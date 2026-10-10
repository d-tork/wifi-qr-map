"""The hidden QR as a few blocks of houses, plus the legend cartouche and Wi-Fi mark.

The ward is laid out like the rest of the town (see houses.py), on the same plot size:
  - dark modules -> houses, light modules -> empty plots (yards)
  - narrow streets run along module edges every few modules, cutting the symbol into
    blocks about the size of Old Town's, never through a finder or alignment pattern
  - finder patterns -> courtyard blocks: a ring of terraced houses round a court,
    with a hall in the middle; alignment patterns are smaller courts of the same kind
  - quiet zone -> front gardens and a wide street round the ward, where the real
    streets stop and the neighbouring blocks turn their houses to face it
Streets and walls lie on module edges, so every module centre keeps its value.
"""

from __future__ import annotations

from PIL import ImageDraw

from . import config, houses
from .district import District
from .qr import Code


def street_cuts(n: int, alignment, spacing: float) -> list[int]:
    """Module edges (between module p-1 and p) where the ward's streets run, along one
    axis. The outermost run beside the finder patterns and separators, at 8 and n - 8;
    the rest split the span between into blocks of about `spacing` modules, nudged so
    no street splits an alignment pattern (rows of `alignment` are along the street)."""
    lo, hi = 8, n - 8
    if hi <= lo:
        return []
    k = max(1, round((hi - lo) / spacing))
    cuts = []
    for i in range(k + 1):
        p = lo + round(i * (hi - lo) / k)
        for q in (p, p - 1, p + 1, p - 2, p + 2, p - 3, p + 3):
            if lo <= q <= hi and q not in cuts and not (alignment[:, q - 1] & alignment[:, q]).any():
                cuts.append(q)
                break
    return sorted(cuts)


def draw_ward(cv, layers: dict, dist: District, code: Code, rng, lw: float, long_axis: str = "v"):
    """`long_axis` is the way the town's blocks run nearby, in the ward's own frame:
    "u" along its rows, "v" along its columns. The ward's blocks run the same way."""
    ss = cv.ss
    reserve = dist.reserve(ss)
    for img in layers.values():
        ImageDraw.Draw(img).polygon(reserve, fill=0)

    n = code.n
    across, along = config.WARD_BLOCK
    cols = street_cuts(n, code.alignment, along if long_axis == "u" else across)  # vertical streets
    rows = street_cuts(n, code.alignment.T, across if long_axis == "u" else along)  # horizontal streets
    half = config.WARD_STREET / 2
    g = config.WARD_GARDEN

    # Blocks: yards between the streets, with front gardens spilling into the quiet zone
    # on the outside, outlined in ink like every other block.
    yards = ImageDraw.Draw(layers["yards"])
    ink = ImageDraw.Draw(layers["ink"])
    us, vs = [0, *cols, n], [0, *rows, n]
    for ua, ub in zip(us, us[1:]):
        for va, vb in zip(vs, vs[1:]):
            u0, u1 = ua + (half if ua else -g), ub - (half if ub < n else -g)
            v0, v1 = va + (half if va else -g), vb - (half if vb < n else -g)
            sq = dist.square(u0, v0, u1, v1, ss)
            yards.polygon(sq, fill=255)
            ink.line([*sq, sq[0]], fill=235, width=max(1, round(lw * 1.3)), joint="curve")

    # Houses on the dark modules, set back from the ward's streets.
    pattern = code.finder | code.alignment
    cu, cr = set(cols), set(rows)
    built, walls = [], []
    for r in range(n):
        for c in range(n):
            if not code.dark[r, c]:
                continue
            u0, u1 = c + (half if c in cu else 0), c + 1 - (half if c + 1 in cu else 0)
            v0, v1 = r + (half if r in cr else 0), r + 1 - (half if r + 1 in cr else 0)
            built.append(dist.square(u0, v0, u1, v1, ss))
            # Party walls between some neighbours; courts and halls stay one building.
            if pattern[r, c]:
                continue
            if c + 1 < n and code.dark[r, c + 1] and not pattern[r, c + 1] and c + 1 not in cu \
                    and rng.random() < config.PARTY_WALL_CHANCE:
                walls.append([dist.to_px(c + 1, v0, ss), dist.to_px(c + 1, v1, ss)])
            if r + 1 < n and code.dark[r + 1, c] and not pattern[r + 1, c] and r + 1 not in cr \
                    and rng.random() < config.PARTY_WALL_CHANCE:
                walls.append([dist.to_px(u0, r + 1, ss), dist.to_px(u1, r + 1, ss)])
    houses.draw(layers, built, walls, lw)


def wifi_mark(draw, cx, cy, s, fill=255, width=2):
    """The Wi-Fi sign: a dot with two arcs above it. `s` is the outer arc radius."""
    r = s * 0.16
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
    for rad in (s * 0.55, s * 0.98):
        draw.arc([cx - rad, cy - rad, cx + rad, cy + rad], 222, 318, fill=fill, width=width)


def legend_box(cv, legend: dict, font) -> dict:
    """Fonts, metrics and the box (supersampled pixels) of the cartouche: title, then
    'label ...... value' rows (the lettered references, then the network name keyed by
    the Wi-Fi mark alone), then the password by itself on the last line, unlabelled."""
    from .geo import proj

    ss, dpi = cv.ss, cv.layout.dpi
    base = dpi * ss * config.LEGEND_TEXT_INCHES
    L = {"base": base, "f_title": font("caps", base * 1.05), "f_label": font("italic", base),
         "f_value": font("caslon", base * 0.95), "pad": base * 0.9, "icon": base * 1.1,
         "line_h": base * 1.55, "rows": [*legend.get("refs", []), ("", legend["network"])],
         "icon_row": len(legend.get("refs", [])), "password": legend.get("password")}
    rows = L["rows"]
    lab_w = max([L["f_label"].getlength(lb) for lb, _ in rows] + [L["icon"]])
    val_w = max(L["f_value"].getlength(v) for _, v in rows)
    pw_w = L["f_value"].getlength(L["password"]) if L["password"] else 0
    L["title_w"] = L["f_title"].getlength(" ".join(legend["title"]))
    W = max(lab_w + base * 1.6 + val_w, L["title_w"], pw_w) + 2 * L["pad"]
    H = L["pad"] * 2 + L["line_h"] * (len(rows) + 1.2 + (1.15 if L["password"] else 0))

    cx, cy = cv.xy(*proj(*legend.get("center", config.LEGEND_CENTER)))
    bx0, by0, bx1, by1 = cv.box
    cx = min(max(cx, bx0 + W / 2 + base), bx1 - W / 2 - base)
    cy = min(max(cy, by0 + H / 2 + base), by1 - H / 2 - base)
    L["box"] = (cx - W / 2, cy - H / 2, cx + W / 2, cy + H / 2)
    return L


def draw_legend(cv, layers: dict, legend: dict, lw: float, font, occupied: list):
    """A ruled cartouche, as on an engraved plan's table of references."""
    L = legend_box(cv, legend, font)
    base, pad, icon = L["base"], L["pad"], L["icon"]
    f_label, f_value = L["f_label"], L["f_value"]
    x0, y0, x1, y1 = L["box"]
    cx = (x0 + x1) / 2
    for img in layers.values():
        ImageDraw.Draw(img).rectangle([x0, y0, x1, y1], fill=0)
    occupied.append(L["box"])

    d = ImageDraw.Draw(layers["ink"])
    w = max(1, round(lw))
    d.rectangle([x0, y0, x1, y1], outline=240, width=w * 2)
    g = base * 0.22
    d.rectangle([x0 + g, y0 + g, x1 - g, y1 - g], outline=200, width=w)

    ty = y0 + pad + base * 0.55
    title_w = L["title_w"]
    d.text((cx, ty), " ".join(legend["title"]), font=L["f_title"], fill=245, anchor="mm")
    d.line([cx - title_w * 0.35, ty + base * 0.75, cx + title_w * 0.35, ty + base * 0.75], fill=170, width=w)

    for i, (label, value) in enumerate(L["rows"]):
        y = ty + L["line_h"] * (i + 1.15)
        lx = x0 + pad
        if i == L["icon_row"]:  # the Wi-Fi mark stands where a reference letter would
            wifi_mark(d, lx + icon * 0.45, y + base * 0.22, icon * 0.5, fill=225, width=w + 1)
            key_w = icon * 0.9
        else:
            d.text((lx, y), label, font=f_label, fill=240, anchor="lm")
            key_w = f_label.getlength(label)
        vx = x1 - pad - f_value.getlength(value)
        d.text((x1 - pad, y), value, font=f_value, fill=250, anchor="rm")
        # Dotted leader between key and value, as in an engraved table of references.
        sx = lx + key_w + base * 0.4
        ex = vx - base * 0.4
        step = base * 0.32
        t = sx
        while t < ex:
            d.ellipse([t - w, y + base * 0.12 - w, t + w, y + base * 0.12 + w], fill=150)
            t += step
    if L["password"]:  # alone, centred, under a short rule
        y = ty + L["line_h"] * (len(L["rows"]) + 1.3)
        d.line([cx - title_w * 0.2, y - L["line_h"] * 0.55, cx + title_w * 0.2, y - L["line_h"] * 0.55],
               fill=150, width=w)
        d.text((cx, y), L["password"], font=f_value, fill=250, anchor="mm")
