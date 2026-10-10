"""Tunables for the Wi-Fi QR map. Location comes from config.yaml; physical tunables live here."""

from dataclasses import dataclass
import math
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
DATA = ROOT / "data"
MILE = 1609.344


@dataclass(frozen=True)
class Layout:
    """Sheet layout in output pixels: `width_in` x `height_in` at `dpi`. The design is 12 in
    on its short side; a longer sheet gets more map along its long side."""

    dpi: int = 300
    width_in: float = 12.0
    height_in: float = 12.0
    # Border bands (inches): title on top, scale and attribution below.
    top: float = 1.10
    bottom: float = 0.78
    side: float = 0.94

    @property
    def width(self) -> int:
        return round(self.width_in * self.dpi)

    @property
    def height(self) -> int:
        return round(self.height_in * self.dpi)

    def px(self, inches: float) -> int:
        return round(inches * self.dpi)

    @property
    def map_box(self) -> tuple[int, int, int, int]:
        """Map area (x0, y0, x1, y1) inside the graduated border."""
        return (self.px(self.side), self.px(self.top),
                self.width - self.px(self.side), self.height - self.px(self.bottom))


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


def parse_size(v) -> tuple[float, float]:
    """'16x20' (or [16, 20], or 12) -> (width, height) in inches."""
    try:
        parts = [float(x) for x in (v if isinstance(v, (list, tuple)) else re.split(r"[x×*, ]+", str(v).strip().lower()))]
        w, h = (parts * 2)[:2] if len(parts) == 1 else parts
        assert len(parts) <= 2 and w > 0 and h > 0
    except (ValueError, AssertionError):
        raise SystemExit(f"bad print size {v!r}: use WIDTHxHEIGHT in inches, e.g. 16x20")
    return w, h


def _latlon(v, default):
    return default if v is None else (float(v[0]), float(v[1]))


CFG = _load(CONFIG_FILE)

# Print size: the sheet the file is made for, with a blank border all round (for a canvas
# wrap or a mat). The map fills the sheet inside the border, drawn at the design scale
# for its short side (12 in) and scaled up with it, so a longer sheet shows more ground
# along its long side. `--size` and `--border` on the command line (also `make fetch`)
# override config.yaml; they are read here, as the map's extent fixes the OSM query.
def _flag(name: str):
    for i, arg in enumerate(sys.argv):
        if arg == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return None


_PRINT = CFG.get("print") or {}
PRINT_SIZE = parse_size(_flag("--size") or _PRINT.get("size", "12x12"))
PRINT_BORDER = float(_flag("--border") or _PRINT.get("border", 0))
_ART_IN = (PRINT_SIZE[0] - 2 * PRINT_BORDER, PRINT_SIZE[1] - 2 * PRINT_BORDER)
if min(_ART_IN) < 4:
    raise SystemExit(f"{PRINT_SIZE[0]:g} x {PRINT_SIZE[1]:g} in with a {PRINT_BORDER:g} in border "
                     f"leaves too little room for the map")
SCALE = min(_ART_IN) / 12.0  # print inches per design inch
DESIGN = Layout(width_in=_ART_IN[0] / SCALE, height_in=_ART_IN[1] / SCALE)  # the map's sheet, in design inches
NAME = str(CFG.get("name") or "the Map")
CENTER = _latlon(CFG["center"], None)

# The scale is fixed: one house plot on the ground is one QR module on paper, so the
# ward's houses are the same size as every other house on the map.
MODULE_INCHES = 0.05  # printed module (and house plot) size; 0.05 in = 15 px at 300 dpi
PLOT_METRES = 16.0  # ground frontage of one house plot
_mx0, _my0, _mx1, _my1 = DESIGN.map_box
_MAP_IN = ((_mx1 - _mx0) / DESIGN.dpi, (_my1 - _my0) / DESIGN.dpi)  # the map, in design inches
_HALF_W_M, _HALF_H_M = (v / MODULE_INCHES * PLOT_METRES / 2 for v in _MAP_IN)
RADIUS_MILES = max(_HALF_W_M, _HALF_H_M) / MILE  # ~1 mile on a square sheet

# The map covers 2 x _HALF_W_M by 2 x _HALF_H_M on the ground, centred on CENTER.
_HALF_H_DEG = _HALF_H_M / 110_540
_HALF_W_DEG = _HALF_W_M / (111_320 * math.cos(math.radians(CENTER[0])))
SOUTH, NORTH = CENTER[0] - _HALF_H_DEG, CENTER[0] + _HALF_H_DEG
WEST, EAST = CENTER[1] - _HALF_W_DEG, CENTER[1] + _HALF_W_DEG
BBOX = (SOUTH, WEST, NORTH, EAST)  # Overpass order

# Stroke widths, symbol sizes and the like were tuned in metres for a 2-mile radius and
# are scaled to print the same size at the fixed scale.
_ref = Layout().map_box
STYLE = (_ref[2] - _ref[0]) / Layout().dpi / MODULE_INCHES * PLOT_METRES / 2 / MILE / 2.0  # ~0.5 on the 12 in design

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
LEGEND_TEXT_INCHES = 0.13  # label size; values print slightly smaller in Caslon
# Lettered references above the Wi-Fi rows, keyed to letters on the map, as on an
# engraved plan: `auto` picks real named buildings from OSM; a list of
# {at: [lat, lon], text: ...} names your own; [] leaves them out.
_refs = CFG.get("references", "auto")
REFERENCES = None if _refs in (None, "auto") else \
    [(float(r["at"][0]), float(r["at"][1]), str(r["text"])) for r in (_refs or [])]
REFERENCE_COUNT = 6
REFERENCE_MAX_CHARS = 26  # longer names would make the cartouche too wide
