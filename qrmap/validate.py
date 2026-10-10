"""Programmatic acceptance test for a finished (or hand-edited) artwork.

    python -m qrmap.validate build/wifi-map.png [--manifest build/manifest.json]

Checks, in order:
  1. Print geometry: 12 x 12 in at the declared DPI (PNG pHYs and PDF MediaBox).
  2. Module fidelity: every module centre of the hidden ward, sampled from the image
     (following its rotation), binarises to the intended bit (zero errors allowed),
     with the light/dark contrast margin reported.
  3. Decoder battery: ZXing-C++ and three OpenCV detectors, at several capture sizes
     mostly close-ups of the ward under simulated phone conditions (perspective, blur,
     noise, JPEG, glare, low light). The decoded text must hash to the manifest's payload_sha256.
Exits non-zero if any gate fails, so it can sit at the end of a Makefile.
Decoded text is printed with the password masked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import zxingcpp
from PIL import Image

from .district import District

Image.MAX_IMAGE_PIXELS = None

# Gates.
MIN_CORE_CONTRAST = 60  # grey levels (0..255) between lightest dark core and darkest light core
STRESS_PASS_RATE = 0.80  # fraction of stressed captures ZXing must decode
CLEAN_DECODERS_REQUIRED = 2  # independent decoders that must read every clean capture


def mask_payload(text: str | None) -> str | None:
    if text is None:
        return None
    return re.sub(r"(P:)((?:\\.|[^;])*)", lambda m: m.group(1) + "*" * min(8, len(m.group(2))), text)


def gray(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


# --- decoders -------------------------------------------------------------------------

def _zxing(img):
    res = zxingcpp.read_barcodes(img, formats=zxingcpp.BarcodeFormat.QRCode)
    return res[0].text if res else None


def _cv(det):
    def run(img):
        try:
            text, pts, _ = det.detectAndDecode(img)
        except cv2.error:
            return None
        return text or None
    return run


def _wechat():
    det = cv2.wechat_qrcode_WeChatQRCode()

    def run(img):
        texts, _ = det.detectAndDecode(img)
        return texts[0] if texts else None
    return run


def decoders():
    out = {"zxing-cpp": _zxing, "opencv": _cv(cv2.QRCodeDetector())}
    if hasattr(cv2, "QRCodeDetectorAruco"):
        out["opencv-aruco"] = _cv(cv2.QRCodeDetectorAruco())
    if hasattr(cv2, "wechat_qrcode_WeChatQRCode"):
        out["opencv-wechat"] = _wechat()
    return out


# --- simulated captures ---------------------------------------------------------------

def resize(img, width):
    h = round(img.shape[0] * width / img.shape[1])
    return cv2.resize(img, (width, h), interpolation=cv2.INTER_AREA)


def perspective(img, amount, seed):
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    jitter = rng.uniform(-amount, amount, (4, 2)) * [w, h]
    dst = (src + jitter).astype(np.float32)
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, M, (w, h), borderValue=(200, 200, 200))


def rotate(img, deg):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(img, M, (w, h), borderValue=(200, 200, 200))


def jpeg(img, q):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)


def noise(img, sigma, seed):
    rng = np.random.default_rng(seed)
    return np.clip(img.astype(np.float32) + rng.normal(0, sigma, img.shape), 0, 255).astype(np.uint8)


def glare(img, strength=0.55):
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    g = np.exp(-(((xx - w * 0.68) ** 2 + (yy - h * 0.3) ** 2) / (2 * (0.22 * w) ** 2)))
    g = (g * strength)[..., None] if img.ndim == 3 else g * strength
    return np.clip(img * (1 - g) + 255 * g, 0, 255).astype(np.uint8)


def low_light(img):
    f = (img.astype(np.float32) / 255) ** 1.6 * 0.65
    return noise((f * 255).astype(np.uint8), 7, 3)


def captures(rgb: np.ndarray, dist: District):
    """(name, image, stressed?) as a phone might deliver them. The code is small on a
    12 in sheet, so most captures are close-ups framing the ward with some map round it,
    as a person holding a phone 15-30 cm away would."""
    x0, y0, x1, y1 = dist.bbox()
    pad = (x1 - x0) * 0.6
    cx0, cy0 = int(max(0, x0 - pad)), int(max(0, y0 - pad))
    close = rgb[cy0:int(y1 + pad), cx0:int(x1 + pad)]
    yield "sheet full-res", rgb, False
    yield "sheet 2400px", resize(rgb, 2400), False
    for w in (1400, 900, 600):
        yield f"close-up {w}px", resize(close, w), False
    base = resize(close, 900)
    yield "close-up rotated 17deg", rotate(base, 17), True
    yield "close-up perspective 6%", perspective(base, 0.06, 1), True
    yield "close-up perspective 10%", perspective(base, 0.10, 2), True
    yield "close-up blur sigma 1.5", cv2.GaussianBlur(base, (0, 0), 1.5), True
    yield "close-up blur sigma 2.5 @1400", cv2.GaussianBlur(resize(close, 1400), (0, 0), 2.5), True
    yield "close-up sensor noise", noise(base, 10, 4), True
    yield "close-up jpeg q35", jpeg(base, 35), True
    yield "close-up glare", glare(base), True
    yield "close-up low light", low_light(base), True
    yield "close-up small 400px", resize(close, 400), True
    yield "sheet 1500px (arm's length)", resize(rgb, 1500), True
    yield "combo: persp+blur+noise+jpeg", jpeg(noise(cv2.GaussianBlur(perspective(resize(close, 1100), 0.07, 5), (0, 0), 1.2), 6, 6), 60), True


# --- checks ---------------------------------------------------------------------------

def check_print(path: Path, manifest) -> dict:
    img = Image.open(path)
    dpi = manifest.get("dpi", 300)
    inches = manifest.get("inches", 12)
    inches = list(inches) if isinstance(inches, list) else [inches, inches]
    want = tuple(round(v * dpi) for v in inches)
    got_dpi = img.info.get("dpi", (None, None))
    ok = img.size == want and got_dpi[0] is not None and round(got_dpi[0]) == dpi
    res = {"pixels": img.size, "dpi": got_dpi, "inches": [s / dpi for s in img.size], "ok": ok}
    manifest_in = inches
    pdf = path.with_suffix(".pdf")
    if pdf.exists():
        m = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", pdf.read_bytes())
        inches = [float(m.group(1)) / 72, float(m.group(2)) / 72] if m else None
        want_in = [v for v in manifest_in]
        res["pdf_inches"] = inches
        res["ok"] = ok and inches is not None and all(abs(v - w) < 0.01 for v, w in zip(inches, want_in))
    return res


def _district(manifest) -> District:
    return District(**manifest["district"])


def check_modules(rgb: np.ndarray, manifest) -> dict:
    dist = _district(manifest)
    dark = np.array([[c == "1" for c in row] for row in manifest["matrix"]])
    function = np.array([[c == "1" for c in row] for row in manifest["function"]])
    n = dist.n
    gr = gray(rgb).astype(np.float32)
    # Sample a k x k lattice over the central 30% of each module (and over the whole
    # module), following the ward's rotation.
    k = 7
    core_off = (np.arange(k) + 0.5) / k * 0.3 + 0.35
    whole_off = (np.arange(k) + 0.5) / k

    def sample(r, c, offs):
        pts = [dist.to_px(c + du, r + dv) for dv in offs for du in offs]
        xs = np.clip(np.round([p[0] for p in pts]).astype(int), 0, gr.shape[1] - 1)
        ys = np.clip(np.round([p[1] for p in pts]).astype(int), 0, gr.shape[0] - 1)
        return gr[ys, xs].mean()

    cores = np.array([[sample(r, c, core_off) for c in range(n)] for r in range(n)])
    whole = np.array([[sample(r, c, whole_off) for c in range(n)] for r in range(n)])
    thr = (cores[dark].max() + cores[~dark].min()) / 2
    core_err = (cores < thr) != dark
    margin = float(cores[~dark].min() - cores[dark].max())
    # What a badly defocused camera would see: whole-module averages, Otsu threshold.
    t_whole, _ = cv2.threshold(whole.astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    whole_err = (whole < t_whole) != dark
    # Quiet zone: mean darkness of the ring, which should look like paper to a scanner.
    ring = [dist.to_px(u, v) for u in np.arange(-dist.quiet + .5, dist.n + dist.quiet, .5)
            for v in (-dist.quiet + .5, -.5, dist.n + .5, dist.n + dist.quiet - .5)]
    qz = np.mean([gr[int(y), int(x)] for x, y in ring])
    return {
        "modules": int(n * n),
        "module_inches": round(manifest.get("module_inches", 0), 4),
        "core_errors": int(core_err.sum()),
        "core_errors_in_function_patterns": int((core_err & function).sum()),
        "core_contrast_margin": round(margin, 1),
        "core_mean_dark": round(float(cores[dark].mean()), 1),
        "core_mean_light": round(float(cores[~dark].mean()), 1),
        "quiet_zone_mean": round(float(qz), 1),
        "defocus_module_errors_pct": round(100 * float(whole_err.mean()), 2),
        "ok": bool(core_err.sum() == 0 and margin >= MIN_CORE_CONTRAST),
        "_core_err": core_err,
    }


def check_decoders(rgb: np.ndarray, sha: str | None, dist: District) -> dict:
    decs = decoders()
    rows, clean_ok, stress = [], True, []
    for name, img, stressed in captures(rgb, dist):
        row = {"capture": name}
        hits = 0
        for dn, fn in decs.items():
            text = fn(img)
            good = text is not None and (sha is None or hashlib.sha256(text.encode()).hexdigest() == sha)
            row[dn] = good
            hits += good
            if text is not None:
                row["text"] = mask_payload(text)
        if stressed:
            stress.append(row["zxing-cpp"])
        elif hits < CLEAN_DECODERS_REQUIRED:
            clean_ok = False
        rows.append(row)
    rate = sum(stress) / max(1, len(stress))
    return {"decoders": list(decs), "captures": rows, "clean_ok": clean_ok,
            "zxing_stress_pass_rate": round(rate, 3), "ok": clean_ok and rate >= STRESS_PASS_RATE}


def error_overlay(rgb, manifest, core_err) -> np.ndarray:
    """Close-up of the ward: wrong modules boxed in red, quiet zone edge in blue."""
    dist = _district(manifest)
    out = rgb.copy()
    for r, c in zip(*np.nonzero(core_err)):
        pts = np.array(dist.square(c, r, c + 1, r + 1), np.int32)
        cv2.polylines(out, [pts], True, (220, 0, 0), max(2, dist.module // 6))
    cv2.polylines(out, [np.array(dist.reserve(), np.int32)], True, (0, 90, 200), 2)
    x0, y0, x1, y1 = (int(v) for v in dist.bbox(extra=dist.quiet))
    return out[max(0, y0):y1, max(0, x0):x1]


def validate(image: Path, manifest_path: Path | None = None, report: Path | None = None, quiet=False) -> bool:
    manifest_path = manifest_path or image.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    sheet = Image.open(image).convert("RGB")
    rgb = np.asarray(sheet)
    if "art_box" in manifest:  # the map sits inside a border; the ward is placed within it
        x, y, aw, ah = manifest["art_box"]
        art = sheet.crop((x, y, x + aw, y + ah))
        if (aw, ah) != tuple(manifest["render_px"]):
            art = art.resize(tuple(manifest["render_px"]), Image.LANCZOS)
        rgb = np.asarray(art)

    pr = check_print(image, manifest)
    mod = check_modules(rgb, manifest)
    dec = check_decoders(rgb, manifest.get("payload_sha256"), _district(manifest))
    core_err = mod.pop("_core_err")
    Image.fromarray(error_overlay(rgb, manifest, core_err)).save(image.with_name(image.stem + "-module-check.png"))

    ok = pr["ok"] and mod["ok"] and dec["ok"]
    result = {"image": str(image), "ok": ok, "print": pr, "modules": mod, "decode": dec}
    if report:
        report.write_text(json.dumps(result, indent=2, default=str))
    if not quiet:
        _print(result)
    return ok


def _print(r):
    p, m, d = r["print"], r["modules"], r["decode"]
    mark = lambda b: "PASS" if b else "FAIL"
    print(f"[{mark(p['ok'])}] print size   {p['pixels'][0]}x{p['pixels'][1]} px @ {p['dpi'][0]} dpi"
          f" = {p['inches'][0]:.2f} x {p['inches'][1]:.2f} in" + (f"; PDF {p['pdf_inches']}" if "pdf_inches" in p else ""))
    print(f"[{mark(m['ok'])}] modules      {m['core_errors']} centre errors of {m['modules']}"
          f" (function patterns: {m['core_errors_in_function_patterns']}); contrast margin {m['core_contrast_margin']}"
          f" (dark {m['core_mean_dark']} / light {m['core_mean_light']}, quiet zone {m['quiet_zone_mean']});"
          f" {m['module_inches']} in modules; defocus errors {m['defocus_module_errors_pct']}%")
    print(f"[{mark(d['ok'])}] decoding     ZXing stress pass rate {d['zxing_stress_pass_rate']:.0%};"
          f" every clean capture read by >= {CLEAN_DECODERS_REQUIRED} decoders: {d['clean_ok']}")
    names = d["decoders"]
    print("      " + "capture".ljust(34) + "".join(n.ljust(15) for n in names))
    for row in d["captures"]:
        print("      " + row["capture"].ljust(34) + "".join(("ok" if row[n] else "--").ljust(15) for n in names))
    text = next((row["text"] for row in d["captures"] if "text" in row), None)
    print(f"      decoded: {text}")
    print("RESULT:", "PASS" if r["ok"] else "FAIL")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("image", type=Path)
    ap.add_argument("--manifest", type=Path)
    ap.add_argument("--report", type=Path)
    a = ap.parse_args(argv)
    sys.exit(0 if validate(a.image, a.manifest, a.report or a.image.with_name("validation.json")) else 1)


if __name__ == "__main__":
    main()
