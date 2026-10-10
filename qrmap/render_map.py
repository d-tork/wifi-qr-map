"""Engraved, hand-coloured 18th-century-style map art, with the QR ward drawn in.

Everything is drawn as uint8 coverage masks at `ss`x supersampling, downsampled to
the output resolution, then composited as ink over washes over parchment.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.affinity import rotate
from shapely.geometry import LineString, MultiPolygon, Polygon, box

from . import config, ward
from .geo import FRAME, WIDTH_M, GeoModel, proj

FONT_FILES = {
    "roman": "im-fell-english-latin-400-normal.woff",
    "italic": "im-fell-english-latin-400-italic.woff",
    "sc": "im-fell-english-sc-latin-400-normal.woff",
    "caslon": "libre-caslon-text-latin-400-normal.woff",  # clear lining figures for the legend
}


def font(style: str, px: float) -> ImageFont.FreeTypeFont:
    name = {"caps": "roman", "sc": "sc"}.get(style, style)
    return ImageFont.truetype(str(config.FONTS / FONT_FILES[name]), max(6, round(px)))


class Canvas:
    """Maps local metres to supersampled pixels inside the layout's map box."""

    def __init__(self, layout: config.Layout, ss: int):
        self.layout, self.ss = layout, ss
        self.size = layout.size * ss
        x0, y0, x1, y1 = layout.map_box
        self.box = (x0 * ss, y0 * ss, x1 * ss, y1 * ss)
        self.k = (x1 - x0) * ss / WIDTH_M  # pixels per metre on the ground

    def xy(self, x: float, y: float) -> tuple[float, float]:
        return self.box[0] + x * self.k, self.box[3] - y * self.k

    def m(self, metres: float) -> float:
        """Stroke or symbol size, in metres at the 2-mile reference scale -> pixels."""
        return metres * config.STYLE * self.k

    def new(self) -> Image.Image:
        return Image.new("L", (self.size, self.size), 0)

    def polygon(self, draw: ImageDraw.ImageDraw, geom, fill=255):
        for p in _polys(geom):
            draw.polygon([self.xy(*c) for c in p.exterior.coords], fill=fill)
            for hole in p.interiors:
                draw.polygon([self.xy(*c) for c in hole.coords], fill=0)

    def line(self, draw, geom, width, fill=255):
        for ls in _lines(geom):
            pts = [self.xy(*c) for c in ls.coords]
            if len(pts) >= 2:
                draw.line(pts, fill=fill, width=max(1, round(width)), joint="curve")
                r = width / 2
                for p in (pts[0], pts[-1]):
                    draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=fill)


def _polys(g):
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for sub in getattr(g, "geoms", []) for p in _polys(sub)]


def _lines(g):
    if g is None or g.is_empty:
        return []
    if isinstance(g, LineString):
        return [g]
    return [ln for sub in getattr(g, "geoms", []) for ln in _lines(sub)]


def _arr(img: Image.Image) -> np.ndarray:
    return np.asarray(img, dtype=np.uint8)


def _hatch(shape, period, width, angle_deg) -> np.ndarray:
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    a = math.radians(angle_deg)
    d = xx * math.cos(a) + yy * math.sin(a)
    return ((d % period) < width).astype(np.uint8) * 255


def _noise(shape, rng, scales=((8, 0.5), (40, 0.3), (180, 0.2))) -> np.ndarray:
    h, w = shape
    out = np.zeros(shape, np.float32)
    for s, amp in scales:
        small = rng.standard_normal((max(2, h // s), max(2, w // s))).astype(np.float32)
        out += amp * cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    return out / max(1e-6, out.std())


def render(model: GeoModel, layout: config.Layout, ss: int = 2, seed: int = 1749,
           district=None, code=None, legend: dict | None = None) -> dict:
    """Returns {"rgb": float32 HxWx3 in 0..1 at output size, plus named 1x masks}."""
    rng = np.random.default_rng(seed)
    cv = Canvas(layout, ss)
    S = cv.size
    land = FRAME.difference(model.water) if model.water is not None else FRAME

    layers = {k: cv.new() for k in ("water", "blocks", "parks", "fields", "ink")}
    d = {k: ImageDraw.Draw(v) for k, v in layers.items()}
    clip = cv.new()
    ImageDraw.Draw(clip).rectangle(cv.box, fill=255)

    # --- water and water-lining (engraved lines parallel to the shore) ---
    cv.polygon(d["water"], model.water)
    for ls, _ in model.streams:
        cv.line(d["water"], ls.intersection(land), cv.m(14))
    water = _arr(layers["water"])
    # Measure distance from the shore only, not from the map's neat line.
    wet = (water > 127) | (_arr(clip) == 0)
    dist = cv2.distanceTransform(wet.astype(np.uint8), cv2.DIST_L2, 5)
    lw = max(1.0, 1.1 * ss)
    rings = np.zeros_like(dist, dtype=bool)
    step = cv.m(16)
    for i in range(9):
        r = step * (i + 1) ** 1.35
        rings |= (dist > r) & (dist < r + lw * (1.3 - i * 0.08))
    open_water = dist > step * 10 ** 1.35
    ruling = (np.arange(S)[:, None] % max(3, round(cv.m(18))) < lw * 0.8) & open_water
    water_ink = ((rings | ruling) & (water > 127)).astype(np.uint8) * 200

    # --- open country: fields with furrows, woods, hedgerows ---
    trees = []
    for fpoly in model.fields:
        cells = []
        cell = 260.0
        ang = rng.uniform(-25, 25)
        minx, miny, maxx, maxy = fpoly.bounds
        for gx in np.arange(minx - cell, maxx + cell, cell):
            for gy in np.arange(miny - cell, maxy + cell, cell * 0.8):
                c = box(gx + rng.uniform(-40, 40), gy, gx + cell + rng.uniform(-40, 40), gy + cell * 0.8)
                c = rotate(c, ang, origin=fpoly.centroid)
                c = c.intersection(fpoly).intersection(land).buffer(-6)
                if not c.is_empty and c.area > 3_000:
                    cells.append(c)
        for c in cells:
            kind = rng.choice(["furrow", "furrow", "wood", "meadow"])
            if kind == "wood":
                trees.append(c)
                continue
            cv.polygon(d["fields"], c)
            if kind == "furrow":
                bx0, by1 = cv.xy(c.bounds[0], c.bounds[1])
                bx1, by0 = cv.xy(c.bounds[2], c.bounds[3])
                bb = (int(bx0), int(by0), int(bx1) + 1, int(by1) + 1)
                m = Image.new("L", (bb[2] - bb[0], bb[3] - bb[1]), 0)
                md = ImageDraw.Draw(m)
                for p in _polys(c):
                    md.polygon([(u - bb[0], v - bb[1]) for u, v in (cv.xy(*q) for q in p.exterior.coords)], fill=255)
                pat = _hatch(m.size[::-1], max(4, cv.m(11)), lw, rng.uniform(0, 180))
                region = _arr(layers["ink"].crop(bb))
                layers["ink"].paste(Image.fromarray(np.maximum(region, np.minimum(_arr(m), pat) // 2)), bb[:2])
            for p in _polys(c):
                cv.line(d["ink"], p.exterior, lw * 1.2, 160)  # hedge

    # --- parks and woods: tree symbols ---
    for p in model.parks:
        cv.polygon(d["parks"], p.intersection(land))
    trees.extend(model.parks)
    for p in trees:
        p = p.intersection(land)
        if p.is_empty:
            continue
        minx, miny, maxx, maxy = p.bounds
        sp = 38.0 * config.STYLE
        for gx in np.arange(minx, maxx, sp):
            for gy in np.arange(miny, maxy, sp * 0.85):
                x, y = gx + rng.uniform(-12, 12) * config.STYLE, gy + rng.uniform(-10, 10) * config.STYLE
                if not p.contains(_pt(x, y)):
                    continue
                cx, cy = cv.xy(x, y)
                r = cv.m(rng.uniform(10, 14))
                d["ink"].ellipse([cx - r, cy - r, cx + r, cy + r], outline=230, width=max(1, round(lw)))
                d["ink"].pieslice([cx - r, cy - r, cx + r, cy + r], 330, 120, fill=170)
                d["ink"].line([cx, cy + r, cx, cy + r * 1.5], fill=230, width=max(1, round(lw)))
                d["parks"].ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)

    # --- hills: radial hachures ---
    for hx, hy, hr in model.hills:
        cx, cy = cv.xy(hx, hy)
        R = hr * cv.k  # hills are real ground sizes
        n = int(2 * math.pi * R / max(3, lw * 4.5))
        for i in range(n):
            a = 2 * math.pi * i / n + rng.uniform(-0.02, 0.02)
            r0 = R * rng.uniform(0.45, 0.55)
            r1 = R * rng.uniform(0.8, 1.0)
            # Shade the south-east slopes heavier, as engravers lit hills from the north-west.
            heavy = 0.5 + 0.5 * math.cos(a - math.radians(-45))
            d["ink"].line([cx + r0 * math.cos(a), cy + r0 * math.sin(a),
                           cx + r1 * math.cos(a), cy + r1 * math.sin(a)],
                          fill=int(90 + 120 * heavy), width=max(1, round(lw * (0.6 + 0.7 * heavy))))

    # --- blocks: carmine wash, diagonal hatching, ink outline ---
    blocks = model.blocks()
    for b in blocks:
        cv.polygon(d["blocks"], b)
        for p in _polys(b):  # shrinking a block off the kerb can split it in two
            cv.line(d["ink"], p.exterior, lw * 1.3, 235)
    bmask = _arr(layers["blocks"])
    hatch = _hatch((S, S), max(4, cv.m(7.5)), lw, 45)
    ink = np.maximum(_arr(layers["ink"]), np.minimum(bmask, hatch) * 0.8).astype(np.uint8)
    layers["ink"] = Image.fromarray(ink)
    d["ink"] = ImageDraw.Draw(layers["ink"])

    # --- roads: double-ruled, major roads wider ---
    roads = [(g.intersection(land), cls, name) for g, cls, name in model.roads]
    for g, cls, _ in roads:
        w = cv.m(26 if cls == "major" else 16)
        cv.line(d["ink"], g, w + lw * 2.6, 245)
    for g, cls, _ in roads:
        w = cv.m(26 if cls == "major" else 16)
        cv.line(d["ink"], g, w, 0)
        cv.line(d["blocks"], g, w, 0)
        cv.line(d["parks"], g, w, 0)
        cv.line(d["fields"], g, w, 0)

    # --- railway: single rule with cross-ticks ---
    for r in model.rail:
        for ls in _lines(r.intersection(land)):
            cv.line(d["ink"], ls, lw * 2.2, 240)
            L = ls.length
            tick = 9 * config.STYLE
            for t in np.arange(0, L, 30 * config.STYLE):
                p0, p1 = ls.interpolate(t), ls.interpolate(min(L, t + 1))
                dx, dy = p1.x - p0.x, p1.y - p0.y
                n = math.hypot(dx, dy) or 1
                a = cv.xy(p0.x - dy / n * tick, p0.y + dx / n * tick)
                b = cv.xy(p0.x + dy / n * tick, p0.y - dx / n * tick)
                d["ink"].line([a, b], fill=220, width=max(1, round(lw)))

    # --- streams: double line ---
    for ls, _ in model.streams:
        g = ls.intersection(land)
        cv.line(d["ink"], g, cv.m(14) + lw * 2.4, 230)
        cv.line(d["ink"], g, cv.m(14), 0)

    # --- shoreline: heavy rule ---
    if model.water is not None:
        for p in _polys(model.water):
            for ring in [p.exterior, *p.interiors]:
                seg = ring.difference(FRAME.exterior.buffer(1))
                cv.line(d["ink"], seg, lw * 2.6, 255)

    ink = np.maximum(_arr(layers["ink"]), water_ink)
    layers["ink"] = Image.fromarray(ink)
    d["ink"] = ImageDraw.Draw(layers["ink"])

    occupied = []
    if district is not None:
        ward.draw_ward(cv, layers, district, code, rng, lw)
        occupied.append(district.bbox(ss, extra=0.5))
    if legend:
        ward.draw_legend(cv, layers, legend, lw, font, occupied)
    d = {k: ImageDraw.Draw(v) for k, v in layers.items()}
    _landmarks(cv, d["ink"], model, lw, occupied)
    _place_labels(cv, layers["ink"], model, roads, occupied, rng)
    _compass(cv, ImageDraw.Draw(layers["ink"]), round(0.95 * layout.dpi * ss), lw)

    # --- downsample masks and composite ---
    out = layout.size
    to1 = {k: np.asarray(v.resize((out, out), Image.LANCZOS), np.float32) / 255
           for k, v in {**layers, "clip": clip}.items()}
    to1.setdefault("ward", np.zeros((out, out), np.float32))
    rgb = _parchment((out, out), rng)
    inside = to1["clip"][..., None]
    for key, col, strength in (("fields", config.FIELD_WASH, 0.55), ("parks", config.PARK_WASH, 0.6),
                               ("blocks", config.BLOCK_WASH, 0.8), ("ward", config.BLOCK_WASH, 0.9),
                               ("water", config.WATER_WASH, 0.8)):
        a = (to1[key] * strength)[..., None] * inside
        rgb = rgb * (1 - a) + rgb * (np.array(col, np.float32) / 255) * a  # multiply wash
    ia = (np.clip(to1["ink"] * 1.05, 0, 1) * 0.94)[..., None] * inside
    rgb = rgb * (1 - ia) + (np.array(config.INK, np.float32) / 255) * ia
    return {"rgb": np.clip(rgb, 0, 1), **{k: to1[k] for k in ("water", "blocks", "ward", "ink")}}


def _pt(x, y):
    from shapely.geometry import Point
    return Point(x, y)


def _parchment(shape, rng) -> np.ndarray:
    h, w = shape
    base = np.array(config.PARCHMENT, np.float32) / 255
    n = _noise(shape, rng)
    stains = _noise(shape, rng, scales=((300, 0.7), (900, 0.3)))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    edge = np.minimum.reduce([xx, yy, w - 1 - xx, h - 1 - yy]) / (0.08 * w)
    vignette = 1 - 0.10 * np.clip(1 - edge, 0, 1) ** 2
    shade = (1 + 0.018 * n - 0.025 * np.clip(stains, 0, None)) * vignette
    tint = np.stack([shade, shade * (1 - 0.006 * stains), shade * (1 - 0.02 * stains)], -1)
    return np.clip(base * tint, 0, 1).astype(np.float32)


def _inside(bb, x, y, pad=0):
    return bb[0] - pad <= x <= bb[2] + pad and bb[1] - pad <= y <= bb[3] + pad


def _landmarks(cv: Canvas, draw, model: GeoModel, lw, occupied):
    w = max(1, round(lw * 1.4))
    for x, y, kind, _ in model.landmarks:
        cx, cy = cv.xy(x, y)
        s = cv.m(22)
        if any(_inside(bb, cx, cy, s * 2.5) for bb in occupied):
            continue
        if kind == "church":
            draw.rectangle([cx - s * .5, cy - s * .35, cx + s * .5, cy + s * .35], fill=250)
            draw.line([cx, cy - s * 1.3, cx, cy - s * .35], fill=250, width=w)
            draw.line([cx - s * .3, cy - s * 1.0, cx + s * .3, cy - s * 1.0], fill=250, width=w)
        elif kind == "temple":  # the Masonic Memorial's stepped tower
            for i, f in enumerate((1.0, .75, .55, .38, .22)):
                draw.rectangle([cx - s * f, cy + s * .9 - s * .55 * (i + 1), cx + s * f, cy + s * .9 - s * .55 * i],
                               outline=250, width=w)
            draw.polygon([(cx - s * .22, cy - s * 1.85), (cx + s * .22, cy - s * 1.85), (cx, cy - s * 2.4)], fill=250)
        elif kind == "market":
            draw.rectangle([cx - s * .6, cy - s * .6, cx + s * .6, cy + s * .6], outline=250, width=w)
            draw.rectangle([cx - s * .2, cy - s * .2, cx + s * .2, cy + s * .2], fill=250)
        elif kind == "lighthouse":
            draw.polygon([(cx - s * .3, cy + s * .5), (cx + s * .3, cy + s * .5), (cx + s * .15, cy - s * .8),
                          (cx - s * .15, cy - s * .8)], fill=250)
            for a in range(0, 360, 45):
                r0, r1 = s * 1.0, s * 1.6
                ar = math.radians(a)
                draw.line([cx + r0 * math.cos(ar), cy - s * .8 + r0 * math.sin(ar),
                           cx + r1 * math.cos(ar), cy - s * .8 + r1 * math.sin(ar)], fill=200, width=w)


def _text_img(text, fnt, tracking_px):
    widths = [fnt.getlength(ch) for ch in text]
    total = sum(widths) + tracking_px * max(0, len(text) - 1)
    asc, desc = fnt.getmetrics()
    img = Image.new("L", (int(total + 8), asc + desc + 8), 0)
    dr = ImageDraw.Draw(img)
    x = 4.0
    for ch, wd in zip(text, widths):
        dr.text((x, 4), ch, font=fnt, fill=255)
        x += wd + tracking_px
    return img


def _stamp(canvas_img: Image.Image, txt: Image.Image, cx, cy, angle, occupied, force=False) -> bool:
    rot = txt.rotate(angle, expand=True, resample=Image.BICUBIC)
    x0, y0 = int(cx - rot.width / 2), int(cy - rot.height / 2)
    bb = (x0, y0, x0 + rot.width, y0 + rot.height)
    if not force:
        for o in occupied:
            if bb[0] < o[2] and bb[2] > o[0] and bb[1] < o[3] and bb[3] > o[1]:
                return False
    occupied.append(bb)
    region = canvas_img.crop(bb)
    canvas_img.paste(Image.fromarray(np.maximum(_arr(region), _arr(rot))), bb[:2])
    return True


def _place_labels(cv: Canvas, ink_img, model, roads, occupied, rng):
    base = cv.layout.dpi * cv.ss * 0.115
    for lb in model.labels:
        fnt = font(lb.style, base * lb.size)
        text = lb.text.upper() if lb.style == "caps" else lb.text
        txt = _text_img(text, fnt, lb.tracking * base * lb.size)
        cx, cy = cv.xy(*proj(lb.lat, lb.lon))
        # Place names are kept, but nudged upward off the ward, the legend and each other.
        for _ in range(40):
            if _stamp(ink_img, txt, cx, cy, lb.angle, occupied):
                break
            cy -= txt.height * 0.6
    # Street names along their longest straight run, keeping text upright.
    seen = set()
    by_name = {}
    for g, cls, name in roads:
        if name:
            by_name.setdefault(name, []).extend((ls, cls) for ls in _lines(g))
    order = sorted(by_name.items(), key=lambda kv: -max(ls.length for ls, _ in kv[1]))
    for name, parts in order:
        if name in seen:
            continue
        ls, cls = max(parts, key=lambda p: p[0].length)
        if ls.length < 300 * config.STYLE:
            continue
        fnt = font("italic", base * (0.78 if cls == "major" else 0.62))
        txt = _text_img(name, fnt, 0)
        if ls.length * cv.k < txt.width * 1.3:
            continue
        for frac in (0.5, 0.3, 0.7):
            p = ls.interpolate(frac, normalized=True)
            q = ls.interpolate(min(1, frac + 0.02), normalized=True)
            ax, ay = cv.xy(p.x, p.y)
            bx, by = cv.xy(q.x, q.y)
            ang = -math.degrees(math.atan2(by - ay, bx - ax))
            if ang > 90:
                ang -= 180
            elif ang < -90:
                ang += 180
            if _stamp(ink_img, txt, ax, ay, ang, occupied):
                seen.add(name)
                break


def _compass(cv: Canvas, draw, size, lw):
    """Compass rose in the lower-right corner of the map (river side)."""
    x1, y1 = cv.box[2], cv.box[3]
    R = size * 0.42
    cx, cy = x1 - size * 0.5, y1 - size * 0.55
    w = max(1, round(lw))
    draw.ellipse([cx - R * .55, cy - R * .55, cx + R * .55, cy + R * .55], outline=150, width=w)
    for i in range(16):
        a = math.radians(i * 22.5)
        L = R if i % 4 == 0 else (R * .62 if i % 2 == 0 else R * .4)
        tip = (cx + L * math.sin(a), cy - L * math.cos(a))
        sa, sb = a + math.pi / 2, a - math.pi / 2
        bw = R * (0.12 if i % 4 == 0 else 0.07)
        p1 = (cx + bw * math.sin(sa), cy - bw * math.cos(sa))
        p2 = (cx + bw * math.sin(sb), cy - bw * math.cos(sb))
        draw.polygon([tip, p1, (cx, cy)], fill=170)
        draw.polygon([tip, p2, (cx, cy)], outline=170)
    f = font("caps", R * 0.38)
    draw.text((cx, cy - R * 1.02), "N", font=f, fill=200, anchor="ms")
