# Wi-Fi QR colonial map

A reproducible pipeline that prints your guest Wi-Fi as a **12 × 12 in, 18th-century
style plan of Alexandria**: Old Town, Rosemont, and Del Ray (the former Town of
Potomac). The QR code is **hidden in the map** as a made-up ward of Del Ray. Its built
house blocks are the dark modules, its empty lots are the light ones, and its three
walled squares are the finder patterns. A legend cartouche in the river gives the
network name and password, with a small Wi-Fi mark, for any device that can't scan.
Every build is checked by decoders before it counts as done.

![demo](examples/demo-preview.jpg)

| The hidden ward at 1:1 (300 dpi) | Legend at 1:1 | Validator's module check |
|---|---|---|
| ![](examples/demo-ward-1to1.png) | ![](examples/demo-legend-1to1.png) | ![](examples/demo-module-check.png) |

The demo uses dummy credentials (`Alexandria Guest` / `Potomac-1749`).

## Quick start

```sh
make venv            # .venv with pinned deps (segno, pillow, numpy, opencv-contrib, zxing-cpp, shapely)
make fetch           # one-off: OpenStreetMap extract -> data/osm-alexandria.json (needs internet)
make demo            # dummy credentials -> build/, then validate
cp wifi.env.example wifi.env && $EDITOR wifi.env
make build           # your network (or: WIFI_PASSWORD=... make build ARGS="--ssid MyGuest")
make proof           # 8 x 8 in PDF of the sheet, for a cheap test print
```

`make build` exits non-zero if validation fails. The password is never accepted as a
command-line flag. It comes from `$WIFI_PASSWORD`, the gitignored `wifi.env`, or a
prompt, and it is masked in every log and report. The printed legend shows it on
purpose; to leave it off, use `--no-legend-password` or `--legend-password-text "ask
at the bar"`.

### Options (`make build ARGS="..."`)

| Option | Default | Effect |
|---|---|---|
| `--center LAT,LON` | `38.8276,-77.0572` (Del Ray) | Where the hidden ward sits |
| `--angle DEG` | `0` | Rotate the ward. `-9` matches Old Town's grid. |
| `--module-in IN` | `0.05` | Printed block size. Bigger is easier to scan and less hidden. |
| `--ecc l/m/q/h` | `q` | Error correction. Higher means more modules, so a bigger ward. |
| `--version N` | smallest that fits | Force more, smaller-scale blocks |
| `--legend-network-label` / `--legend-password-label` | `Network` / `Password` | Legend labels |
| `--legend-network-text` / `--legend-password-text` | SSID / password | Legend values |
| `--no-legend-password`, `--no-legend` | | Omit the password row, or the whole legend |

The same settings live in `qrmap/config.py`, along with hatch pitch, street width, tones,
legend position and text size, palette, and layout. Legend text can also be set
through `WIFI_LEGEND_*` in `wifi.env`.

## Outputs (`build/`, gitignored)

| File | What it is |
|---|---|
| `wifi-map-12in.png` | Final art, 3600 × 3600 px, 300 dpi (pHYs set) |
| `wifi-map-12in.pdf` | Same, on a 12 × 12 in page, for the print shop |
| `ward-detail.png` | Crop of the hidden ward at 1:1 |
| `artwork.svg` | Inkscape master: the final raster, plus hidden layers with the vector QR reference and the quiet-zone outline |
| `qr-reference.svg` | The plain QR code, for comparison |
| `manifest.json` | Version, mask, ward placement, module matrix, and the payload's SHA-256 (not the password) |
| `validation.json`, `*-module-check.png` | Validator report, plus a ward close-up with any wrong modules boxed in red |

## How the code is hidden

```
credentials ─► Segno WIFI: payload (ECC Q) ─► of 8 valid masks, keep the most town-like
OSM extract ─► shapely geometry ─► engraved map (Pillow/OpenCV, 2× supersampled)
                                       │  the ward's footprint is cleared and redrawn:
                                       ▼
   dark module  → built block: carmine wash, 45° hatching, ink outline
   light module → open lot, faint lot lines
   finder       → walled square with bastions on its three outer corners
   quiet zone   → more open lots; real streets stop at its edge
                                       │
          legend cartouche + Wi-Fi mark · guard pass · frame ─► validate
```

- **Same ink as the rest of the town.** The ward uses the same carmine wash and
  hatching as Old Town's blocks. Narrow streets split most neighbouring built blocks,
  and some merge into larger blocks, so from across a room it reads as one more
  densely built neighbourhood.
- **Town-like mask.** Of the eight masks, which are all equally valid, the build
  keeps the one where built blocks most often join their neighbours, so the ward looks
  less like scattered pixels.
- **Geometry rules.** Streets and lot lines run along module edges, never through a
  module centre. Each finder's bastion is left off the corner facing into the code,
  so the separator module next to it stays light.
- **Guard pass.** After rendering, any module centre that lands on the wrong side of
  the light/dark targets is pulled back. With the defaults it corrects 0 modules.
- **ECC Q instead of H.** The modules are drawn cleanly rather than damaged by art,
  so a lower error-correction level is enough. That keeps the ward small: the demo
  payload is version 4, 33 × 33 blocks, 1.65 in square.

## Validation (`make validate IMAGE=...`)

Run this on whatever you'll actually print, including files you've edited by hand in
GIMP or Inkscape. The `manifest.json` from the build has to sit next to the image.

1. **Print geometry.** The image is 3600 × 3600 px with 300 dpi metadata, and the
   PDF MediaBox is 12 × 12 in.
2. **Module fidelity.** A lattice over the central 30% of every module is sampled,
   following the ward's rotation. Gate: zero errors, and at least 60 grey levels
   between the lightest dark centre and the darkest light centre. The report also
   gives the quiet zone's mean tone and a defocus error rate.
3. **Decoder battery.** ZXing-C++ and three OpenCV detectors, including WeChat, are
   run on 17 captures:
   - the whole sheet at 3600, 2400, and 1500 px
   - close-ups framing the ward, as a phone held 15–30 cm away would, at 1400, 900,
     600, and 400 px
   - close-ups with rotation, 6% and 10% perspective, blur, sensor noise, JPEG q35,
     glare, low light, and a combined capture

   Gates: every clean capture must be read by at least 2 decoders, and ZXing must read
   at least 80% of the stressed ones. Decoded text must hash to the manifest's SHA-256.

Results:
- **Demo:** 0 / 1089 centre errors, contrast margin 116, 17 / 17 captures read by
  ZXing and WeChat.
- **Longer payload, rotated −9°:** a 33-character password at version 7 passes too.
- **Plain `cv2.QRCodeDetector`:** misses some captures, so it doesn't gate the build.

**A desktop pass is necessary but not sufficient.** At 0.05 in per module, this code is
meant to be scanned up close, about 15–30 cm away, which suits "the code is hidden in
the map". Before ordering the 12 in print:
- Print `make proof`. It's scaled to 8 in, so the modules print smaller than the real
  sheet's, which makes it a conservative test.
- Test with the iPhone Camera app and an Android camera, under the light where the
  print will hang, and behind the glass if it will be framed. Matte glass or no glass
  is easiest to scan.
- If scanning is fussy, raise `--module-in` to 0.06–0.07, or shorten the password.

## Map data and accuracy

- **`make fetch`** pulls roads, rail, water (including coastline handling), parks,
  and landmark positions for the bounding box in `qrmap/config.py` from the Overpass
  API, and caches them in `data/`. Builds use the cache automatically. Data ©
  OpenStreetMap contributors, ODbL. The attribution is printed in the lower border.
- **Without the cache**, a hand-plotted fallback (`qrmap/seed.py`) is used. Old Town's
  grid is generated from its real street order, spacing, and ~9° skew, and the
  shoreline and arterials come from known landmarks. Del Ray's grid spacing and
  Rosemont's lanes are schematic, so treat that version as a layout proof, not a map.
  The demo images above use the fallback, because the build sandbox couldn't reach
  OSM. After `make fetch`, commit `data/osm-alexandria.json` so builds stay reproducible.
- **The ward is invented on purpose.** It replaces whatever real streets lie under its
  footprint.
- **Period detail is styling, not history.** In the 18th century, only Old Town
  (the 1749 town) existed. Del Ray and St. Elmo date from 1894, and the Town of
  Potomac was incorporated in 1908 and annexed in 1930. Hence the title's "the late
  Town of Potomac".

## Notes on the original LLM write-up

The overall approach held up: Segno, the matrix as a fixed binary mask, and validate
then print then rescan. These corrections came out of building it:

- Segno escapes `\ ; : "` in Wi-Fi payloads but not commas, and that's fine: commas
  aren't delimiters in `WIFI:` strings. Use `T:WPA` for WPA2, WPA3-transition, and
  mixed networks. Use `SAE` only for WPA3-only networks, and test those phones.
- Decoders see only lightness, so hue is free. Texture added in GIMP afterwards can
  change lightness, so re-run `make validate` on the edited file.
- `cv2.QRCodeDetector.detectAndDecode` alone is a poor gate for artistic QR codes.
  It fails renders that phones read. Gate on ZXing and WeChat as well.
- Mask choice is free, and all eight masks are equally valid. Picking the one that
  best suits the art is a cheap win the write-up didn't mention.
- A short guest SSID and password lower the QR version, which gives a smaller, better
  hidden ward.

## Layout

```
qrmap/config.py      tunables (bbox, ward placement and size, legend, palette)
qrmap/geo.py         projection + GeoModel (blocks are faces of the street network)
qrmap/osm.py         Overpass fetch + OSM → GeoModel
qrmap/seed.py        hand-plotted fallback geography + place labels
qrmap/render_map.py  engraved map art
qrmap/ward.py        the hidden QR ward, legend cartouche, Wi-Fi mark
qrmap/district.py    ward placement and module <-> pixel transform (shared with validator)
qrmap/guard.py       module-centre safety pass
qrmap/qr.py          Wi-Fi payload, matrix, town-like mask choice
qrmap/frame.py       graduated neat line, title, scale, attribution
qrmap/validate.py    acceptance tests (exit code gates the build)
qrmap/build.py       CLI
fonts/               IM Fell English + Libre Caslon Text (SIL OFL) via @fontsource
```
