"""Hand-plotted fallback geography, used when no OpenStreetMap extract is cached.

This is a SCHEMATIC: the Old Town grid is generated from its real street order,
spacing and ~9 degree skew, and the shoreline and arterials are plotted from known
landmarks, but positions are good to tens of metres at best and Rosemont's local
streets are placeholders. Run `make fetch` for the accurate OSM-based map.
Used only when config.yaml says `offline_fallback: alexandria`.
Only street names whose order is well established are labelled here.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString
from shapely.ops import unary_union

from . import config
from .geo import FRAME, GeoModel, line, poly, proj
from .osm import config_labels

N, S, W, E = config.NORTH, config.SOUTH, config.WEST, config.EAST

# West-bank land, traced north to south along the Potomac, round Jones Point, up
# Hunting Creek to the mouth of Cameron Run, then back along the Belle Haven shore.
WEST_SHORE = [
    (N, W), (N, -77.0442), (38.8448, -77.0447), (38.8436, -77.0452),
    (38.8418, -77.0450), (38.8395, -77.0428), (38.8370, -77.0410), (38.8350, -77.0395),
    (38.8330, -77.0383), (38.8300, -77.0375), (38.8265, -77.0377), (38.8235, -77.0390),
    (38.8200, -77.0398), (38.8165, -77.0394), (38.8130, -77.0391), (38.8100, -77.0388),
    (38.8060, -77.0386), (38.8030, -77.0389), (38.7990, -77.0393), (38.7950, -77.0396),
    (38.7915, -77.0399), (38.7898, -77.0405), (38.7893, -77.0418), (38.7900, -77.0440),
    (38.7915, -77.0465), (38.7928, -77.0500), (38.7938, -77.0545), (38.7950, -77.0590),
    (38.7957, -77.0630), (38.7952, -77.0662), (38.7936, -77.0668), (38.7920, -77.0642),
    (38.7902, -77.0612), (38.7884, -77.0580), (S, -77.0574), (S, W),
]
# Maryland / District shore across the river.
EAST_SHORE = [
    (N, E), (N, -77.0212), (38.8400, -77.0208), (38.8320, -77.0215), (38.8240, -77.0225),
    (38.8170, -77.0220), (38.8100, -77.0205), (38.8030, -77.0195), (38.7960, -77.0200),
    (S, -77.0210), (S, E),
]

ARTERIALS = {
    # name: (class, [(lat, lon), ...])
    "King St": ("major", [(38.8063, -77.0550), (38.8066, -77.0600), (38.8070, -77.0640),
                          (38.8085, -77.0680), (38.8105, -77.0720), (38.8135, -77.0770),
                          (38.8165, -77.0820), (38.8195, -77.0880), (38.8222, W)]),
    "Duke St": ("major", [(38.8041, -77.0552), (38.8045, -77.0600), (38.8040, -77.0660),
                          (38.8045, -77.0720), (38.8055, -77.0800), (38.8065, W)]),
    "Geo. Washington Pkwy": ("major", [(38.8170, -77.0447), (38.8220, -77.0440), (38.8270, -77.0425),
                                       (38.8320, -77.0420), (38.8370, -77.0440), (38.8420, -77.0465),
                                       (N, -77.0478)]),
    "Richmond Hwy": ("major", [(38.8174, -77.0490), (38.8210, -77.0510), (38.8260, -77.0518),
                               (38.8300, -77.0518), (38.8360, -77.0515), (38.8410, -77.0520),
                               (N, -77.0525)]),
    "Mount Vernon Ave": ("major", [(38.8175, -77.0598), (38.8205, -77.0592), (38.8352, -77.0590),
                                   (38.8380, -77.0592), (38.8420, -77.0610), (N, -77.0640)]),
    "Commonwealth Ave": ("major", [(38.8080, -77.0618), (38.8130, -77.0622), (38.8180, -77.0624),
                                   (38.8352, -77.0624), (38.8385, -77.0620)]),
    "Braddock Rd": ("major", [(38.8230, W), (38.8200, -77.0800), (38.8185, -77.0700),
                              (38.8180, -77.0650), (38.8175, -77.0610), (38.8160, -77.0560),
                              (38.8150, -77.0520), (38.8158, -77.0490)]),
    "Russell Rd": ("minor", [(38.8090, -77.0685), (38.8130, -77.0675), (38.8180, -77.0665),
                             (38.8230, -77.0655), (38.8280, -77.0650), (38.8330, -77.0645),
                             (38.8380, -77.0640), (38.8420, -77.0640)]),
    "Glebe Rd": ("major", [(38.8395, -77.0518), (38.8390, -77.0560), (38.8385, -77.0600),
                           (38.8390, -77.0650), (38.8410, -77.0700), (38.8440, -77.0760)]),
    "Slaters Ln": ("minor", [(38.8228, -77.0442), (38.8233, -77.0515)]),
    "Eisenhower Ave": ("minor", [(38.8013, -77.0610), (38.8020, -77.0700), (38.8025, -77.0800),
                                 (38.8030, W)]),
}

RAIL = [(38.7920, -77.0655), (38.8000, -77.0625), (38.8063, -77.0614), (38.8100, -77.0590),
        (38.8125, -77.0560), (38.8142, -77.0533), (38.8190, -77.0505), (38.8250, -77.0490),
        (38.8330, -77.0485), (38.8400, -77.0490), (N, -77.0495)]

STREAMS = {
    "Four Mile Run": [(38.8425, -77.0452), (38.8428, -77.0490), (38.8430, -77.0530),
                      (38.8432, -77.0570), (38.8440, -77.0620), (38.8452, -77.0680), (N, -77.0720)],
    "Cameron Run": [(38.7950, -77.0664), (38.7965, -77.0700), (38.7985, -77.0740),
                    (38.8005, -77.0790), (38.8010, -77.0850), (38.8020, W)],
    "Timber Branch": [(38.8160, -77.0700), (38.8200, -77.0660), (38.8250, -77.0640)],
}

# Old Town: streets in their real order. N-S streets run on a bearing of ~9 degrees;
# indices are relative to Washington St (u) and King St (v).
OT_ORIGIN = (38.8048, -77.0469)  # King & Washington
OT_BEARING = 9.0
OT_DU, OT_DV = 100.0, 112.0  # metres between N-S streets, between E-W streets
OT_NS = ["West", "Payne", "Fayette", "Henry", "Patrick", "Alfred", "Columbus",
         "Washington", "St. Asaph", "Pitt", "Royal", "Fairfax", "Lee", "Union"]  # u = -7..6
OT_EW = {-7: "Jefferson", -6: "Franklin", -5: "Gibbon", -4: "Wilkes", -3: "Wolfe",
         -2: "Duke", -1: "Prince", 0: "King", 1: "Cameron", 2: "Queen", 3: "Princess",
         4: "Oronoco", 5: "Pendleton", 6: "Wythe", 7: "Madison", 8: "Montgomery"}
OT_V = (-12, 12)

# Del Ray: avenues south to north and cross streets west to east (schematic spacing).
DR_AVES = ["E. Monroe", "Bellefonte", "Howell", "Windsor", "Custis", "Del Ray", "Oxford",
           "Uhler", "Mt. Ida", "Stewart", "Randolph", "Raymond", "Hume"]
DR_LAT = (38.8205, 38.8352)
DR_LON = (-77.0624, -77.0520)
DR_COLS = 9


def _ot_point(u: float, v: float) -> tuple[float, float]:
    """Old Town grid (u east-ish, v north-ish, in street indices) -> local metres."""
    ox, oy = proj(*OT_ORIGIN)
    b = math.radians(OT_BEARING)
    du, dv = u * OT_DU, v * OT_DV
    return (ox + du * math.cos(b) + dv * math.sin(b), oy - du * math.sin(b) + dv * math.cos(b))


def build() -> GeoModel:
    m = GeoModel(source="hand-plotted schematic (run `make fetch` for OpenStreetMap)")
    land = unary_union([poly(WEST_SHORE), poly(EAST_SHORE)])
    m.water = FRAME.difference(land)

    for name, (cls, pts) in ARTERIALS.items():
        m.roads.append((line(pts), cls, name))

    for i, name in enumerate(OT_NS):
        u = i - 7
        cls = "major" if name in ("Washington", "Patrick", "Henry") else "minor"
        m.roads.append((LineString([_ot_point(u, OT_V[0]), _ot_point(u, OT_V[1])]), cls, f"{name} St"))
    for v in range(OT_V[0], OT_V[1] + 1):
        name = OT_EW.get(v, "")
        cls = "major" if name in ("King", "Duke") else "minor"
        m.roads.append((LineString([_ot_point(-7, v), _ot_point(6.6, v)]), cls, f"{name} St" if name else ""))

    for i, name in enumerate(DR_AVES):
        lat = DR_LAT[0] + (DR_LAT[1] - DR_LAT[0]) * i / (len(DR_AVES) - 1)
        m.roads.append((line([(lat, DR_LON[0]), (lat, DR_LON[1])]), "minor", f"{name} Ave"))
    for j in range(DR_COLS):
        lon = DR_LON[0] + (DR_LON[1] - DR_LON[0]) * j / (DR_COLS - 1)
        if j in (0, 2, DR_COLS - 1):
            continue  # Commonwealth, Mount Vernon and Route 1 are arterials
        m.roads.append((line([(DR_LAT[0], lon), (DR_LAT[1], lon)]), "minor", ""))

    # Rosemont: placeholder lanes between Russell Rd and Commonwealth Ave.
    for lat in (38.8100, 38.8117, 38.8134, 38.8151, 38.8168):
        m.roads.append((line([(lat, -77.0676), (lat, -77.0622)]), "minor", ""))
    for lon in (-77.0658, -77.0640):
        m.roads.append((line([(38.8092, lon), (38.8172, lon)]), "minor", ""))

    m.rail.append(line(RAIL))
    for name, pts in STREAMS.items():
        m.streams.append((line(pts), name))

    m.parks = [
        poly([(38.7896, -77.0412), (38.7935, -77.0400), (38.7940, -77.0440), (38.7920, -77.0470),
              (38.7903, -77.0445)]),  # Jones Point
        poly([(38.8270, -77.0383), (38.8340, -77.0388), (38.8360, -77.0405), (38.8300, -77.0410),
              (38.8262, -77.0398)]),  # Daingerfield Island
        poly([(38.8405, -77.0570), (38.8425, -77.0570), (38.8428, -77.0480), (38.8410, -77.0480)]),  # Four Mile Run Park
        poly([(38.8064, -77.0680), (38.8090, -77.0675), (38.8092, -77.0645), (38.8066, -77.0642)]),  # Shooter's Hill
    ]
    # Open country west of Russell Rd and south of King St, drawn as fields and woods.
    m.fields = [
        poly([(38.8250, W), (38.8440, -77.0760), (38.8420, -77.0660), (38.8230, -77.0668),
              (38.8195, -77.0695), (38.8170, -77.0780)]),
        poly([(38.8040, -77.0800), (38.8110, -77.0740), (38.8085, -77.0690), (38.8040, -77.0690)]),
        poly([(38.8035, W), (38.8048, -77.0820), (38.8100, -77.0820), (38.8170, -77.0860),
              (38.8210, W)]),
    ]
    m.hills = [(*proj(38.8076, -77.0661), 260), (*proj(38.8210, -77.0790), 380),
               (*proj(38.8120, -77.0860), 300)]
    m.landmarks = [
        (*proj(38.8076, -77.0661), "temple", "Masonic Memorial"),
        (*proj(38.8058, -77.0467), "church", "Christ Church"),
        (*proj(38.8052, -77.0430), "market", "Market Sq."),
        (*proj(38.7903, -77.0410), "lighthouse", "Jones Point Light"),
        (*proj(38.8160, -77.0700), "church", ""),
    ]
    m.labels = config_labels() or []
    return m
