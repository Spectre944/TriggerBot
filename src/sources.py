"""
Источники кадров. Все отдают BGR uint8 (как wincam).

  ScreenSource  — реальный захват экрана через wincam (только Windows)
  DemoSource    — синтетическая движущаяся картинка (для запуска где угодно)
  StaticScene   — статическая картинка + подвижное окно (ROI) + цель-спрайт
                  для отладки детектора без игры
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np


# --------------------------------------------------------------------------- screen
class ScreenSource:
    def __init__(self, x: int, y: int, w: int, h: int, fps: int = 60):
        from . import ThreadedCapture
        if ThreadedCapture is None:
            raise RuntimeError("wincam недоступен (нужен Windows и `pip install wincam`)")
        self._cap = ThreadedCapture(x, y, w, h, fps=fps)
        self.size = (w, h)

    @staticmethod
    def available() -> bool:
        from . import ThreadedCapture
        return ThreadedCapture is not None

    def start(self) -> "ScreenSource":
        self._cap.start()
        return self

    def read(self) -> Optional[np.ndarray]:
        frame, _ts = self._cap.read_latest()
        return frame

    def stop(self) -> None:
        self._cap.stop()

    @property
    def stats(self) -> str:
        return f"захвачено {self._cap.captured}, выброшено {self._cap.dropped}"


# --------------------------------------------------------------------------- demo
class DemoSource:
    """Текстура + пара движущихся фигур. Нужен, чтобы GUI работал без Windows."""

    def __init__(self, w: int = 400, h: int = 300, fps: int = 60):
        self.size = (w, h)
        self._bg = make_background(w, h, seed=3)
        self._t0 = time.perf_counter()

    @staticmethod
    def available() -> bool:
        return True

    def start(self) -> "DemoSource":
        return self

    def read(self) -> Optional[np.ndarray]:
        w, h = self.size
        t = time.perf_counter() - self._t0
        frame = self._bg.copy()
        # шарик по кругу
        cx = int(w / 2 + math.cos(t * 1.3) * w * 0.3)
        cy = int(h / 2 + math.sin(t * 1.3) * h * 0.3)
        yy, xx = np.ogrid[:h, :w]
        frame[(xx - cx) ** 2 + (yy - cy) ** 2 < 18 ** 2] = (40, 60, 220)
        # прямоугольник туда-сюда
        rx = int((math.sin(t * 0.7) * 0.5 + 0.5) * (w - 40))
        frame[h - 70:h - 20, rx:rx + 40] = (230, 200, 40)
        return frame

    def stop(self) -> None:
        pass

    @property
    def stats(self) -> str:
        return "демо-источник"


# --------------------------------------------------------------------------- helpers
def make_background(w: int, h: int, seed: int = 1) -> np.ndarray:
    """Процедурная "игровая" сцена: небо, земля, ящики, шум текстуры."""
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), np.float32)
    horizon = int(h * 0.55)
    t = np.linspace(0, 1, horizon)[:, None]
    img[:horizon] = (np.array([200, 170, 120]) * (1 - t) + np.array([230, 215, 190]) * t)[:, None, :]
    g = np.linspace(0, 1, h - horizon)[:, None]
    img[horizon:] = (np.array([70, 105, 95]) * (1 - g) + np.array([45, 70, 65]) * g)[:, None, :]
    # ящики / стены
    for _ in range(max(3, w // 120)):
        bw, bh = rng.integers(w // 14, w // 5), rng.integers(h // 8, h // 3)
        bx = rng.integers(0, max(1, w - bw))
        by = horizon - bh + rng.integers(0, max(1, h // 10))
        color = rng.integers(60, 160, 3)
        img[by:by + bh, bx:bx + bw] = color
        img[by:by + bh, bx:bx + 3] = color * 0.6
        img[by:by + 3, bx:bx + bw] = color * 1.2
    img += rng.normal(0, 6, img.shape)  # текстура
    return np.clip(img, 0, 255).astype(np.uint8)


def make_target_sprite(h: int = 120) -> tuple[np.ndarray, np.ndarray]:
    """Тёмный силуэт человека: (BGR, alpha 0..1)."""
    w = int(h * 0.42)
    yy, xx = np.mgrid[:h, :w].astype(np.float32)
    cx = w / 2
    head_r = h * 0.11
    head = (xx - cx) ** 2 + (yy - head_r * 1.1) ** 2 <= head_r ** 2
    body = (np.abs(xx - cx) <= w * 0.32) & (yy >= h * 0.22) & (yy <= h * 0.62)
    legs = ((np.abs(xx - cx + w * 0.15) <= w * 0.12) | (np.abs(xx - cx - w * 0.15) <= w * 0.12)) \
        & (yy > h * 0.6)
    alpha = (head | body | legs).astype(np.float32)
    bgr = np.zeros((h, w, 3), np.uint8)
    bgr[:] = (40, 45, 60)
    bgr[body] = (35, 55, 50)
    return bgr, alpha


# --------------------------------------------------------------------------- static scene
@dataclass
class Sprite:
    bgr: np.ndarray
    alpha: np.ndarray   # HxW float32 0..1
    x: float = 0.0      # левый верхний угол в координатах сцены
    y: float = 0.0
    visible: bool = False

    @property
    def size(self) -> tuple[int, int]:
        return self.bgr.shape[1], self.bgr.shape[0]


class StaticScene:
    """
    Статическая картинка, по которой двигается окно захвата (ROI).
    Двигаем ROI — это имитация поворота камеры. Двигаем спрайт — имитация цели.
    """

    def __init__(self, background: np.ndarray, roi_w: int = 200, roi_h: int = 200):
        self.background = background
        self.roi_w, self.roi_h = roi_w, roi_h
        h, w = background.shape[:2]
        self.roi_x = float(max(0, (w - roi_w) // 2))
        self.roi_y = float(max(0, (h - roi_h) // 2))
        bgr, alpha = make_target_sprite(max(40, int(h * 0.18)))
        self.sprite = Sprite(bgr, alpha)
        self.noise = 0.0  # СКО гауссова шума (имитация сжатия/сглаживания)
        self._rng = np.random.default_rng()

    # -- geometry
    @property
    def size(self) -> tuple[int, int]:
        return self.background.shape[1], self.background.shape[0]

    def set_background(self, img: np.ndarray) -> None:
        self.background = img
        self.clamp_roi()

    def set_roi_size(self, w: int, h: int) -> None:
        bw, bh = self.size
        self.roi_w, self.roi_h = max(8, min(w, bw)), max(8, min(h, bh))
        self.clamp_roi()

    def move_roi(self, x: float, y: float) -> None:
        self.roi_x, self.roi_y = x, y
        self.clamp_roi()

    def clamp_roi(self) -> None:
        bw, bh = self.size
        self.roi_w, self.roi_h = min(self.roi_w, bw), min(self.roi_h, bh)
        self.roi_x = float(min(max(0.0, self.roi_x), bw - self.roi_w))
        self.roi_y = float(min(max(0.0, self.roi_y), bh - self.roi_h))

    @property
    def crosshair(self) -> tuple[float, float]:
        return self.roi_x + self.roi_w // 2, self.roi_y + self.roi_h // 2

    def set_sprite(self, bgr: np.ndarray, alpha: np.ndarray) -> None:
        sp = self.sprite
        self.sprite = Sprite(bgr, alpha.astype(np.float32), sp.x, sp.y, sp.visible)

    def sprite_covers(self, x: float, y: float) -> bool:
        """Попадает ли точка сцены (x, y) в непрозрачную часть цели."""
        sp = self.sprite
        if not sp.visible:
            return False
        lx, ly = int(round(x - sp.x)), int(round(y - sp.y))
        sw, sh = sp.size
        return bool(0 <= lx < sw and 0 <= ly < sh and sp.alpha[ly, lx] > 0.5)

    # -- render
    def render_roi(self) -> np.ndarray:
        x0, y0 = int(round(self.roi_x)), int(round(self.roi_y))
        x1, y1 = x0 + self.roi_w, y0 + self.roi_h
        out = self.background[y0:y1, x0:x1].copy()

        sp = self.sprite
        if sp.visible:
            sw, sh = sp.size
            sx, sy = int(round(sp.x)), int(round(sp.y))
            ix0, iy0 = max(x0, sx), max(y0, sy)
            ix1, iy1 = min(x1, sx + sw), min(y1, sy + sh)
            if ix0 < ix1 and iy0 < iy1:
                a = sp.alpha[iy0 - sy:iy1 - sy, ix0 - sx:ix1 - sx, None]
                src = sp.bgr[iy0 - sy:iy1 - sy, ix0 - sx:ix1 - sx].astype(np.float32)
                dst = out[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0].astype(np.float32)
                out[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0] = (src * a + dst * (1 - a)).astype(np.uint8)

        if self.noise > 0:
            n = self._rng.normal(0, self.noise, out.shape)
            out = np.clip(out.astype(np.float32) + n, 0, 255).astype(np.uint8)
        return out
