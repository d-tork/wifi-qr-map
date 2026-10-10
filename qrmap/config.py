"""Tunables for the Wi-Fi QR map. Location comes from config.yaml; physical tunables live here."""

from dataclasses import dataclass
import math
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
DATA = ROOT / "data"
MILE = 1609.344

# --- Location, from config.yaml (or $QRMAP_CONFIG) ---------------------------------
CONFIG_FILE = Path(os.environ.get("QRMAP_CONFIG") or ROOT / "config.yaml")


def _load(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Config file not found: {path}")
    cfg = yaml.safe_load(path.read_text()) or {}
    try:
        lat, lon = (float(v) for v in cfg["center"])
        r = float(cfg["radius_miles"])
    except (KeyError, TypeError, ValueError):
        raise SystemExit(f"{path}: needs `center: [lat, lon]` and `radius_miles: <number>`")
    if not (-80 <= lat <= 80 and -180 <= lon <= 180):
        raise SystemExit(f"{path}: center {lat}, {lon} is out of range (|lat| <= 80)")
    if not 0.1 <= r <= 25:
        raise SystemExit(f"{path}: radius_miles must be between 0.1 and 25")
    return cfg


def _latlon(v, default):
    return default if v is None else (float(v[0]), float(v[1]))


CFG = _load(CONFIG_FILE)
NAME = str(CFG.get("name") or "the Map")
CENTER = _latlon(CFG["center"], None)
RADIUS_MILES = float(CFG["radius_miles"])

# The map is a square 2r on a side on the ground, so it is not stretched on a square sheet.
_HALF_M = RADIUS_MILES * MILE
_HALF_H_DEG = _HALF_M / 110_540
_HALF_W_DEG = _HALF_M / (111_320 * math.cos(math.radians(CENTER[0])))
SOUTH, NORTH = CENTER[0] - _HALF_H_DEG, CENTER[0] + _HALF_H_DEG
WEST, EAST = CENTER[1] - _HALF_W_DEG, CENTER[1] + _HALF_W_DEG
BBOX = (SOUTH, WEST, NORTH, EAST)  # Overpass order

# Stroke widths, symbol sizes and the like are tuned in metres for a 2-mile radius. They
# scale with the map so they print the same size at any radius.
STYLE = RADIUS_MILES / 2.0

TITLE = CFG.get("title") or f"A  PLAN  of  {NAME.upper()}"
SUBTITLE = CFG.get("subtitle") or ""
_minor = CFG.get("minor_roads")
MINOR_ROADS = RADIUS_MILES <= 3 if _minor is None else bool(_minor)
LANDMARKS = dict(CFG.get("landmarks") or {})  # OSM name -> temple|church|market|lighthouse
HILLS = [(float(a), float(b), float(c)) for a, b, c in CFG.get("hills") or []]
LABELS = CFG.get("labels")  # None -> label places from OSM
OFFLINE_FALLBACK = CFG.get("offline_fallback")


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
_WARD = CFG.get("ward") or {}
DISTRICT_CENTER = _latlon(_WARD.get("center"), CENTER)
DISTRICT_ANGLE = float(_WARD.get("angle") or 0.0)  # degrees counter-clockwise
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
# Engravers put cartouches in open water; set legend.center in config.yaml to do the same.
LEGEND_CENTER = _latlon((CFG.get("legend") or {}).get("center"), (SOUTH, WEST))
LEGEND_TITLE = "REFERENCES"
LEGEND_NETWORK_LABEL = "Network"
LEGEND_PASSWORD_LABEL = "Password"
LEGEND_TEXT_INCHES = 0.13  # label size; values print slightly smaller in Caslon
