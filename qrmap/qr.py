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
    agreement: float  # mask-selection score (see make)

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


def blockiness(dark: np.ndarray, function: np.ndarray) -> float:
    """How town-like the data area is: the share of dark data modules with a dark
    neighbour to the right or below, so blocks join into streets of houses rather
    than scattered single cells."""
    d = dark & ~function
    pairs = (d[:, :-1] & d[:, 1:]).sum() + (d[:-1, :] & d[1:, :]).sum()
    return float(pairs / max(1, d.sum()))


def make(payload: str, version: int | None = None, error: str = "q", score=None) -> Code:
    """Build the symbol. With `score(dark, function) -> float`, try all eight masks and
    keep the highest-scoring one; every mask is equally valid to decoders."""
    base = segno.make_qr(payload, error=error, version=version, boost_error=False)
    best = None
    for mask in (range(8) if score else [base.mask]):
        q = segno.make_qr(payload, error=error, version=base.version, mask=mask, boost_error=False)
        dark, function, finder = _matrices(q)
        sc = score(dark, function) if score else 0.0
        if best is None or sc > best.agreement:
            best = Code(payload, base.version, base.error, mask, dark, function, finder, sc)
    return best
