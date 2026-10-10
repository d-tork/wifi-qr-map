"""Geographic model shared by the OSM loader and the hand-plotted fallback.

All geometry is in local metres (x east, y north) from the south-west corner of
config.BBOX, using an equirectangular projection, which is exact enough at the scale
of a town plan (a few miles across).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from shapely.geometry import LineString, Polygon, box
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree

from . import config

_LAT_C = (config.SOUTH + config.NORTH) / 2
MX = 111_320 * math.cos(math.radians(_LAT_C))  # metres per degree of longitude
MY = 110_540  # metres per degree of latitude
WIDTH_M = (config.EAST - config.WEST) * MX
HEIGHT_M = (config.NORTH - config.SOUTH) * MY
FRAME = box(0, 0, WIDTH_M, HEIGHT_M)


def proj(lat: float, lon: float) -> tuple[float, float]:
    return (lon - config.WEST) * MX, (lat - config.SOUTH) * MY


def line(pts) -> LineString:
    return LineString([proj(la, lo) for la, lo in pts])


def poly(pts) -> Polygon:
    return Polygon([proj(la, lo) for la, lo in pts])


@dataclass
class Label:
    lat: float
    lon: float
    text: str
    size: float = 1.0  # relative to the base label size
    style: str = "italic"  # italic | caps | sc
    angle: float = 0.0  # degrees counter-clockwise
    tracking: float = 0.0  # extra letter spacing, in em


@dataclass
class GeoModel:
    source: str
    water: object = None  # shapely (Multi)Polygon
    roads: list = field(default_factory=list)  # (LineString, "major"|"minor"|"path", name)
    rail: list = field(default_factory=list)  # LineString
    streams: list = field(default_factory=list)  # (LineString, name)
    parks: list = field(default_factory=list)  # Polygon
    fields: list = field(default_factory=list)  # Polygon (open country, drawn as farmland)
    hills: list = field(default_factory=list)  # (x, y, radius_m)
    landmarks: list = field(default_factory=list)  # (x, y, kind, name)
    labels: list = field(default_factory=list)  # Label

    def blocks(self, min_area=1_500, max_area=160_000):
        """City blocks: faces of the street network, less water and parks, cut back from
        every road by its drawn half-width and ink casing, so houses never sit under a
        road (including dead ends and cul-de-sacs inside a face)."""
        min_area *= config.STYLE ** 2  # too small to print; max_area is a real-world size
        lines = [g for g, cls, _ in self.roads if cls != "path"] + list(self.rail)
        lines.append(FRAME.exterior)
        faces = polygonize(unary_union(lines))
        land = FRAME.difference(self.water) if self.water is not None else FRAME
        if self.parks:
            land = land.difference(unary_union(self.parks))
        # Half the drawn width (render_map: 26 / 13 m at the reference scale) plus casing.
        kerbs = [g.buffer((17 if cls == "major" else 10.5) * config.STYLE, cap_style=2)
                 for g, cls, _ in self.roads if cls != "path"]
        kerbs += [r.buffer(12 * config.STYLE, cap_style=2) for r in self.rail]
        tree = STRtree(kerbs)
        out = []
        for f in faces:
            if not (min_area <= f.area <= max_area):
                continue
            near = tree.query(f)
            f = f.intersection(land)
            if len(near):
                f = f.difference(unary_union([kerbs[i] for i in near]))
            f = f.buffer(0)
            if f.is_empty or f.area < min_area * 0.4:
                continue
            out.append(f)
        return out
