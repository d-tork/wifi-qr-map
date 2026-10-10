"""Wi-Fi payload -> QR matrix (Segno), with the mask chosen to suit the artwork."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

import numpy as np
import segno
import segno.consts as C
from segno.helpers import make_wifi_data

DATA_TYPES = {C.TYPE_DATA_DARK, C.TYPE_DATA_LIGHT}
FINDER_TYPES = {C.TYPE_FINDER_PATTERN_DARK, C.TYPE_FINDER_PATTERN_LIGHT, C.TYPE_SEPARATOR}


@dataclass
class Code:
    payload: str
    version: int
    error: str
    mask: int
    dark: np.ndarray  # bool [n, n], True = dark module (no quiet zone)
    function: np.ndarray  # bool [n, n], finder/separator/timing/alignment/format/version
    finder: np.ndarray  # bool [n, n], finder patterns + separators
    agreement: float  # fraction of data modules whose tone matches the art

    @property
    def n(self) -> int:
        return self.dark.shape[0]

    @property
    def payload_sha256(self) -> str:
        return hashlib.sha256(self.payload.encode()).hexdigest()

    def segno(self):
        return segno.make_qr(self.payload, error=self.error, version=self.version,
                             mask=self.mask, boost_error=False)


def wifi_payload(ssid: str, password: str | None, security: str = "WPA", hidden: bool = False) -> str:
    """WIFI:T:<sec>;S:<ssid>;P:<pw>;H:true;; with \\ ; : " escaped (Segno does this)."""
    security = (security or "nopass").upper()
    if security in ("NONE", "OPEN", "NOPASS"):
        return make_wifi_data(ssid, None, "nopass", hidden)
    if security not in ("WPA", "WEP", "SAE", "WPA2", "WPA3"):
        raise ValueError(f"unsupported security type {security!r}")
    # WPA2/WPA3-personal phones accept T:WPA; SAE is the WPA3-only spelling.
    return make_wifi_data(ssid, password, "WPA" if security in ("WPA2", "WPA3") else security, hidden)


def _matrices(q):
    rows = [list(r) for r in q.matrix_iter(verbose=True, border=0)]
    types = np.array(rows)
    dark = np.array([list(r) for r in q.matrix], dtype=np.uint8).astype(bool)
    function = ~np.isin(types, list(DATA_TYPES))
    finder = np.isin(types, list(FINDER_TYPES))
    return dark, function, finder


def make(payload: str, version: int | None = None, error: str = "h",
         art_lightness: np.ndarray | None = None) -> Code:
    """Build the symbol. If `art_lightness` (callable n -> [n, n] array in 0..1) is
    given, try all eight masks and keep the one whose dark modules best coincide
    with dark areas of the artwork. All masks are equally valid to decoders."""
    base = segno.make_qr(payload, error=error, version=version, boost_error=False)
    best = None
    masks = range(8) if art_lightness is not None else [base.mask]
    for mask in masks:
        q = segno.make_qr(payload, error=error, version=base.version, mask=mask, boost_error=False)
        dark, function, finder = _matrices(q)
        agree = 0.0
        if art_lightness is not None:
            lum = art_lightness(dark.shape[0])
            data = ~function
            match = np.where(dark, lum < 0.5, lum >= 0.5)
            # Weight by how strongly the art leans one way, so near-grey cells don't vote.
            w = np.abs(lum - 0.5)[data]
            agree = float((match[data] * w).sum() / max(w.sum(), 1e-9))
        if best is None or agree > best.agreement:
            best = Code(payload, base.version, base.error, mask, dark, function, finder, agree)
    return best
