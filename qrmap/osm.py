"""OpenStreetMap extract: fetch once with Overpass, cache as JSON, build a GeoModel.

Map data (c) OpenStreetMap contributors, ODbL 1.0. The rendered map carries that
attribution in its lower border.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, polygonize, polylabel, unary_union

from . import config
from .geo import FRAME, MX as _MX, MY as _MY, GeoModel, Label, proj

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
MAJOR = {"motorway", "trunk", "primary", "secondary", "motorway_link", "trunk_link",
         "primary_link", "secondary_link"}
MINOR = {"tertiary", "tertiary_link", "unclassified", "residential", "living_street"}
PLACES = {  # place=* -> (label size, style), most important first
    "city": (2.3, "caps"), "town": (1.8, "caps"), "suburb": (1.35, "caps"),
    "village": (1.35, "caps"), "quarter": (1.1, "caps"), "neighbourhood": (1.0, "italic"),
    "hamlet": (0.95, "italic"),
}


def _ql(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def query() -> str:
    b = ",".join(f"{v:.5f}" for v in config.BBOX)
    hw = "|".join(sorted(MAJOR | (MINOR if config.MINOR_ROADS else set())))
    landmarks = "".join(f'\n  nwr["name"="{_ql(n)}"]({b});' for n in config.LANDMARKS)
    return f"""[out:json][timeout:{240 if config.RADIUS_MILES <= 5 else 600}];
(
  way["highway"~"^({hw})$"]({b});
  node["place"~"^({"|".join(PLACES)})$"]({b});
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
  way["landuse"~"^(forest|cemetery)$"]({b});{landmarks}
);
out geom;"""


def cache_path() -> Path:
    """One cache file per location and query, so editing config.yaml never reuses stale data."""
    slug = re.sub(r"[^a-z0-9]+", "-", config.NAME.lower()).strip("-") or "map"
    return config.DATA / f"osm-{slug}-{hashlib.sha1(query().encode()).hexdigest()[:10]}.json"


def fetch(path: Path | None = None) -> Path:
    path = path or cache_path()
    print(f"{config.NAME}: {config.RADIUS_MILES:g} mi around {config.CENTER[0]:.5f}, "
          f"{config.CENTER[1]:.5f} (bbox S,W,N,E = {', '.join(f'{v:.5f}' for v in config.BBOX)})",
          file=sys.stderr)
    body = urllib.parse.urlencode({"data": query()}).encode()
    last = None
    for url in ENDPOINTS:
        try:
            print(f"Querying {url} ...", file=sys.stderr)
            req = urllib.request.Request(url, data=body, headers={"User-Agent": "wifi-qr-map/1.0"})
            with urllib.request.urlopen(req, timeout=660) as r:
                data = json.load(r)
            if data.get("remark"):  # Overpass reports timeouts and memory limits here
                raise RuntimeError(data["remark"])
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


def config_labels() -> list[Label] | None:
    """Place names from config.yaml, or None to take them from OSM."""
    if config.LABELS is None:
        return None
    return [Label(float(lb["at"][0]), float(lb["at"][1]), str(lb["text"]), float(lb.get("size", 1.0)),
                  lb.get("style", "italic"), float(lb.get("angle", 0.0)), float(lb.get("tracking", 0.0)))
            for lb in config.LABELS]


def _osm_labels(places, named_waters) -> list[Label]:
    """Places (most important first), then large named waters at their widest point."""
    rank = list(PLACES)
    inner = FRAME.buffer(-FRAME.bounds[2] * 0.06)  # names on the neat line get cut off
    out = []
    for kind, name, lat, lon in sorted(places, key=lambda p: rank.index(p[0])):
        if not inner.contains(Point(proj(lat, lon))):
            continue
        size, style = PLACES[kind]
        out.append(Label(lat, lon, name, size, style, 0.0, 0.25 if style == "caps" else 0.0))
    for name, area in sorted(named_waters, key=lambda w: -w[1].area):
        area = area.intersection(FRAME)
        if area.is_empty or area.area < FRAME.area * 0.01:
            continue
        p = max(getattr(area, "geoms", [area]), key=lambda g: g.area)
        c = polylabel(p, tolerance=10)
        x0, y0, x1, y1 = p.bounds
        angle = 80.0 if (y1 - y0) > 2 * (x1 - x0) else 0.0
        lat, lon = c.y / _MY + config.SOUTH, c.x / _MX + config.WEST
        out.append(Label(lat, lon, name.upper(), 1.6, "caps", angle, 0.25))
    return out


def build(path: Path | None = None) -> GeoModel:
    data = json.loads((path or cache_path()).read_text())
    m = GeoModel(source="OpenStreetMap (c) OpenStreetMap contributors, ODbL")
    waters, coasts, named_waters, places = [], [], [], []
    landmarks = {}
    for el in data.get("elements", []):
        t = el.get("tags", {})
        name = t.get("name", "")
        if el["type"] == "node" and t.get("place") in PLACES and name:
            places.append((t["place"], name, el["lat"], el["lon"]))
            continue
        if name in config.LANDMARKS and name not in landmarks:
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
                if name:
                    named_waters.append((name, a))
        elif t.get("leisure") in ("park", "nature_reserve", "golf_course") or \
                t.get("natural") == "wood" or t.get("landuse") in ("forest", "cemetery"):
            a = _area(el)
            if a is not None and a.area > 4_000 * config.STYLE ** 2:
                m.parks.append(a.intersection(FRAME))
    cw = _coast_water(coasts)
    if cw is not None:
        waters.append(cw)
    m.water = unary_union(waters).intersection(FRAME) if waters else None
    # Streams already drawn as water areas are redundant as lines.
    if m.water is not None:
        m.streams = [(ls.difference(m.water), n) for ls, n in m.streams]
        m.streams = [(g, n) for g, n in m.streams if not g.is_empty]
    m.hills = [(*proj(lat, lon), r) for lat, lon, r in config.HILLS]
    for full, kind in config.LANDMARKS.items():
        if full in landmarks:
            x, y = landmarks[full]
            m.landmarks.append((x, y, kind, full))
    labels = config_labels()
    m.labels = _osm_labels(places, named_waters) if labels is None else labels
    return m


def load() -> GeoModel:
    path = cache_path()
    if path.exists():
        return build(path)
    if config.OFFLINE_FALLBACK == "alexandria":
        from . import seed
        print(f"no OSM cache at {path.relative_to(config.ROOT)}; using the hand-plotted "
              "Alexandria schematic (run `make fetch` for the real map)", file=sys.stderr)
        return seed.build()
    raise SystemExit(f"No OSM data for {config.NAME} at {path}. Run `make fetch` first "
                     f"(config: {config.CONFIG_FILE}).")


if __name__ == "__main__":
    fetch()
