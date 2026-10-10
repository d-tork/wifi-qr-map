"""Sheet furniture outside the map: graduated neat line, title, scale, attribution."""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from . import config
from .geo import MY, WIDTH_M, proj
from .render_map import font

MILE = config.MILE
# Border graduations (seconds of arc), and scale bars as
# (miles, title, divisions, middle label, end label).
STEPS = (5, 10, 15, 30, 60, 120, 300, 600)
SCALES = ((0.25, "a Quarter Mile", 2, "1 Furlong", "2 Furlongs"),
          (0.5, "Half a Mile", 4, "2 Furlongs", "4 Furlongs"),
          (1, "One Mile", 8, "4 Furlongs", "1 Mile"),
          (2, "Two Miles", 4, "1 Mile", "2 Miles"),
          (5, "Five Miles", 5, "", "5 Miles"))


def _dms(v: float, pos: str, neg: str) -> str:
    h = pos if v >= 0 else neg
    sec = round(abs(v) * 3600)
    d, m, s = sec // 3600, sec // 60 % 60, sec % 60
    return f"{d}°{m:02d}' {s:02d}\" {h}" if s else f"{d}°{m:02d}' {h}"


def graduation() -> float:
    """Border band width in degrees: at most 16 bands along the longer side."""
    span = max(config.NORTH - config.SOUTH, config.EAST - config.WEST) * 3600
    return next((s for s in STEPS if span / s <= 16), STEPS[-1]) / 3600


def scale_bar() -> tuple:
    """Longest scale that fits in 40% of the map's width."""
    fits = [sc for sc in SCALES if sc[0] * MILE <= 0.4 * WIDTH_M]
    return fits[-1] if fits else SCALES[0]


def draw(img: Image.Image, layout: config.Layout, source: str):
    dr = ImageDraw.Draw(img)
    ink = config.INK
    dpi = layout.dpi
    x0, y0, x1, y1 = layout.map_box
    k = (x1 - x0) / WIDTH_M
    band = round(0.085 * dpi)
    lw = max(1, round(dpi / 150))

    # Graduated border: alternating ink/paper bands of a few seconds of arc.
    dr.rectangle([x0 - 1, y0 - 1, x1, y1], outline=ink, width=lw)
    dr.rectangle([x0 - band, y0 - band, x1 + band, y1 + band], outline=ink, width=lw)
    dr.rectangle([x0 - band - 3 * lw, y0 - band - 3 * lw, x1 + band + 3 * lw, y1 + band + 3 * lw],
                 outline=ink, width=lw * 2)
    step = graduation()
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
    cx = layout.width / 2
    top = y0 - band - round(0.2 * dpi)
    title = font("roman", dpi * 0.30)
    sub = font("italic", dpi * 0.135)
    if config.SUBTITLE:
        dr.text((cx, top - round(0.24 * dpi)), config.TITLE, font=title, fill=ink, anchor="ms")
        dr.text((cx, top - round(0.01 * dpi)), config.SUBTITLE, font=sub, fill=ink, anchor="ms")
    else:
        dr.text((cx, top - round(0.08 * dpi)), config.TITLE, font=title, fill=ink, anchor="ms")

    # Scale bar, divided into furlongs or miles.
    miles, name, parts, mid, end = scale_bar()
    sy = y1 + band + round(0.36 * dpi)
    sx = x0
    L = miles * MILE * k
    h = round(0.05 * dpi)
    for f in range(parts):
        xa, xb = sx + L * f / parts, sx + L * (f + 1) / parts
        dr.rectangle([xa, sy, xb, sy + h], outline=ink, width=lw, fill=ink if f % 2 == 0 else None)
    lab = font("italic", dpi * 0.09)
    dr.text((sx, sy + h + 4 * lw), "0", font=lab, fill=ink, anchor="mt")
    if mid:
        dr.text((sx + L / 2, sy + h + 4 * lw), mid, font=lab, fill=ink, anchor="mt")
    dr.text((sx + L, sy + h + 4 * lw), end, font=lab, fill=ink, anchor="mt")
    dr.text((sx + L / 2, sy - 4 * lw), f"A Scale of {name}", font=lab, fill=ink, anchor="ms")

    attrib = font("italic", dpi * 0.075)
    dr.text((x1, sy + h // 2), source, font=attrib, fill=ink, anchor="rm")
