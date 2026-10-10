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

    @property
    def size(self) -> int:
        return round(self.inches * self.dpi)

    def px(self, inches: float) -> int:
        return round(inches * self.dpi)

    @property
    def map_box(self) -> tuple[int, int, int, int]:
        """Square map area (x0, y0, x1, y1) inside the graduated border."""
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

# --- The hidden QR: a fabricated ward of small house blocks -------------------------
# Each dark module is a hatched block, each light module a lane or yard. The ward sits
# at DISTRICT_CENTER, turned DISTRICT_ANGLE degrees to match the street grid around it,
# inside a ring of open ground (the quiet zone) where the real streets stop.
DISTRICT_CENTER = (38.8276, -77.0572)  # Del Ray, the former Town of Potomac
DISTRICT_ANGLE = 0.0  # degrees counter-clockwise; Old Town's grid is about -9
MODULE_INCHES = 0.05  # printed module size; 0.05 in = 15 px at 300 dpi
QUIET_MODULES = 3  # open ground around the symbol, in modules (ISO asks 4; 3 tests fine)
ECC = "q"  # l/m/q/h. Clean rendering needs no art-damage budget; Q keeps modules large.
HATCH_PITCH = 0.0125  # inches between engraved rules in the ward's blocks
HATCH_INK = 0.55  # ink fraction of each pitch
STREET_FRACTION = 0.16  # street width between built blocks, as a fraction of a module
STREET_CHANCE = 0.7  # chance two neighbouring built blocks are split by a street
LOT_INK = 80  # ink (0-255) of the faint outlines round open lots

# Module centres (the central CORE_FRACTION, where decoders sample) are corrected only
# if the finished art leaves them short of these mean CIE L* values.
CORE_FRACTION = 0.36
CORE_LIGHT = 80.0
CORE_DARK = 44.0

# --- Legend cartouche (fallback for devices that cannot scan) ---------------------
LEGEND_CENTER = (38.8395, -77.0300)  # in the river, where engravers put cartouches
LEGEND_TITLE = "REFERENCES"
LEGEND_NETWORK_LABEL = "Network"
LEGEND_PASSWORD_LABEL = "Password"
LEGEND_TEXT_INCHES = 0.13  # label size; values print slightly smaller in Caslon
