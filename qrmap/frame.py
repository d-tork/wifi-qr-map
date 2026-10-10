"""Sheet furniture outside the map: graduated neat line, title, scale, attribution."""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from . import config
from .geo import MY, WIDTH_M, proj
from .render_map import font

MILE = 1609.344


def _dms(v: float, pos: str, neg: str) -> str:
    h = pos if v >= 0 else neg
    v = abs(v)
    d = int(v)
    m = round((v - d) * 60)
    if m == 60:
        d, m = d + 1, 0
    return f"{d}°{m:02d}' {h}"


def draw(img: Image.Image, layout: config.Layout, source: str, subtitle: str | None = None):
    dr = ImageDraw.Draw(img)
    ink = config.INK
    dpi = layout.dpi
    x0, y0, x1, y1 = layout.map_box
    k = (x1 - x0) / WIDTH_M
    band = round(0.085 * dpi)
    lw = max(1, round(dpi / 150))

    # Graduated border: alternating ink/paper every 15 seconds of arc.
    dr.rectangle([x0 - 1, y0 - 1, x1, y1], outline=ink, width=lw)
    dr.rectangle([x0 - band, y0 - band, x1 + band, y1 + band], outline=ink, width=lw)
    dr.rectangle([x0 - band - 3 * lw, y0 - band - 3 * lw, x1 + band + 3 * lw, y1 + band + 3 * lw],
                 outline=ink, width=lw * 2)
    step = 15 / 3600
    small = font("italic", dpi * 0.085)

    lat = math.floor(config.SOUTH / step) * step
    i = int(round(lat / step))
    while lat < config.NORTH:
        a = max(config.SOUTH, lat)
        b = min(config.NORTH, lat + step)
        ya, yb = y1 - (a - config.SOUTH) * MY * k, y1 - (b - config.SOUTH) * MY * k
        if i % 2 == 0:
            dr.rectangle([x0 - band, yb, x0 - 1, ya], fill=ink)
            dr.rectangle([x1, yb, x1 + band, ya], fill=ink)
        if i % 4 == 0 and config.SOUTH < lat:
            t = _dms(lat, "N", "S")
            dr.text((x0 - band - 6 * lw, ya), t, font=small, fill=ink, anchor="rm")
            dr.text((x1 + band + 6 * lw, ya), t, font=small, fill=ink, anchor="lm")
        lat += step
        i += 1

    lon = math.floor(config.WEST / step) * step
    i = int(round(lon / step))
    while lon < config.EAST:
        a, b = max(config.WEST, lon), min(config.EAST, lon + step)
        xa, xb = x0 + proj(config.SOUTH, a)[0] * k, x0 + proj(config.SOUTH, b)[0] * k
        if i % 2 == 0:
            dr.rectangle([xa, y0 - band, xb, y0 - 1], fill=ink)
            dr.rectangle([xa, y1, xb, y1 + band], fill=ink)
        if i % 4 == 0 and config.WEST < lon:
            t = _dms(lon, "E", "W")
            dr.text((xa, y0 - band - 6 * lw), t, font=small, fill=ink, anchor="ms")
            dr.text((xa, y1 + band + 6 * lw), t, font=small, fill=ink, anchor="mt")
        lon += step
        i += 1

    # Title.
    cx = layout.size / 2
    top = y0 - band - round(0.2 * dpi)
    title = font("roman", dpi * 0.30)
    sub = font("italic", dpi * 0.135)
    dr.text((cx, top - round(0.24 * dpi)), "A  PLAN  of  the  TOWN  of  ALEXANDRIA", font=title, fill=ink, anchor="ms")
    dr.text((cx, top - round(0.01 * dpi)),
            subtitle or "with ROSEMONT and the late TOWN of POTOMAC, call’d DEL RAY, in VIRGINIA",
            font=sub, fill=ink, anchor="ms")

    # Scale of one mile, divided into furlongs.
    sy = y1 + band + round(0.36 * dpi)
    sx = x0
    L = MILE * k
    h = round(0.05 * dpi)
    for f in range(8):
        xa, xb = sx + L * f / 8, sx + L * (f + 1) / 8
        dr.rectangle([xa, sy, xb, sy + h], outline=ink, width=lw, fill=ink if f % 2 == 0 else None)
    lab = font("italic", dpi * 0.09)
    dr.text((sx, sy + h + 4 * lw), "0", font=lab, fill=ink, anchor="mt")
    dr.text((sx + L / 2, sy + h + 4 * lw), "4 Furlongs", font=lab, fill=ink, anchor="mt")
    dr.text((sx + L, sy + h + 4 * lw), "1 Mile", font=lab, fill=ink, anchor="mt")
    dr.text((sx + L / 2, sy - 4 * lw), "A Scale of One Mile", font=lab, fill=ink, anchor="ms")

    attrib = font("italic", dpi * 0.075)
    dr.text((x1, sy + h // 2), source, font=attrib, fill=ink, anchor="rm")
