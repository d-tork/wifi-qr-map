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


# --- Location, from config.yaml (or $QRMAP_CONFIG) ---------------------------------
CONFIG_FILE = Path(os.environ.get("QRMAP_CONFIG") or ROOT / "config.yaml")


def _load(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Config file not found: {path}")
    cfg = yaml.safe_load(path.read_text()) or {}
    try:
        lat, lon = (float(v) for v in cfg["center"])
    except (KeyError, TypeError, ValueError):
        raise SystemExit(f"{path}: needs `center: [lat, lon]`")
    if not (-80 <= lat <= 80 and -180 <= lon <= 180):
        raise SystemExit(f"{path}: center {lat}, {lon} is out of range (|lat| <= 80)")
    if "radius_miles" in cfg:
        raise SystemExit(f"{path}: remove `radius_miles`. The scale is fixed so that every house "
                         f"plot is one QR module (the sheet shows about a mile round `center`).")
    return cfg


def _latlon(v, default):
    return default if v is None else (float(v[0]), float(v[1]))


CFG = _load(CONFIG_FILE)
NAME = str(CFG.get("name") or "the Map")
CENTER = _latlon(CFG["center"], None)

# The scale is fixed: one house plot on the ground is one QR module on paper, so the
# ward's houses are the same size as every other house on the map.
MODULE_INCHES = 0.05  # printed module (and house plot) size; 0.05 in = 15 px at 300 dpi
PLOT_METRES = 16.0  # ground frontage of one house plot
_x0, _, _x1, _ = Layout().map_box
RADIUS_MILES = (_x1 - _x0) / Layout().dpi / MODULE_INCHES * PLOT_METRES / 2 / MILE  # ~1 mile

# The map is a square 2r on a side on the ground, so it is not stretched on a square sheet.
_HALF_M = RADIUS_MILES * MILE
_HALF_H_DEG = _HALF_M / 110_540
_HALF_W_DEG = _HALF_M / (111_320 * math.cos(math.radians(CENTER[0])))
SOUTH, NORTH = CENTER[0] - _HALF_H_DEG, CENTER[0] + _HALF_H_DEG
WEST, EAST = CENTER[1] - _HALF_W_DEG, CENTER[1] + _HALF_W_DEG
BBOX = (SOUTH, WEST, NORTH, EAST)  # Overpass order

# Stroke widths, symbol sizes and the like were tuned in metres for a 2-mile radius and
# are scaled to print the same size at the fixed scale.
STYLE = RADIUS_MILES / 2.0

TITLE = CFG.get("title") or f"A  PLAN  of  {NAME.upper()}"
SUBTITLE = CFG.get("subtitle") or ""
MINOR_ROADS = True
LANDMARKS = dict(CFG.get("landmarks") or {})  # OSM name -> temple|church|market|lighthouse
HILLS = [(float(a), float(b), float(c)) for a, b, c in CFG.get("hills") or []]
LABELS = CFG.get("labels")  # None -> label places from OSM
OFFLINE_FALLBACK = CFG.get("offline_fallback")


# Palette (sRGB). Ink is a warm iron-gall black; washes imitate hand colouring.
PARCHMENT = (240, 228, 200)
INK = (43, 30, 20)
WATER_WASH = (150, 185, 180)
BLOCK_WASH = (214, 140, 130)
PARK_WASH = (170, 186, 128)
FIELD_WASH = (222, 205, 150)

# --- Houses: every block on the map is laid out in plots one module wide -----------
# A plot either has a house (carmine wash, hatched, ink outline) or is a yard (a pale
# wash). Plots along a street are mostly built; plots behind them mostly yards.
FRONT_HOUSE_CHANCE = 0.72
BACK_HOUSE_CHANCE = 0.22
PARTY_WALL_CHANCE = 0.55  # chance two neighbouring houses are drawn as separate buildings
COURTS = 6  # large blocks built as courts round a hall, like the ward's finder patterns
HATCH_PITCH = 0.0125  # inches between engraved rules on houses
HATCH_INK = 0.55  # ink fraction of each pitch
YARD_WASH = 0.15  # strength of the block wash on yards; light enough for light modules

# --- The hidden QR: a ward of a few house blocks -----------------------------------
# Dark modules are houses, light modules are empty plots, and the finder patterns are
# courtyard blocks with a hall in the middle. Narrow streets run between the blocks,
# along module edges. The ward sits at DISTRICT_CENTER, turned to the nearest major
# street (or DISTRICT_ANGLE), inside a ring of open ground (the quiet zone).
_WARD = CFG.get("ward") or {}
DISTRICT_CENTER = _latlon(_WARD.get("center"), CENTER)
_angle = _WARD.get("angle", "auto")
DISTRICT_ANGLE = None if str(_angle).lower() == "auto" else float(_angle)  # None: follow the street
QUIET_MODULES = 3  # open ground around the symbol, in modules (ISO asks 4; 3 tests fine)
ECC = "q"  # l/m/q/h. Clean rendering needs no art-damage budget; Q keeps modules large.
WARD_BLOCK = (6, 12)  # target block size in the ward, in modules: across, along the block
WARD_STREET = 0.56  # street width between the ward's blocks, as a fraction of a module
WARD_GARDEN = 1.0  # front gardens round the ward, in modules, then a street round it,
WARD_RING = 0.8  # this wide; the rest of the quiet zone is the neighbours' back yards

# Module centres (the central CORE_FRACTION, where decoders sample) are corrected only
# if the finished art leaves them short of these mean CIE L* values.
CORE_FRACTION = 0.36
CORE_LIGHT = 70.0  # yards carry a pale wash, so light modules sit near 78, not paper white
CORE_DARK = 44.0

# --- Legend cartouche (fallback for devices that cannot scan) ---------------------
# Engravers put cartouches in open water; set legend.center in config.yaml to do the same.
LEGEND_CENTER = _latlon((CFG.get("legend") or {}).get("center"), (SOUTH, WEST))
LEGEND_TITLE = "REFERENCES"
LEGEND_NETWORK_LABEL = "Network"
LEGEND_PASSWORD_LABEL = "Password"
LEGEND_TEXT_INCHES = 0.13  # label size; values print slightly smaller in Caslon
# Lettered references above the Wi-Fi rows, keyed to letters on the map, as on an
# engraved plan: `auto` picks real named buildings from OSM; a list of
# {at: [lat, lon], text: ...} names your own; [] leaves them out.
_refs = CFG.get("references", "auto")
REFERENCES = None if _refs in (None, "auto") else \
    [(float(r["at"][0]), float(r["at"][1]), str(r["text"])) for r in (_refs or [])]
REFERENCE_COUNT = 6
REFERENCE_MAX_CHARS = 26  # longer names would make the cartouche too wide
