"""Guard pass: make sure every module centre reads as the bit it encodes.

The ward is drawn as clean blocks, so this normally changes nothing. It exists so
that tuning (paler wash, sparser hatching, lot lines, a rotated ward) can never
silently push a module across the threshold: any centre whose mean CIE L* falls on
the wrong side of CORE_DARK / CORE_LIGHT is pulled back with a feathered patch.
"""

from __future__ import annotations

import cv2
import numpy as np

from . import config
from .district import District
from .qr import Code


def guard(rgb: np.ndarray, code: Code, dist: District) -> tuple[np.ndarray, int]:
    lab = cv2.cvtColor(rgb.astype(np.float32), cv2.COLOR_RGB2Lab)
    L = lab[..., 0]
    m = dist.module
    half = max(1.0, config.CORE_FRACTION * m / 2)
    R = int(np.ceil(half * 1.6))
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1].astype(np.float32)
    fixed = 0
    for r in range(code.n):
        for c in range(code.n):
            x, y = dist.center(r, c)
            xi, yi = int(round(x)), int(round(y))
            patch = L[yi - R:yi + R + 1, xi - R:xi + R + 1]
            dx, dy = xx + (xi - x), yy + (yi - y)
            core = (np.abs(dx) <= half) & (np.abs(dy) <= half)
            mean = float(patch[core].mean())
            if code.dark[r, c] and mean > config.CORE_DARK:
                target = patch * (config.CORE_DARK / mean)
            elif not code.dark[r, c] and mean < config.CORE_LIGHT:
                target = 100 - (100 - patch) * ((100 - config.CORE_LIGHT) / max(100 - mean, 1e-3))
            else:
                continue
            w = np.clip(half * 1.5 - np.maximum(np.abs(dx), np.abs(dy)), 0, 1)
            patch += w * (target - patch)
            fixed += 1
    return np.clip(cv2.cvtColor(lab, cv2.COLOR_Lab2RGB), 0, 1), fixed
