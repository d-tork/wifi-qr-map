"""Build the 12 x 12 in Wi-Fi map: payload -> matrix -> a map with the code drawn in as a ward.

Credentials never go on the command line (shell history). The password comes from
$WIFI_PASSWORD, a `wifi.env` file (gitignored), or an interactive prompt.

    python -m qrmap.build --demo                    # dummy credentials
    python -m qrmap.build --ssid MyGuest            # prompts for the password
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

from . import config, district, frame, guard, osm, qr, render_map, validate

Image.MAX_IMAGE_PIXELS = None
DEMO = {"ssid": "Alexandria Guest", "password": "Potomac-1749", "security": "WPA"}


def _read_env_file(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def credentials(a) -> tuple[str, str | None, str, bool]:
    if a.demo:
        return DEMO["ssid"], DEMO["password"], DEMO["security"], False
    env = {**_read_env_file(config.ROOT / "wifi.env"), **os.environ}
    ssid = a.ssid or env.get("WIFI_SSID")
    if not ssid:
        sys.exit("No SSID: pass --ssid, set WIFI_SSID, or use --demo")
    security = (a.security or env.get("WIFI_SECURITY") or "WPA").upper()
    hidden = a.hidden or env.get("WIFI_HIDDEN", "").lower() in ("1", "true", "yes")
    password = None
    if security not in ("NOPASS", "NONE", "OPEN"):
        password = env.get("WIFI_PASSWORD") or getpass.getpass(f"Password for {ssid!r}: ")
    return ssid, password, security, hidden


def _bits(a: np.ndarray) -> list[str]:
    return ["".join("1" if v else "0" for v in row) for row in a]


def legend_entries(a, ssid, password, env) -> tuple[str, str | None]:
    """The fallback text for phones that won't scan: the network name (printed beside
    the Wi-Fi mark) and the password (printed alone at the foot of the legend, with
    no label, so it doesn't announce itself), or None to leave the password off."""
    net = a.legend_network_text or env.get("WIFI_LEGEND_NETWORK_TEXT") or ssid
    pw = a.legend_password_text or env.get("WIFI_LEGEND_PASSWORD_TEXT") or password
    return net, None if a.no_legend_password else pw


def _svg(out: Path, layout: config.Layout, code: qr.Code, dist: district.District):
    """Inkscape master: final raster, map-only raster and vector QR reference as layers."""
    s = layout.size
    inch = layout.inches
    def poly(pts):
        return "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in pts) + " Z"
    dark = "".join(poly(dist.square(c, r, c + 1, r + 1)) for r in range(code.n)
                   for c in range(code.n) if code.dark[r, c])
    lay = 'inkscape:groupmode="layer"'
    out.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
     width="{inch}in" height="{inch}in" viewBox="0 0 {s} {s}">
  <g {lay} inkscape:label="Final artwork" sodipodi:insensitive="true">
    <image xlink:href="wifi-map-12in.png" width="{s}" height="{s}"/></g>
  <g {lay} inkscape:label="QR reference (dark modules)" style="display:none;opacity:0.5">
    <path d="{dark}" fill="#d00"/></g>
  <g {lay} inkscape:label="Quiet zone (keep light)" style="display:none">
    <path d="{poly(dist.reserve())}" fill="none" stroke="#09f" stroke-width="2"/></g>
</svg>
''')


def build(a) -> Path:
    t0 = time.time()
    ssid, password, security, hidden = credentials(a)
    env = {**_read_env_file(config.ROOT / "wifi.env"), **os.environ}
    payload = qr.wifi_payload(ssid, password, security, hidden)
    layout = config.Layout(dpi=a.dpi)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    code = qr.make(payload, version=a.version, error=a.ecc, score=qr.blockiness)
    center = tuple(float(v) for v in a.center.split(",")) if a.center else None
    model = osm.load()
    dist = district.place(layout, code.n, center=center, angle=a.angle, module_in=a.module_in, model=model)
    print(f"map data: {model.source}")
    print(f"QR version {code.version}-{code.error}, mask {code.mask}: {code.n} modules of "
          f"{dist.module}px ({dist.module / layout.dpi:.3f} in); ward {dist.side / layout.dpi:.2f} in "
          f"+ {dist.quiet}-module quiet zone, turned {dist.angle:g} deg")

    net, pw = legend_entries(a, ssid, password, env)
    legend = None if a.no_legend else {"title": config.LEGEND_TITLE, "network": net, "password": pw}
    art = render_map.render(model, layout, ss=a.ss, district=dist, code=code, legend=legend)
    print(f"{art['courts']} court(s) elsewhere in town echo the finder patterns")
    final, fixed = guard.guard(art["rgb"], code, dist)
    print(f"guard pass corrected {fixed} module centre(s)")
    img = Image.fromarray((final * 255).round().astype(np.uint8))
    frame.draw(img, layout, f"Map data: {model.source}")
    png = out / "wifi-map-12in.png"
    img.save(png, dpi=(layout.dpi, layout.dpi), optimize=False)
    if not a.no_pdf:
        img.save(png.with_suffix(".pdf"), resolution=layout.dpi)
    code.segno().save(str(out / "qr-reference.svg"), scale=10, border=4)
    _svg(out / "artwork.svg", layout, code, dist)
    img.resize((1200, 1200), Image.LANCZOS).save(out / "preview.jpg", quality=88)
    x0, y0, x1, y1 = (int(v) for v in dist.bbox(extra=dist.quiet))
    img.crop((x0, y0, x1, y1)).save(out / "ward-detail.png")

    manifest = {
        "dpi": layout.dpi, "inches": layout.inches, "version": code.version, "error": code.error,
        "mask": code.mask, "payload_sha256": code.payload_sha256, "ssid": ssid, "security": security,
        "district": dist.to_dict(), "module_inches": dist.module / layout.dpi, "map_source": model.source,
        "legend_shows_password": bool(legend) and legend["password"] is not None,
        "legend_references": art["references"],
        "guard_corrections": fixed,
        "matrix": _bits(code.dark), "function": _bits(code.function),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"wrote {png} ({time.time() - t0:.0f}s)")
    return png


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--demo", action="store_true", help="use dummy credentials")
    ap.add_argument("--ssid")
    ap.add_argument("--security", help="WPA (default, covers WPA2/3-personal), SAE, WEP or nopass")
    ap.add_argument("--hidden", action="store_true")
    ap.add_argument("--version", type=int, help="force a larger QR version (more, smaller blocks)")
    ap.add_argument("--ecc", default=config.ECC, choices=list("lmqh"), help="error correction level")
    ap.add_argument("--center", help="ward centre as LAT,LON (default: ward.center in config.yaml)")
    ap.add_argument("--angle", type=float, help="ward rotation in degrees (default: ward.angle in config.yaml, "
                    "or the nearest major street's direction)")
    ap.add_argument("--module-in", type=float, help=f"module and house-plot size in inches (default {config.MODULE_INCHES}); "
                    "the map's scale stays fixed")
    lg = ap.add_argument_group("legend (fallback text for devices that can't scan)")
    lg.add_argument("--legend-network-text", help="default: the SSID")
    lg.add_argument("--legend-password-text", help="default: the password (e.g. set a hint instead)")
    lg.add_argument("--no-legend-password", action="store_true", help="omit the password line")
    lg.add_argument("--no-legend", action="store_true")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--ss", type=int, default=2, help="supersampling for line art")
    ap.add_argument("--out", default=str(config.ROOT / "build"))
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--skip-validate", action="store_true")
    a = ap.parse_args(argv)
    png = build(a)
    if not a.skip_validate:
        sys.exit(0 if validate.validate(png, report=png.with_name("validation.json")) else 1)


if __name__ == "__main__":
    main()
