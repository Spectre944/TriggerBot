"""Мост numpy <-> Qt: конвертация кадров и провайдер картинок для QML."""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider


def bgr_to_qimage(frame: np.ndarray) -> QImage:
    if frame.ndim == 2:
        frame = np.ascontiguousarray(frame.astype(np.uint8))
        h, w = frame.shape
        return QImage(frame.data, w, h, w, QImage.Format_Grayscale8).copy()
    if frame.shape[2] == 4:  # BGRA (так ARGB32 лежит в памяти на little-endian)
        frame = np.ascontiguousarray(frame)
        h, w = frame.shape[:2]
        return QImage(frame.data, w, h, 4 * w, QImage.Format_ARGB32).copy()
    frame = np.ascontiguousarray(frame[..., :3])
    h, w = frame.shape[:2]
    return QImage(frame.data, w, h, 3 * w, QImage.Format_BGR888).copy()


def qimage_to_bgr(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_BGR888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    arr = np.frombuffer(img.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)
    return arr[:, : w * 3].reshape(h, w, 3).copy()


def load_bgra(path: str | Path, height: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """PNG с прозрачностью -> (BGR uint8, alpha float32 0..1)."""
    img = QImage(str(path))
    if img.isNull():
        raise ValueError(f"Не удалось открыть изображение: {path}")
    if height:
        img = img.scaledToHeight(int(height), Qt.SmoothTransformation)
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    arr = np.frombuffer(img.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)[:, : w * 4]
    arr = arr.reshape(h, w, 4)
    return arr[..., :3].copy(), arr[..., 3].astype(np.float32) / 255.0


def load_bgr(path: str | Path) -> np.ndarray:
    img = QImage(str(path))
    if img.isNull():
        raise ValueError(f"Не удалось открыть изображение: {path}")
    return qimage_to_bgr(img)


class FrameProvider(QQuickImageProvider):
    """
    QML: Image { source: "image://<name>/<key>/" + backend.frameId; cache: false }
    Python: provider.set("<key>", numpy_bgr)
    """

    def __init__(self):
        super().__init__(QQuickImageProvider.Image)
        self._images: dict[str, QImage] = {}
        self._lock = threading.Lock()

    def set(self, key: str, frame: np.ndarray) -> None:
        img = bgr_to_qimage(frame)
        with self._lock:
            self._images[key] = img

    def requestImage(self, id_: str, size: QSize, requested: QSize) -> QImage:  # noqa: N802
        key = id_.split("/", 1)[0]
        with self._lock:
            img = self._images.get(key)
        if img is None:
            img = QImage(1, 1, QImage.Format_RGB888)
            img.fill(0)
        if size is not None:
            size.setWidth(img.width())
            size.setHeight(img.height())
        return img


def upscale_nearest(img: np.ndarray, k: int) -> np.ndarray:
    if k <= 1:
        return img
    return np.repeat(np.repeat(img, k, axis=0), k, axis=1)
