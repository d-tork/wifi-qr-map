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


def test_legend_rows():
    from types import SimpleNamespace
    from qrmap.build import legend_rows
    a = SimpleNamespace(legend_network_label=None, legend_password_label="Key", legend_network_text=None,
                        legend_password_text=None, no_legend_password=False)
    assert legend_rows(a, "Guest", "pw", {}) == [("Network", "Guest"), ("Key", "pw")]
    a.no_legend_password = True
    assert legend_rows(a, "Guest", "pw", {}) == [("Network", "Guest")]


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
