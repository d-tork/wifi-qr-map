"""The hidden QR as a ward of the town, plus the legend cartouche and Wi-Fi mark.

The ward is drawn into the same supersampled layers as the rest of the map, so it
gets the same parchment, washes and ink, and reads as one more neighbourhood:
  - dark modules -> built blocks: carmine wash, hatched, ink-outlined, with narrow
    streets between most neighbours (some merge into larger blocks)
  - light modules -> open lots, outlined faintly
  - finder patterns -> walled squares with bastions at their outer corners
  - quiet zone -> more open lots, where the real streets stop
"""

from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image, ImageDraw

from . import config
from .district import District
from .qr import Code


def _hatch(h, w, period, ink, angle):
    """Anti-aliased parallel rules covering `ink` of each period."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = math.radians(angle)
    d = (xx * math.cos(r) + yy * math.sin(r)) % period
    return np.clip(ink * period / 2 - np.abs(d - period / 2) + 0.5, 0, 1)


def draw_ward(cv, layers: dict, dist: District, code: Code, rng, lw: float):
    ss = cv.ss
    reserve = dist.reserve(ss)
    for img in layers.values():
        ImageDraw.Draw(img).polygon(reserve, fill=0)

    ward = Image.new("L", layers["ink"].size, 0)
    wd = ImageDraw.Draw(ward)
    n = code.n
    for r in range(n):
        for c in range(n):
            if code.dark[r, c]:
                wd.polygon(dist.square(c, r, c + 1, r + 1, ss), fill=255)

    # Streets: the ward is laid out as a grid of small blocks like Old Town's. Built
    # (dark) blocks are separated by a narrow street unless merged into one larger
    # block; finder patterns stay solid. Streets run along module edges, never through
    # a module centre, so every centre keeps its value.
    street = max(1, round(dist.module * ss * config.STREET_FRACTION))
    lots = ImageDraw.Draw(layers["ink"])
    lot_w = max(1, round(ss * 0.8))
    q = dist.quiet

    def dark(r, c):
        return 0 <= r < n and 0 <= c < n and bool(code.dark[r, c])

    def near_finder(r, c):  # finder + separator, plus one module of margin
        lo, hi = -q, 8
        return ((lo <= r <= hi and lo <= c <= hi) or (lo <= r <= hi and n - 9 <= c < n + q)
                or (n - 9 <= r < n + q and lo <= c <= hi))

    for r in range(-q, n + q):
        for c in range(-q, n + q):
            for dr, dc in ((0, 1), (1, 0)):
                r2, c2 = r + dr, c + dc
                if r2 >= n + q or c2 >= n + q:
                    continue
                edge = ([dist.to_px(c2, r, ss), dist.to_px(c2, r + 1, ss)] if dc else
                        [dist.to_px(c, r2, ss), dist.to_px(c + 1, r2, ss)])
                a, b = dark(r, c), dark(r2, c2)
                if a and b:
                    if code.function[r, c] or code.function[r2, c2]:
                        continue
                    if rng.random() < config.STREET_CHANCE:
                        wd.line(edge, fill=0, width=street)
                elif not a and not b and not (near_finder(r, c) or near_finder(r2, c2)):
                    # Open lots, continuing into the quiet zone so the ward has no hard edge.
                    lots.line(edge, fill=config.LOT_INK, width=lot_w)

    # Bastions on the three outward corners of each finder ("walled squares").
    mid = dist.to_px(n / 2, n / 2, ss)
    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):
        for u, v in ((c0, r0), (c0 + 7, r0), (c0, r0 + 7), (c0 + 7, r0 + 7)):
            du = -1 if u == c0 else 1
            dv = -1 if v == r0 else 1
            corner = dist.to_px(u, v, ss)
            if math.dist(dist.to_px(u + du, v + dv, ss), mid) < math.dist(corner, mid):
                continue  # the corner facing the symbol would cut into a separator module
            kite = [(u - du * .6, v - dv * .6), (u - du * .6, v), (u + du * .55, v + dv * .55), (u, v - dv * .6)]
            wd.polygon([dist.to_px(a, b, ss) for a, b in kite], fill=255)

    x0, y0, x1, y1 = (int(v) for v in dist.bbox(ss))
    x0, y0 = max(0, x0), max(0, y0)
    w = np.asarray(ward, np.float32)[y0:y1, x0:x1] / 255
    pitch = cv.layout.dpi * ss * config.HATCH_PITCH
    hatch = _hatch(w.shape[0], w.shape[1], pitch, config.HATCH_INK, 45 - dist.angle)
    k = np.ones((max(2, round(ss * 1.5)),) * 2, np.uint8)
    edge = (w - cv2.erode(w, k)).clip(0, 1)
    ink = np.asarray(layers["ink"], np.float32)
    region = ink[y0:y1, x0:x1]
    ink[y0:y1, x0:x1] = np.maximum(region, 255 * np.maximum(w * hatch, edge))
    layers["ink"] = Image.fromarray(ink.astype(np.uint8))

    layers["ward"] = ward


def wifi_mark(draw, cx, cy, s, fill=255, width=2):
    """The Wi-Fi sign: a dot with two arcs above it. `s` is the outer arc radius."""
    r = s * 0.16
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
    for rad in (s * 0.55, s * 0.98):
        draw.arc([cx - rad, cy - rad, cx + rad, cy + rad], 222, 318, fill=fill, width=width)


def draw_legend(cv, layers: dict, legend: dict, lw: float, font, occupied: list):
    """A ruled cartouche: title, then 'label ...... value' rows."""
    from .geo import proj

    ss, dpi = cv.ss, cv.layout.dpi
    base = dpi * ss * config.LEGEND_TEXT_INCHES
    f_title = font("caps", base * 1.05)
    f_label = font("italic", base)
    f_value = font("caslon", base * 0.95)
    rows = legend["rows"]
    pad = base * 0.9
    leader = base * 1.6
    icon = base * 1.1
    lab_w = max(f_label.getlength(lb) for lb, _ in rows) + icon * 1.4
    val_w = max(f_value.getlength(v) for _, v in rows)
    title_w = f_title.getlength(" ".join(legend["title"]))
    inner_w = max(lab_w + leader + val_w, title_w)
    line_h = base * 1.55
    W = inner_w + 2 * pad
    H = pad * 2 + line_h * (len(rows) + 1.2)

    cx, cy = cv.xy(*proj(*legend.get("center", config.LEGEND_CENTER)))
    bx0, by0, bx1, by1 = cv.box
    m = base
    cx = min(max(cx, bx0 + W / 2 + m), bx1 - W / 2 - m)
    cy = min(max(cy, by0 + H / 2 + m), by1 - H / 2 - m)
    x0, y0, x1, y1 = cx - W / 2, cy - H / 2, cx + W / 2, cy + H / 2
    for img in layers.values():
        ImageDraw.Draw(img).rectangle([x0, y0, x1, y1], fill=0)
    occupied.append((x0, y0, x1, y1))

    d = ImageDraw.Draw(layers["ink"])
    w = max(1, round(lw))
    d.rectangle([x0, y0, x1, y1], outline=240, width=w * 2)
    g = base * 0.22
    d.rectangle([x0 + g, y0 + g, x1 - g, y1 - g], outline=200, width=w)

    ty = y0 + pad + base * 0.55
    d.text((cx, ty), " ".join(legend["title"]), font=f_title, fill=245, anchor="mm")
    d.line([cx - title_w * 0.35, ty + base * 0.75, cx + title_w * 0.35, ty + base * 0.75], fill=170, width=w)

    for i, (label, value) in enumerate(rows):
        y = ty + line_h * (i + 1.15)
        lx = x0 + pad
        if i == 0:
            wifi_mark(d, lx + icon * 0.45, y + base * 0.22, icon * 0.5, fill=225, width=w + 1)
        lx += icon * 1.4
        d.text((lx, y), label, font=f_label, fill=240, anchor="lm")
        vx = x1 - pad - f_value.getlength(value)
        d.text((x1 - pad, y), value, font=f_value, fill=250, anchor="rm")
        # Dotted leader between label and value, as in an engraved table of references.
        sx = lx + f_label.getlength(label) + base * 0.4
        ex = vx - base * 0.4
        step = base * 0.32
        t = sx
        while t < ex:
            d.ellipse([t - w, y + base * 0.12 - w, t + w, y + base * 0.12 + w], fill=150)
            t += step
