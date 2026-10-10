"""OpenStreetMap extract: fetch once with Overpass, cache as JSON, build a GeoModel.

Map data (c) OpenStreetMap contributors, ODbL 1.0. The rendered map carries that
attribution in its lower border.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, polygonize, unary_union

from . import config, seed
from .geo import FRAME, GeoModel, proj

CACHE = config.DATA / "osm-alexandria.json"
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
MAJOR = {"motorway", "trunk", "primary", "secondary", "motorway_link", "trunk_link",
         "primary_link", "secondary_link"}
MINOR = {"tertiary", "tertiary_link", "unclassified", "residential", "living_street"}
LANDMARK_NAMES = {
    "George Washington Masonic National Memorial": "temple",
    "Christ Church": "church",
    "Market Square": "market",
    "Jones Point Lighthouse": "lighthouse",
}


def query() -> str:
    b = ",".join(f"{v:.5f}" for v in config.BBOX)
    hw = "|".join(sorted(MAJOR | MINOR))
    names = "|".join(LANDMARK_NAMES)
    return f"""[out:json][timeout:240];
(
  way["highway"~"^({hw})$"]({b});
  way["railway"="rail"]({b});
  way["waterway"~"^(river|stream|canal)$"]({b});
  way["natural"="coastline"]({b});
  way["natural"="water"]({b});
  relation["natural"="water"]({b});
  way["waterway"="riverbank"]({b});
  relation["waterway"="riverbank"]({b});
  way["leisure"~"^(park|nature_reserve|golf_course)$"]({b});
  relation["leisure"~"^(park|nature_reserve)$"]({b});
  way["natural"="wood"]({b});
  way["landuse"~"^(forest|cemetery)$"]({b});
  nwr["name"~"^({names})$"]({b});
);
out geom;"""


def fetch(path: Path = CACHE) -> Path:
    body = urllib.parse.urlencode({"data": query()}).encode()
    last = None
    for url in ENDPOINTS:
        try:
            print(f"Querying {url} ...", file=sys.stderr)
            req = urllib.request.Request(url, data=body, headers={"User-Agent": "wifi-qr-map/1.0"})
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data))
            print(f"Saved {len(data.get('elements', []))} elements to {path}", file=sys.stderr)
            return path
        except Exception as e:  # try the next mirror
            last = e
            print(f"  failed: {e}", file=sys.stderr)
    raise SystemExit(f"All Overpass endpoints failed: {last}")


def _ls(geom) -> LineString | None:
    pts = [proj(p["lat"], p["lon"]) for p in geom or [] if p]
    return LineString(pts) if len(pts) >= 2 else None


def _area(el):
    """Polygon for a closed way or a multipolygon relation (full member geometry)."""
    if el["type"] == "way":
        ls = _ls(el.get("geometry"))
        if ls is None or len(ls.coords) < 4 or not ls.is_closed:
            return None
        return Polygon(ls.coords).buffer(0)
    rings = {"outer": [], "inner": []}
    for mem in el.get("members", []):
        ls = _ls(mem.get("geometry"))
        if ls is not None:
            rings.get(mem.get("role") or "outer", rings["outer"]).append(ls)
    outer = unary_union(list(polygonize(linemerge(rings["outer"])))) if rings["outer"] else None
    if outer is None or outer.is_empty:
        return None
    if rings["inner"]:
        outer = outer.difference(unary_union(list(polygonize(linemerge(rings["inner"])))))
    return outer.buffer(0)


def _coast_water(coasts: list[LineString]):
    """OSM coastlines have land on the left; classify the frame's faces accordingly."""
    lines = [c.intersection(FRAME) for c in coasts]
    lines = [g for g in lines if not g.is_empty]
    if not lines:
        return None
    faces = list(polygonize(unary_union(lines + [FRAME.exterior])))
    probes = []  # (point, is_water)
    for c in coasts:
        cs = list(c.coords)
        for (x0, y0), (x1, y1) in zip(cs, cs[1:]):
            dx, dy = x1 - x0, y1 - y0
            n = (dx * dx + dy * dy) ** 0.5
            if n < 1e-6:
                continue
            mx, my, ox, oy = (x0 + x1) / 2, (y0 + y1) / 2, dy / n * 2, -dx / n * 2
            probes.append((Point(mx + ox, my + oy), True))  # right of travel = water
            probes.append((Point(mx - ox, my - oy), False))
    water = []
    for f in faces:
        votes = sum(1 if w else -1 for p, w in probes if f.contains(p))
        if votes > 0:
            water.append(f)
    return unary_union(water) if water else None


def build(path: Path = CACHE) -> GeoModel:
    data = json.loads(path.read_text())
    m = GeoModel(source="OpenStreetMap (c) OpenStreetMap contributors, ODbL")
    waters, coasts = [], []
    landmarks = {}
    for el in data.get("elements", []):
        t = el.get("tags", {})
        name = t.get("name", "")
        if name in LANDMARK_NAMES and name not in landmarks:
            c = el.get("center") or (el if "lat" in el else None)
            if c is None and el.get("geometry"):
                ls = _ls(el["geometry"])
                c = None if ls is None else {"xy": ls.centroid.coords[0]}
            if c is not None:
                landmarks[name] = c["xy"] if "xy" in c else proj(c["lat"], c["lon"])
        hw = t.get("highway")
        if el["type"] == "way" and hw in MAJOR | MINOR:
            ls = _ls(el.get("geometry"))
            if ls is not None:
                m.roads.append((ls, "major" if hw in MAJOR else "minor", name))
        elif el["type"] == "way" and t.get("railway") == "rail":
            if t.get("service") in ("yard", "siding", "spur"):
                continue
            ls = _ls(el.get("geometry"))
            if ls is not None:
                m.rail.append(ls)
        elif el["type"] == "way" and t.get("waterway") in ("river", "stream", "canal"):
            ls = _ls(el.get("geometry"))
            if ls is not None:
                m.streams.append((ls, name))
        elif el["type"] == "way" and t.get("natural") == "coastline":
            ls = _ls(el.get("geometry"))
            if ls is not None:
                coasts.append(ls)
        elif t.get("natural") == "water" or t.get("waterway") == "riverbank":
            a = _area(el)
            if a is not None:
                waters.append(a)
        elif t.get("leisure") in ("park", "nature_reserve", "golf_course") or \
                t.get("natural") == "wood" or t.get("landuse") in ("forest", "cemetery"):
            a = _area(el)
            if a is not None and a.area > 4_000:
                m.parks.append(a.intersection(FRAME))
    cw = _coast_water(coasts)
    if cw is not None:
        waters.append(cw)
    m.water = unary_union(waters).intersection(FRAME) if waters else None
    # Streams already drawn as water areas are redundant as lines.
    if m.water is not None:
        m.streams = [(ls.difference(m.water), n) for ls, n in m.streams]
        m.streams = [(g, n) for g, n in m.streams if not g.is_empty]
    m.hills = seed.build().hills
    seed_marks = {lm[3]: lm for lm in seed.build().landmarks}
    for full, kind in LANDMARK_NAMES.items():
        if full in landmarks:
            x, y = landmarks[full]
            m.landmarks.append((x, y, kind, full))
    if not m.landmarks:
        m.landmarks = list(seed_marks.values())
    m.labels = seed.default_labels()
    return m


def load() -> GeoModel:
    return build() if CACHE.exists() else seed.build()


if __name__ == "__main__":
    fetch()
