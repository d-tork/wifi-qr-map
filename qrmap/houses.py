"""House plots: the texture the QR ward hides in.

Every block on the map is laid out in plots one QR module wide, on a lattice turned
to the block's own long side. A plot either has a house on it or is a yard. Plots on
the street front are mostly built and plots behind them mostly yards, which gives the
same mix of built and empty plots as the ward's dark and light modules.

A few large blocks are built as courts, a ring of terraced houses round a yard with a
hall in the middle, so the ward's finder patterns are one more of a kind the town
already has. Their proportions are deliberately not a finder pattern's 1:1:3:1:1 both
ways (see COURTS), so scanners do not take them for one.

Houses from the map and from the ward go into the same layers ("houses", "walls") and
are finished together by `finish`, so they print identically: carmine wash, engraved
hatching, an ink outline round each terrace, and party walls between some neighbours.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
import shapely
from PIL import Image, ImageDraw
from shapely.geometry import Polygon

from . import config


def _rot(xy: np.ndarray, deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return xy @ np.array([[c, s], [-s, c]])


def _largest(g):
    if g.is_empty:
        return None
    if isinstance(g, Polygon):
        return g
    polys = [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon) and not p.is_empty]
    return max(polys, key=lambda p: p.area) if polys else None


def _court(w, h, yard):
    """Plots of a w x h court: a ring of houses, `yard` plots of yard, then the hall."""
    ii, jj = np.meshgrid(np.arange(w), np.arange(h), indexing="ij")
    ring = np.minimum.reduce([ii, jj, w - 1 - ii, h - 1 - jj])
    return (ring == 0) | (ring > yard)


# Finder-pattern detectors accept a run of five bars as 1:1:3:1:1 when every bar is
# within about half a module (three quarters, relaxed) of its expected width. Every
# court fails that along at least one axis: big courts have a 3-plot yard round a
# single building (1:3:k:3:1), long ones a hall at least 6 plots long (1:1:6+:1:1),
# small ones a 2-plot yard (1:2:1:2:1, 1:2:2:2:1). tests/ checks each one.
COURTS = [_court(11, 11, 3), _court(9, 9, 3), _court(7, 14, 1), _court(14, 7, 1),
          _court(7, 12, 1), _court(12, 7, 1), _court(7, 10, 1), _court(10, 7, 1),
          _court(8, 8, 2), _court(7, 9, 2), _court(9, 7, 2), _court(7, 7, 2)]


def _fit_court(fits: np.ndarray):
    """(i0, j0, built) for the first court in COURTS that fits where `fits` [nx, ny] is
    true, as near the middle of the block as possible; or None."""
    nx, ny = fits.shape
    for built in COURTS:
        w, h = built.shape
        if w > nx or h > ny:
            continue
        win = np.lib.stride_tricks.sliding_window_view(fits, (w, h)).all(axis=(2, 3))
        ok = np.argwhere(win)
        if len(ok):
            i0, j0 = min(ok, key=lambda o: abs(o[0] + w / 2 - nx / 2) + abs(o[1] + h / 2 - ny / 2))
            return int(i0), int(j0), built
    return None


def block_plots(block: Polygon, module: float, rng, court: bool = False) -> tuple[list, list, bool]:
    """Houses and party walls for one block (canvas pixels); with `court`, try to build
    the block as a court.

    Returns (houses, walls, is_court): houses as lists of (x, y) points, walls as point
    pairs."""
    rect = block.minimum_rotated_rectangle
    if not isinstance(rect, Polygon):
        return [], []
    pts = list(rect.exterior.coords)
    (ax, ay), (bx, by) = max(zip(pts, pts[1:]), key=lambda e: math.dist(*e))
    theta = math.degrees(math.atan2(by - ay, bx - ax))
    b = Polygon(_rot(np.asarray(block.exterior.coords), -theta),
                [_rot(np.asarray(h.coords), -theta) for h in block.interiors])
    x0, y0, x1, y1 = b.bounds
    # Whole plots across the block, each within about a quarter of a module of square.
    nx, ny = max(1, round((x1 - x0) / module)), max(1, round((y1 - y0) / module))
    cw, ch = (x1 - x0) / nx, (y1 - y0) / ny
    ii, jj = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
    ii, jj = ii.ravel(), jj.ravel()
    cells = shapely.box(x0 + ii * cw, y0 + jj * ch, x0 + (ii + 1) * cw, y0 + (jj + 1) * ch)
    clipped = shapely.intersection(cells, b)
    full = shapely.area(clipped) / (cw * ch)
    centres = shapely.points(x0 + (ii + 0.5) * cw, y0 + (jj + 0.5) * ch)
    front = shapely.distance(centres, b.boundary) < 0.8 * min(cw, ch)
    chance = np.where(front, config.FRONT_HOUSE_CHANCE, config.BACK_HOUSE_CHANCE)
    built = (full > 0.55) & (rng.random(len(cells)) < chance)
    solid = set()  # plots of a court: no party walls inside it
    plan = _fit_court((full > 0.8).reshape(nx, ny)) if court else None
    if plan is not None:
        i0, j0, cb = plan
        inside = (ii >= i0) & (ii < i0 + cb.shape[0]) & (jj >= j0) & (jj < j0 + cb.shape[1])
        built[inside] = cb[ii[inside] - i0, jj[inside] - j0]
        solid = {(i, j) for i, j in zip(ii[inside], jj[inside])}

    houses, at = [], set()
    for k in np.nonzero(built)[0]:
        p = _largest(clipped[k])
        if p is None:
            continue
        houses.append([tuple(v) for v in _rot(np.asarray(p.exterior.coords), theta)])
        at.add((ii[k], jj[k]))
    walls = []
    for i, j in at:
        for di, dj in ((1, 0), (0, 1)):
            if (i + di, j + dj) in at and (i, j) not in solid and (i + di, j + dj) not in solid \
                    and rng.random() < config.PARTY_WALL_CHANCE:
                ex, ey = x0 + (i + di) * cw, y0 + (j + dj) * ch
                seg = [(ex, y0 + j * ch), (ex, y0 + (j + 1) * ch)] if di else \
                      [(x0 + i * cw, ey), (x0 + (i + 1) * cw, ey)]
                walls.append([tuple(v) for v in _rot(np.asarray(seg), theta)])
    return houses, walls, plan is not None


def draw(layers: dict, houses, walls, lw: float):
    hd, wd = ImageDraw.Draw(layers["houses"]), ImageDraw.Draw(layers["walls"])
    for h in houses:
        hd.polygon(h, fill=255)
    for w in walls:
        wd.line(w, fill=200, width=max(1, round(lw)))


def _hatch_rows(y0, y1, w, period, ink, angle):
    """Anti-aliased parallel rules covering `ink` of each period, for rows y0..y1."""
    yy, xx = np.mgrid[y0:y1, 0:w].astype(np.float32)
    r = math.radians(angle)
    d = (xx * math.cos(r) + yy * math.sin(r)) % period
    return np.clip(ink * period / 2 - np.abs(d - period / 2) + 0.5, 0, 1)


def finish(cv, layers: dict) -> None:
    """Hatch every house, outline each terrace and add party walls, into the ink layer."""
    ss = cv.ss
    h = np.asarray(layers["houses"], np.uint8)
    k = np.ones((max(2, round(ss * 1.5)),) * 2, np.uint8)
    edge = cv2.subtract(h, cv2.erode(h, k))
    walls = np.minimum(np.asarray(layers["walls"], np.uint8), h)
    ink = np.array(layers["ink"], np.uint8)
    pitch = cv.layout.dpi * ss * config.HATCH_PITCH
    rows = np.nonzero(h.any(axis=1))[0]
    if len(rows):
        for y0 in range(rows[0], rows[-1] + 1, 1024):
            y1 = min(y0 + 1024, h.shape[0])
            hatch = _hatch_rows(y0, y1, h.shape[1], pitch, config.HATCH_INK, 45)
            band = np.maximum(h[y0:y1] / 255 * hatch * 255, np.maximum(edge[y0:y1], walls[y0:y1]))
            ink[y0:y1] = np.maximum(ink[y0:y1], band.astype(np.uint8))
    layers["ink"] = Image.fromarray(ink)
