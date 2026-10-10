"""Tunables for the Wi-Fi QR map. Everything physical lives here."""

from dataclasses import dataclass
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
DATA = ROOT / "data"

# Geographic extent: Old Town (south/east), Rosemont (west), Del Ray / the former
# Town of Potomac (north), with the Potomac on the east and Hunting Creek on the
# south. Chosen to be square on the ground at this latitude so the map is not
# stretched on a square sheet.
SOUTH, NORTH = 38.7880, 38.8460
_LON_C = -77.0560
_HALF_W_DEG = ((NORTH - SOUTH) * 110_540 / 2) / (111_320 * math.cos(math.radians((SOUTH + NORTH) / 2)))
WEST, EAST = _LON_C - _HALF_W_DEG, _LON_C + _HALF_W_DEG
BBOX = (SOUTH, WEST, NORTH, EAST)  # Overpass order


@dataclass(frozen=True)
class Layout:
    """Sheet layout in output pixels. 12 in x 12 in at `dpi`."""

    dpi: int = 300
    inches: float = 12.0
    # Border bands (inches): title on top, scale and attribution below.
    top: float = 1.10
    bottom: float = 0.78
    side: float = 0.94
    quiet_zone: int = 4  # modules of light margin around the symbol (ISO 18004 minimum)

    @property
    def size(self) -> int:
        return round(self.inches * self.dpi)

    def px(self, inches: float) -> int:
        return round(inches * self.dpi)

    @property
    def map_box(self) -> tuple[int, int, int, int]:
        """Square map area (x0, y0, x1, y1). The QR symbol + quiet zone fills it."""
        s = self.size
        x0, y0 = self.px(self.side), self.px(self.top)
        side = min(s - 2 * x0, s - y0 - self.px(self.bottom))
        return x0, y0, x0 + side, y0 + side


# Palette (sRGB). Ink is a warm iron-gall black; washes imitate hand colouring.
PARCHMENT = (240, 228, 200)
INK = (43, 30, 20)
WATER_WASH = (150, 185, 180)
BLOCK_WASH = (214, 140, 130)
PARK_WASH = (170, 186, 128)
FIELD_WASH = (222, 205, 150)

# Tone targets in CIE L* (0 black .. 100 white) used by the QR compositor.
# Light modules: the map remapped into [LIGHT_FLOOR, 100].
# Dark modules: engraved rules of DARK_INK over gaps of [DARK_GAP_MIN, DARK_GAP_MAX].
LIGHT_FLOOR = 52.0
DARK_INK = 14.0
DARK_GAP_MIN, DARK_GAP_MAX = 36.0, 68.0
HATCH_PITCH = 0.021  # inches between engraved rules (~48 lines per inch)
HATCH_INK = 0.52  # fraction of each pitch that is ink
LIGHT_CHROMA = 0.85  # colour saturation multipliers
DARK_CHROMA = 1.25
# Module centres (the central CORE_FRACTION of each module, where decoders sample)
# are pulled to at least this mean lightness (light) or at most this one (dark).
CORE_FRACTION = 0.36
CORE_LIGHT = 80.0
CORE_DARK = 36.0
SOFTEN = 0.24  # blur sigma (in modules) that rounds dark modules into "parcels"
OUTLINE_PX = 2.2  # width of the ink rule round each parcel, roughly in pixels
INK_HUE = 0.75  # how far dark parcels on open ground take the ink's hue (0..1)
