"""
Difference Blend — как режим смешивания "Difference" в Photoshop:
    out = |A - B|   (поканально)

Чистый numpy, без Qt, чтобы можно было использовать и в GUI, и в бенчмарках.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def to_gray(frame: np.ndarray) -> np.ndarray:
    """BGR uint8 -> яркость int16 (целочисленная аппроксимация BT.601)."""
    if frame.ndim == 2:
        return frame.astype(np.int16)
    b = frame[..., 0].astype(np.uint16)
    g = frame[..., 1].astype(np.uint16)
    r = frame[..., 2].astype(np.uint16)
    return ((b * 29 + g * 150 + r * 77) >> 8).astype(np.int16)


@dataclass
class DiffBlendResult:
    image: np.ndarray        # BGR uint8 — то, что показываем
    changed_ratio: float     # доля пикселей, у которых разница > threshold
    max_diff: int            # максимальная разница по кадру


def difference_blend(
    current: np.ndarray,
    reference: np.ndarray,
    gain: float = 1.0,
    threshold: int = 0,
    binary: bool = False,
) -> DiffBlendResult:
    """
    current, reference — BGR uint8 одинакового размера.
    gain      — усиление разницы (слабые изменения становятся видны).
    threshold — разница <= threshold считается шумом и зануляется.
    binary    — вместо градаций показывать маску (белое = изменилось).
    """
    if current.shape != reference.shape:
        raise ValueError(f"Размеры кадров не совпадают: {current.shape} vs {reference.shape}")

    diff = np.abs(current.astype(np.int16) - reference.astype(np.int16))  # HxWx3
    per_pixel = diff.max(axis=2) if diff.ndim == 3 else diff               # HxW
    mask = per_pixel > threshold

    if binary:
        out = np.where(mask, 255, 0).astype(np.uint8)
        out = np.repeat(out[..., None], 3, axis=2)
    else:
        if threshold > 0:
            diff = diff * mask[..., None]
        if gain != 1.0:
            diff = diff.astype(np.float32) * gain
        out = np.clip(diff, 0, 255).astype(np.uint8)

    return DiffBlendResult(
        image=out,
        changed_ratio=float(mask.mean()),
        max_diff=int(per_pixel.max()) if per_pixel.size else 0,
    )
