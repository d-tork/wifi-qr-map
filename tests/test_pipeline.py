"""Fast checks that need no network: payload escaping, OSM assembly, mask choice."""

import json

import numpy as np
import zxingcpp
from shapely.affinity import translate

from qrmap import config, osm, qr
from qrmap.geo import FRAME

S, W, N, E = config.SOUTH, config.WEST, config.NORTH, config.EAST
MID = (W + E) / 2


def _node(lat, lon):
    return {"lat": lat, "lon": lon}


def test_wifi_payload_escaping():
    bs = chr(92)  # backslash; Segno escapes \ ; : " (commas need no escape in WIFI:)
    p = qr.wifi_payload("My;Net", 'pa:ss,"x"' + bs, "WPA2")
    assert p == "WIFI:T:WPA;S:My" + bs + ";Net;P:pa" + bs + ":ss," + bs + '"x' + bs + '"' + bs + bs + ";;"
    assert qr.wifi_payload("Open", None, "nopass") == "WIFI:T:nopass;S:Open;;"


def test_qr_roundtrip_and_mask_choice():
    payload = qr.wifi_payload("Guest", "correct horse", "WPA")
    code = qr.make(payload, score=qr.blockiness)
    assert 0 <= code.mask < 8 and code.error == "Q"
    assert code.agreement == max(qr.blockiness(*qr._matrices(qr.segno.make_qr(
        payload, error="q", version=code.version, mask=k, boost_error=False))[:2]) for k in range(8))
    img = np.kron(~code.dark, np.ones((8, 8), bool)).astype(np.uint8) * 255
    img = np.pad(img, 32, constant_values=255)
    assert zxingcpp.read_barcodes(img)[0].text == payload


def test_osm_coastline_and_relation(tmp_path):
    # Coastline running north along MID: OSM puts land on the left, so the east is sea.
    coast = {"type": "way", "tags": {"natural": "coastline"},
             "geometry": [_node(S - 0.01, MID), _node(N + 0.01, MID)]}
    lake = {"type": "relation", "tags": {"natural": "water"}, "members": [
        {"type": "way", "role": "outer", "geometry": [_node(S + .01, W + .002), _node(S + .01, W + .006)]},
        {"type": "way", "role": "outer", "geometry": [_node(S + .01, W + .006), _node(S + .015, W + .006),
                                                     _node(S + .01, W + .002)]}]}
    road = {"type": "way", "tags": {"highway": "residential", "name": "Test St"},
            "geometry": [_node(S + .02, W), _node(S + .02, MID)]}
    path = tmp_path / "osm.json"
    path.write_text(json.dumps({"elements": [coast, lake, road]}))
    m = osm.build(path)
    east = FRAME.bounds[2]
    assert m.water.contains(translate(FRAME.centroid, east / 4, 0))  # sea side
    assert not m.water.contains(translate(FRAME.centroid, -east / 4, 0))  # land side
    assert m.water.area > FRAME.area * 0.45
    assert any(name == "Test St" for _, _, name in m.roads)


def test_district_transform():
    from qrmap.district import District
    d = District(cx=100, cy=100, module=10, n=20, quiet=3, angle=0)
    assert d.to_px(0, 0) == (0, 0) and d.center(0, 0) == (5, 5)
    r = District(cx=100, cy=100, module=10, n=20, quiet=3, angle=90)
    x, y = r.to_px(20, 0)  # top-right corner turns to the top-left when rotated 90 deg CCW
    assert abs(x - 0) < 1e-9 and abs(y - 0) < 1e-9


def test_legend_entries():
    from types import SimpleNamespace
    from qrmap.build import legend_entries
    a = SimpleNamespace(legend_network_text=None, legend_password_text=None, no_legend_password=False)
    assert legend_entries(a, "Guest", "pw", {}) == ("Guest", "pw")
    assert legend_entries(a, "Guest", None, {}) == ("Guest", None)  # open network
    assert legend_entries(a, "Guest", "pw", {"WIFI_LEGEND_PASSWORD_TEXT": "ask at the bar"}) == ("Guest", "ask at the bar")
    a.no_legend_password = True
    assert legend_entries(a, "Guest", "pw", {}) == ("Guest", None)


def test_config_bbox_is_square_around_center():
    from qrmap.geo import HEIGHT_M, WIDTH_M
    side = 2 * config.RADIUS_MILES * config.MILE
    assert abs(WIDTH_M - side) < 1 and abs(HEIGHT_M - side) < 1
    assert abs((S + N) / 2 - config.CENTER[0]) < 1e-9 and abs(MID - config.CENTER[1]) < 1e-9


def test_query_and_cache_follow_config():
    q = osm.query()
    assert ",".join(f"{v:.5f}" for v in config.BBOX) in q
    assert all(f'"name"="{n}"' in q for n in config.LANDMARKS)
    assert osm.cache_path().parent == config.DATA and osm.cache_path().suffix == ".json"


def test_osm_place_labels_when_config_has_none(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LABELS", None)
    town = {"type": "node", "lat": (S + N) / 2, "lon": MID, "tags": {"place": "town", "name": "Testville"}}
    edge = {"type": "node", "lat": N - 1e-5, "lon": MID, "tags": {"place": "hamlet", "name": "Edge"}}
    path = tmp_path / "osm.json"
    path.write_text(json.dumps({"elements": [edge, town]}))
    labels = osm.build(path).labels
    assert [lb.text for lb in labels] == ["Testville"]  # ranked, and nothing on the neat line


def test_scale_is_fixed_and_radius_rejected(tmp_path):
    from qrmap.geo import WIDTH_M
    x0, _, x1, _ = config.Layout().map_box
    plots = (x1 - x0) / config.Layout().dpi / config.MODULE_INCHES
    assert abs(WIDTH_M / plots - config.PLOT_METRES) < 1e-6  # one plot = one module
    cfg = tmp_path / "old.yaml"
    cfg.write_text("center: [38.9, -77.0]\nradius_miles: 2\n")
    try:
        config._load(cfg)
    except SystemExit as e:
        assert "radius_miles" in str(e)
    else:
        raise AssertionError("radius_miles should be rejected")


def test_ward_streets_avoid_patterns():
    from qrmap.ward import street_cuts
    for version in (3, 4, 7, 10):  # v1-2 at ECC Q are too small for this payload
        code = qr.make(qr.wifi_payload("Guest", "pw", "WPA"), version=version)
        for spacing in (6, 12):
            for al in (code.alignment, code.alignment.T):
                cuts = street_cuts(code.n, al, spacing)
                assert not any((al[:, p - 1] & al[:, p]).any() for p in cuts)
                # Beside the finders, or one module further where an alignment pattern
                # sits against them (version 7 and up).
                assert cuts[0] in (8, 9) and cuts[-1] in (code.n - 8, code.n - 9)


def test_ward_turns_to_nearest_major_street():
    from types import SimpleNamespace
    from shapely.geometry import LineString
    from qrmap.district import street_angle
    road = LineString([(0, 0), (1000, 1000 * np.tan(np.radians(20)))])
    far = LineString([(0, 500), (0, 900)])
    m = SimpleNamespace(roads=[(road, "major", "Main"), (far, "minor", "Lane")])
    assert abs(street_angle(m, 500, 150) - 20) < 1e-6
    steep = LineString([(0, 0), (100, 100 * np.tan(np.radians(80)))])
    assert abs(street_angle(SimpleNamespace(roads=[(steep, "major", "")]), 10, 10) - (-10)) < 1e-6


def _runs(line):
    runs, cur, n = [], line[0], 0
    for v in line:
        if v == cur:
            n += 1
        else:
            runs.append(n)
            cur, n = v, 1
    return runs + [n]


def test_courts_are_not_finder_patterns():
    from qrmap.houses import COURTS
    for built in COURTS:
        w, h = built.shape
        across, along = _runs(built[:, h // 2]), _runs(built[w // 2, :])
        assert len(across) == len(along) == 5
        # A finder reads 1:1:3:1:1 both ways: ZXing accepts each bar within 0.5 module
        # (0.75 relaxed) of its expected width. At least one axis must break that.
        def finder_like(r):
            m = sum(r) / 7
            return all(abs(v - e * m) <= m * 0.75 for v, e in zip(r, (1, 1, 3, 1, 1)))
        assert not (finder_like(across) and finder_like(along)), built.shape


def test_block_plots_fill_the_block_deterministically():
    from shapely.geometry import Polygon, box
    from shapely.affinity import rotate
    from qrmap import houses
    block = rotate(box(0, 0, 300, 120), 30, origin=(0, 0))
    a = houses.block_plots(block, 30, np.random.default_rng(7))
    b = houses.block_plots(block, 30, np.random.default_rng(7))
    assert a[0] == b[0] and a[1] == b[1]
    built = a[0]
    assert 0 < len(built) <= 40
    assert all(block.buffer(1e-6).contains(Polygon(h)) for h in built)
    court = houses.block_plots(rotate(box(0, 0, 330, 330), 30, origin=(0, 0)), 30, np.random.default_rng(1), True)
    assert court[2]


def test_references_pick_real_buildings(monkeypatch):
    from qrmap import render_map
    from qrmap.geo import GeoModel
    cv = render_map.Canvas(config.Layout(dpi=100), 1)
    w = FRAME.bounds[2]
    m = GeoModel(source="test")
    m.landmarks = [(w * 0.5, w * 0.5, "church", "Christ Church")]
    m.pois = [(w * 0.52, w * 0.5, "historic", "Too Close House"),  # crowds the landmark
              (w * 0.2, w * 0.8, "station", "Depot"),
              (w * 0.8, w * 0.2, "historic", "Carlyle House"),
              (w * 0.8, w * 0.8, "church", "A Church Whose Name Runs Far Too Long"),
              (w * 0.2, w * 0.2, "museum", "Lyceum"),
              (w * 0.99, w * 0.5, "civic", "Edge Hall")]  # on the neat line
    monkeypatch.setattr(config, "REFERENCES", None)
    names = [n for _, _, n in render_map._references(m, cv, [])]
    assert sorted(names) == ["Carlyle House", "Christ Church", "Depot", "Lyceum"]
    assert names[0] == "Depot"  # lettered north to south: Depot is at the top
    x, y = cv.xy(w * 0.2, w * 0.2)
    avoid = [(x - 5, y - 5, x + 5, y + 5)]  # e.g. the ward
    assert "Lyceum" not in [n for _, _, n in render_map._references(m, cv, avoid)]
    monkeypatch.setattr(config, "REFERENCES", [(S + 0.001, W + 0.001, "Mine")])
    assert [n for _, _, n in render_map._references(m, cv, [])] == ["Mine"]


def test_legend_lists_references_before_wifi_rows():
    from qrmap import render_map, ward
    cv = render_map.Canvas(config.Layout(dpi=100), 1)
    lg = {"title": "REFERENCES", "network": "Guest", "password": "pw", "refs": [("A", "Carlyle House")]}
    L = ward.legend_box(cv, lg, render_map.font)
    # No "Network" / "Password" labels: the Wi-Fi mark keys the name; the password stands alone.
    assert L["rows"] == [("A", "Carlyle House"), ("", "Guest")] and L["icon_row"] == 1
    assert L["password"] == "pw" and all("pw" not in v for _, v in L["rows"])
    H = L["box"][3] - L["box"][1]
    assert H > ward.legend_box(cv, {**lg, "password": None}, render_map.font)["box"][3] - L["box"][1] - 1e-6
    x0, y0, x1, y1 = L["box"]
    assert cv.box[0] <= x0 < x1 <= cv.box[2] and cv.box[1] <= y0 < y1 <= cv.box[3]
