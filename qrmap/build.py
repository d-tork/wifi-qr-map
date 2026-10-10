"""Build the 12 x 12 in Wi-Fi map: payload -> matrix -> map art -> QR-guided composite.

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

import cv2
import numpy as np
from PIL import Image

from . import compose, config, frame, osm, qr, render_map, validate

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


def _svg(out: Path, layout: config.Layout, code: qr.Code, g: compose.Geometry):
    """Inkscape master: final raster, map-only raster and vector QR reference as layers."""
    s = layout.size
    inch = layout.inches
    rects = "".join(
        f'<rect x="{g.x0 + c * g.module}" y="{g.y0 + r * g.module}" width="{g.module}" height="{g.module}"/>'
        for r in range(code.n) for c in range(code.n) if code.dark[r, c])
    grid = "".join(
        f'<line x1="{g.x0 + i * g.module}" y1="{g.y0}" x2="{g.x0 + i * g.module}" y2="{g.y0 + g.side}"/>'
        f'<line x1="{g.x0}" y1="{g.y0 + i * g.module}" x2="{g.x0 + g.side}" y2="{g.y0 + i * g.module}"/>'
        for i in range(code.n + 1))
    lay = 'inkscape:groupmode="layer"'
    out.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     width="{inch}in" height="{inch}in" viewBox="0 0 {s} {s}">
  <g {lay} inkscape:label="Map art (no QR)" style="display:none">
    <image xlink:href="layers/map.png" width="{s}" height="{s}"/></g>
  <g {lay} inkscape:label="Final artwork" sodipodi:insensitive="true" xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd">
    <image xlink:href="wifi-map-12in.png" width="{s}" height="{s}"/></g>
  <g {lay} inkscape:label="QR reference (dark modules)" style="display:none;opacity:0.5;fill:#d00">{rects}</g>
  <g {lay} inkscape:label="Module grid" style="display:none;stroke:#09f;stroke-width:1">{grid}</g>
</svg>
''')


def build(a) -> Path:
    t0 = time.time()
    ssid, password, security, hidden = credentials(a)
    payload = qr.wifi_payload(ssid, password, security, hidden)
    layout = config.Layout(dpi=a.dpi)
    out = Path(a.out)
    (out / "layers").mkdir(parents=True, exist_ok=True)

    probe = qr.make(payload, version=a.version)
    g = compose.geometry(layout, probe.n)
    model = osm.load()
    print(f"map data: {model.source}")
    print(f"QR version {probe.version}-{probe.error}: {probe.n} modules, {g.module}px "
          f"({g.module / layout.dpi:.3f} in) per module, symbol {g.side / layout.dpi:.2f} in")

    art = render_map.render(model, layout, ss=a.ss, quiet_px=g.quiet * g.module)
    rgb = art["rgb"]

    gray_sym = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)[g.y0:g.y0 + g.side, g.x0:g.x0 + g.side]

    def lightness(n):
        cells = cv2.resize(gray_sym, (n, n), interpolation=cv2.INTER_AREA)
        return np.clip(0.5 + (cells - np.median(cells)) / (4 * cells.std() + 1e-6), 0, 1)

    code = qr.make(payload, version=probe.version, art_lightness=lightness)
    print(f"mask {code.mask} chosen; art/QR tone agreement {code.agreement:.1%}")

    final, g, T = compose.compose(art, code, layout)
    img = Image.fromarray((final * 255).round().astype(np.uint8))
    frame.draw(img, layout, f"Map data: {model.source}")
    png = out / "wifi-map-12in.png"
    img.save(png, dpi=(layout.dpi, layout.dpi), optimize=False)
    if not a.no_pdf:
        img.save(png.with_suffix(".pdf"), resolution=layout.dpi)
    Image.fromarray((rgb * 255).round().astype(np.uint8)).save(out / "layers" / "map.png", dpi=(layout.dpi,) * 2)
    Image.fromarray(((1 - T) * 255).astype(np.uint8)).save(out / "layers" / "qr-tone-target.png", dpi=(layout.dpi,) * 2)
    code.segno().save(str(out / "qr-reference.svg"), scale=10, border=layout.quiet_zone)
    _svg(out / "artwork.svg", layout, code, g)
    img.resize((1200, 1200), Image.LANCZOS).save(out / "preview.jpg", quality=88)

    manifest = {
        "dpi": layout.dpi, "inches": layout.inches, "version": code.version, "error": code.error,
        "mask": code.mask, "payload_sha256": code.payload_sha256, "ssid": ssid, "security": security,
        "geometry": g.to_dict(), "map_source": model.source,
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
    ap.add_argument("--version", type=int, help="force a QR version (more modules = finer grain)")
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
