"""QR-guided engraving: the matrix decides lightness, the map decides everything else.

Light modules show the map, lifted into a light tone band. Dark modules are cut as
dense engraved hatching whose direction follows the map feature underneath
(horizontal water-ruling on the river, 45-degree hatching on town blocks,
cross-hatching on open ground), keeping the map's hue. Seen up close it is shading
on an old plan; to a camera, whose pixels average the hatching, it is a dark module.

Adjacent dark data modules are blurred together into rounded "parcels". Finder,
timing and alignment patterns stay crisp. Finally, each module's centre -- where
decoders sample -- is nudged only as far as needed to meet a minimum contrast, so
the correction is invisible wherever the art already agrees with the code.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from . import config
from .qr import Code


@dataclass
class Geometry:
    """Where the symbol sits on the sheet, in output pixels."""

    x0: int  # top-left of module (0, 0), i.e. just inside the quiet zone
    y0: int
    module: int  # module size in pixels
    n: int  # modules per side, without quiet zone
    quiet: int  # quiet zone in modules

    @property
    def side(self) -> int:
        return self.n * self.module

    def to_dict(self):
        return dict(x0=self.x0, y0=self.y0, module=self.module, n=self.n, quiet=self.quiet)


def geometry(layout: config.Layout, n: int) -> Geometry:
    x0, y0, x1, _ = layout.map_box
    total = n + 2 * layout.quiet_zone
    m = (x1 - x0) // total
    pad = ((x1 - x0) - total * m) // 2
    q = layout.quiet_zone
    return Geometry(x0 + pad + q * m, y0 + pad + q * m, m, n, q)


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def _up(a: np.ndarray, m: int) -> np.ndarray:
    return np.kron(a.astype(np.float32), np.ones((m, m), np.float32))


def _fields(code: Code, g: Geometry):
    """(T, outline): crisp anti-aliased parcel shapes and an ink rule along their edge."""
    m = g.module
    crisp = _up(code.dark, m)
    blur = cv2.GaussianBlur(crisp, (0, 0), config.SOFTEN * m)
    edge = max(0.02, 0.9 / (m * 0.35))  # ~1px anti-aliasing at the blur's slope
    soft = _smoothstep(0.5 - edge, 0.5 + edge, blur)
    func = _up(code.function, m) > 0.5
    # Distance to the 0.5 contour ~ |blur - 0.5| / |grad|; a constant-width rule even at
    # saddle points where diagonal modules touch.
    grad = np.hypot(cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3)) / 8
    dist = np.abs(blur - 0.5) / np.maximum(grad, 1e-4)
    outline = np.clip(config.OUTLINE_PX / 2 + 0.5 - dist, 0, 1) * (grad > 0.004)
    outline[func] = 0
    return np.where(func, crisp, soft), outline


def _lines(shape, period, width, angle_deg, offset=0.0) -> np.ndarray:
    """Anti-aliased parallel rules, coverage 0..1."""
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32)
    a = np.radians(angle_deg)
    d = (xx * np.cos(a) + yy * np.sin(a) + offset) % period
    dist = np.abs(d - period / 2)
    return np.clip(width / 2 - dist + 0.5, 0, 1)


def engraving(shape, dpi, water, blocks) -> np.ndarray:
    """Ink coverage of the dark-module engraving, chosen per map feature."""
    p = dpi * config.HATCH_PITCH
    w = p * config.HATCH_INK
    horiz = _lines(shape, p, w, 90)
    diag = _lines(shape, p, w, 45)
    cw = p * (1 - np.sqrt(1 - config.HATCH_INK))  # two passes, same total coverage
    cross = 1 - (1 - _lines(shape, p, cw, 45)) * (1 - _lines(shape, p, cw, -45))
    out = cross
    out = np.where(blocks > 0.5, diag, out)
    out = np.where(water > 0.5, horiz, out)
    return out


def _module_means(L: np.ndarray, g: Geometry, frac: float) -> np.ndarray:
    m = g.module
    c = max(1, int(round(m * frac)))
    a = (m - c) // 2
    v = L.reshape(g.n, m, g.n, m)[:, a:a + c, :, a:a + c]
    return v.mean(axis=(1, 3))


def compose(art: dict, code: Code, layout: config.Layout):
    """Returns (final rgb float 0..1, geometry, darkness target over the whole sheet)."""
    rgb = art["rgb"]
    g = geometry(layout, code.n)
    lab = cv2.cvtColor(rgb.astype(np.float32), cv2.COLOR_RGB2Lab)

    # Whole map box (quiet zone + symbol) gets the light-module treatment first.
    mx0, my0, mx1, my1 = layout.map_box
    qz = lab[my0:my1, mx0:mx1]
    qz[..., 0] = config.LIGHT_FLOOR + (100 - config.LIGHT_FLOOR) * qz[..., 0] / 100
    qz[..., 1:] *= config.LIGHT_CHROMA

    sl = (slice(g.y0, g.y0 + g.side), slice(g.x0, g.x0 + g.side))
    l0 = cv2.cvtColor(rgb[sl].astype(np.float32), cv2.COLOR_RGB2Lab)[..., 0] / 100
    T, outline = _fields(code, g)
    light = config.LIGHT_FLOOR + (100 - config.LIGHT_FLOOR) * l0
    cov = engraving(l0.shape, layout.dpi, art["water"][sl], art["blocks"][sl])
    gap = config.DARK_GAP_MIN + (config.DARK_GAP_MAX - config.DARK_GAP_MIN) * l0
    dark = gap * (1 - cov) + config.DARK_INK * cov
    Lq = (1 - T) * light + T * dark
    Lq = Lq * (1 - outline) + config.DARK_INK * outline  # hand-ruled parcel boundary

    # Minimal centre correction: scale each module's core toward the target mean only
    # where the art leaves it short of it.
    m = g.module
    means = _module_means(Lq, g, config.CORE_FRACTION)
    with np.errstate(divide="ignore", invalid="ignore"):
        dark_gain = np.where(code.dark & (means > config.CORE_DARK), config.CORE_DARK / means, 1.0)
        light_gain = np.where(~code.dark & (means < config.CORE_LIGHT),
                              (100 - config.CORE_LIGHT) / np.maximum(100 - means, 1e-3), 1.0)
    w = core_weights(g)
    Ld = Lq * _up(dark_gain, m)
    Ll = 100 - (100 - Lq) * _up(light_gain, m)
    corrected = np.where(_up(code.dark, m) > 0.5, Ld, Ll)
    Lq = Lq + w * (corrected - Lq)

    sym = lab[sl]
    sym[..., 0] = Lq
    # Light modules were already paled with the map box; restore and deepen dark ones.
    sym[..., 1:] *= (1 + (config.DARK_CHROMA / config.LIGHT_CHROMA - 1) * T)[..., None]
    # Pull dark parcels' hue toward the ink so open ground engraves in sepia, not olive.
    ink_ab = cv2.cvtColor(np.array([[config.INK]], np.float32) / 255, cv2.COLOR_RGB2Lab)[0, 0, 1:]
    mix = (config.INK_HUE * T * (1 - np.maximum(art["water"][sl], art["blocks"][sl])))[..., None]
    sym[..., 1:] = sym[..., 1:] * (1 - mix) + ink_ab * 2.2 * mix
    out = np.clip(cv2.cvtColor(lab, cv2.COLOR_Lab2RGB), 0, 1)

    full_T = np.zeros(rgb.shape[:2], np.float32)
    full_T[sl] = T
    _redoubts(out, g)
    return out, g, full_T


def core_weights(g: Geometry) -> np.ndarray:
    """Feathered square at each module centre: 1 in the core, 0 at the module edge."""
    m = g.module
    cell = np.zeros((m, m), np.float32)
    c = config.CORE_FRACTION * m * 1.15
    a, b = int(round((m - c) / 2)), int(round((m + c) / 2))
    cell[a:b, a:b] = 1
    cell = cv2.GaussianBlur(cell, (0, 0), max(0.6, m * 0.06))
    cell = np.clip(cell / max(cell.max(), 1e-6), 0, 1)
    return np.tile(cell, (g.n, g.n))


def _redoubts(img: np.ndarray, g: Geometry):
    """Dress the three finder patterns as square redoubts with corner bastions. The
    bastions only reach into corners that no finder scan line through the pattern's
    centre crosses."""
    ink = (np.array(config.INK, np.float32) / 255).tolist()
    m = g.module
    for r0, c0 in ((0, 0), (0, g.n - 7), (g.n - 7, 0)):
        x0, y0 = g.x0 + c0 * m, g.y0 + r0 * m
        x1, y1 = x0 + 7 * m, y0 + 7 * m
        w = m * 0.6
        mid = g.x0 + g.side / 2, g.y0 + g.side / 2
        for cx, cy, dx, dy in ((x0, y0, -1, -1), (x1, y0, 1, -1), (x0, y1, -1, 1), (x1, y1, 1, 1)):
            # The corner facing the symbol points into a light separator module whose
            # centre must stay clear; the other three point into the quiet zone.
            inward = (cx - mid[0]) * dx < 0 and (cy - mid[1]) * dy < 0
            s = m * (0.25 if inward else 0.6)
            pts = np.array([[cx - dx * w, cy - dy * w], [cx - dx * w, cy], [cx + dx * s, cy + dy * s],
                            [cx, cy - dy * w]], np.int32)
            cv2.fillConvexPoly(img, pts, ink, lineType=cv2.LINE_AA)
