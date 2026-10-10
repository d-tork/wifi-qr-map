"""Where the hidden QR ward sits on the sheet, and the module <-> pixel transform.

Shared by the renderer (to draw blocks), the guard pass and the validator (to sample
module centres), so all three agree to the pixel.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from . import config
from .geo import WIDTH_M, proj


@dataclass
class District:
    cx: float  # centre of the symbol, output pixels
    cy: float
    module: int  # module size, output pixels
    n: int  # modules per side, excluding quiet zone
    quiet: int  # quiet-zone width in modules
    angle: float  # degrees, counter-clockwise on the page

    @property
    def side(self) -> int:
        return self.n * self.module

    def to_px(self, u: float, v: float, scale: float = 1.0) -> tuple[float, float]:
        """Symbol coordinates in modules (u = column, v = row, origin at the top-left
        corner of the symbol) -> sheet pixels (times `scale`, for supersampled canvases)."""
        a = math.radians(self.angle)
        dx, dy = (u - self.n / 2) * self.module, (v - self.n / 2) * self.module
        x = self.cx + dx * math.cos(a) + dy * math.sin(a)
        y = self.cy - dx * math.sin(a) + dy * math.cos(a)
        return x * scale, y * scale

    def center(self, r: int, c: int) -> tuple[float, float]:
        return self.to_px(c + 0.5, r + 0.5)

    def square(self, u0, v0, u1, v1, scale=1.0):
        return [self.to_px(u, v, scale) for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))]

    def reserve(self, scale=1.0, extra=0.0):
        """Outer edge of the quiet zone (+ `extra` modules)."""
        q = self.quiet + extra
        return self.square(-q, -q, self.n + q, self.n + q, scale)

    def bbox(self, scale=1.0, extra=0.0):
        pts = self.reserve(scale, extra)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def to_dict(self):
        return asdict(self)


def place(layout: config.Layout, n: int, center=None, angle=None, module_in=None, quiet=None) -> District:
    lat, lon = center or config.DISTRICT_CENTER
    angle = config.DISTRICT_ANGLE if angle is None else angle
    m = max(4, round((module_in or config.MODULE_INCHES) * layout.dpi))
    q = config.QUIET_MODULES if quiet is None else quiet
    x0, y0, x1, y1 = layout.map_box
    k = (x1 - x0) / WIDTH_M
    x, y = proj(lat, lon)
    cx, cy = x0 + x * k, y1 - y * k
    half = (n + 2 * q) * m / 2 * (abs(math.cos(math.radians(angle))) + abs(math.sin(math.radians(angle))))
    cx = min(max(cx, x0 + half), x1 - half)  # keep the whole ward on the map
    cy = min(max(cy, y0 + half), y1 - half)
    if angle == 0:  # align module edges to whole pixels for crisp edges
        cx = round(cx - n * m / 2) + n * m / 2
        cy = round(cy - n * m / 2) + n * m / 2
    return District(cx, cy, m, n, q, angle)
