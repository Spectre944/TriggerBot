"""
Детектор движения в центральной зоне (под прицелом).

Идея:
  1. Кадр -> яркость -> (опционально) уменьшение в N раз (сглаживает шум).
  2. |текущий - предыдущий| > порог_пикселя  ->  маска изменённых пикселей.
  3. Зона  = квадрат (2r+1)x(2r+1) в центре кадра.
     Кольцо = всё остальное в кадре.
  4. Если в зоне изменилось >= min_area пикселей — это движение под прицелом.
     Если же сильно изменилось и кольцо — скорее всего двигается камера
     (игрок водит мышкой), а не цель; такой кадр можно подавлять.
  5. Машина состояний: подтверждение N кадров -> задержка -> срабатывание -> кулдаун.

Время передаётся снаружи (now_ms), поэтому детектор легко тестировать.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from .diff_blend import to_gray


class MotionState(str, enum.Enum):
    IDLE = "idle"            # ждём движения
    ARMING = "arming"        # движение есть, набираем confirm_frames
    PENDING = "pending"      # подтверждено, ждём fire_delay_ms
    COOLDOWN = "cooldown"    # только что сработали, игнорируем
    WAIT_CALM = "wait_calm"  # ждём, пока зона успокоится (rearm_on_calm)


@dataclass
class MotionConfig:
    sensitivity: float = 60.0         # 0..100, выше = реагирует на более слабые изменения
    zone_radius: int = 6              # полуразмер центральной зоны, px исходного кадра
    min_area: float = 0.15            # доля пикселей зоны, которые должны измениться (0..1)
    confirm_frames: int = 1           # сколько кадров подряд должно быть движение
    fire_delay_ms: float = 0.0        # задержка между подтверждением и срабатыванием
    cooldown_ms: float = 250.0        # пауза после срабатывания
    rearm_on_calm: bool = True        # после кулдауна ждать, пока зона станет спокойной
    compensate_camera: bool = True    # искать сдвиг камеры (фазовая корреляция) и вычитать его
    max_camera_shift: int = 32        # макс. сдвиг камеры за кадр, px исходного кадра
    ignore_camera_motion: bool = True # подавлять кадр, если после компенсации меняется весь кадр
    camera_limit: float = 0.30        # доля изменившихся пикселей кольца = "двигается камера"
    downscale: int = 1                # 1/2/4 — усреднение блоков, гасит шум

    @property
    def pixel_threshold(self) -> int:
        """Порог изменения яркости пикселя: чувств. 100 -> 4, чувств. 0 -> 84."""
        s = min(max(self.sensitivity, 0.0), 100.0)
        return int(round(4 + (100.0 - s) * 0.8))


@dataclass
class MotionResult:
    state: MotionState
    motion: bool                 # движение в зоне на этом кадре (после фильтра камеры)
    camera_motion: bool          # кадр признан движением камеры
    fired: bool                  # сработали именно на этом кадре
    zone_ratio: float
    ring_ratio: float
    mask: Optional[np.ndarray]   # bool HxW (в масштабе downscale) — для отладки
    diff: Optional[np.ndarray]   # int16 HxW — для отладки
    zone_box: tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h в масштабе маски
    camera_shift: tuple[int, int] = (0, 0)               # найденный сдвиг камеры, px исходного кадра


@dataclass
class MotionStats:
    frames: int = 0
    motion_frames: int = 0
    camera_frames: int = 0
    triggers: int = 0
    last_trigger_ms: Optional[float] = None
    trigger_times_ms: list[float] = field(default_factory=list)


_window_cache: dict[tuple[int, int], np.ndarray] = {}


def estimate_shift_candidates(prev: np.ndarray, cur: np.ndarray, max_shift: int,
                              top_k: int = 3) -> list[tuple[int, int]]:
    """
    Кандидаты глобального сдвига кадра (камеры) по фазовой корреляции, лучшие первыми.
    Сдвиг (dx, dy) означает: cur[y, x] ≈ prev[y - dy, x - dx].
    """
    h, w = cur.shape
    win = _window_cache.get((h, w))
    if win is None:
        win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
        _window_cache[(h, w)] = win
    a = (prev - prev.mean()) * win
    b = (cur - cur.mean()) * win
    fa, fb = np.fft.rfft2(a), np.fft.rfft2(b)
    r = fb * np.conj(fa)
    r /= np.abs(r) + 1e-6
    corr = np.fft.irfft2(r, s=(h, w))
    # ограничиваем поиск окном ±max_shift
    m = max_shift
    corr = np.roll(np.roll(corr, m, axis=0), m, axis=1)[: 2 * m + 1, : 2 * m + 1]
    flat = corr.ravel()
    k = min(top_k, flat.size)
    idx = np.argpartition(flat, -k)[-k:]
    idx = idx[np.argsort(flat[idx])[::-1]]
    out = []
    for i in idx:
        iy, ix = divmod(int(i), corr.shape[1])
        out.append((ix - m, iy - m))
    return out


def _aligned_diff(prev: np.ndarray, cur: np.ndarray, dx: int, dy: int) -> tuple[np.ndarray, np.ndarray]:
    """|cur - shift(prev)|; там, где после сдвига нет данных, valid=False."""
    h, w = cur.shape
    diff = np.zeros_like(cur)
    valid = np.zeros(cur.shape, bool)
    ys, ye = max(0, dy), min(h, h + dy)
    xs, xe = max(0, dx), min(w, w + dx)
    if ys < ye and xs < xe:
        diff[ys:ye, xs:xe] = np.abs(cur[ys:ye, xs:xe] - prev[ys - dy:ye - dy, xs - dx:xe - dx])
        valid[ys:ye, xs:xe] = True
    return diff, valid


def _downscale(gray: np.ndarray, k: int) -> np.ndarray:
    if k <= 1:
        return gray
    h, w = gray.shape
    h2, w2 = h // k, w // k
    g = gray[: h2 * k, : w2 * k].reshape(h2, k, w2, k)
    return g.mean(axis=(1, 3)).astype(np.int16)


class MotionDetector:
    def __init__(self, config: Optional[MotionConfig] = None,
                 on_fire: Optional[Callable[[float], None]] = None):
        self.config = config or MotionConfig()
        self.on_fire = on_fire
        self.stats = MotionStats()
        self._prev: Optional[np.ndarray] = None
        self._state = MotionState.IDLE
        self._streak = 0
        self._fire_at = 0.0
        self._cooldown_until = 0.0
        self._last_shift = (0, 0)

    # ------------------------------------------------------------------ API
    @property
    def state(self) -> MotionState:
        return self._state

    def reset(self, keep_stats: bool = False) -> None:
        self._prev = None
        self._state = MotionState.IDLE
        self._streak = 0
        self._last_shift = (0, 0)
        if not keep_stats:
            self.stats = MotionStats()

    def process(self, frame: np.ndarray, now_ms: float) -> MotionResult:
        cfg = self.config
        k = max(1, int(cfg.downscale))
        gray = _downscale(to_gray(frame), k)

        if self._prev is None or self._prev.shape != gray.shape:
            self._prev = gray
            return MotionResult(self._state, False, False, False, 0.0, 0.0, None, None)

        prev = self._prev
        self._prev = gray

        dx = dy = 0
        valid = None
        diff = np.abs(gray - prev)
        if cfg.compensate_camera:
            # Кандидаты: пики фазовой корреляции + "камера стоит" + сдвиг с прошлого кадра.
            # Пик корреляции может принадлежать самой цели (особенно на однотонном фоне),
            # а камера — это то, что объясняет БОЛЬШИНСТВО пикселей. Поэтому из кандидатов
            # выбираем тот, у которого медианная разница после выравнивания минимальна.
            m = max(1, min(int(cfg.max_camera_shift) // k, min(gray.shape) // 3))
            cands = estimate_shift_candidates(prev, gray, m)
            cands.append(self._last_shift)
            best = float(np.median(diff[::3, ::3]))
            seen = {(0, 0)}
            for c in cands:
                if c in seen or abs(c[0]) > m or abs(c[1]) > m:
                    continue
                seen.add(c)
                d_sh, v_sh = _aligned_diff(prev, gray, c[0], c[1])
                med = float(np.median(d_sh[v_sh][::3]))
                if med < best:
                    best, (dx, dy), diff, valid = med, c, d_sh, v_sh
        self._last_shift = (dx, dy)
        mask = diff > cfg.pixel_threshold

        h, w = mask.shape
        r = max(0, int(cfg.zone_radius) // k)
        cy, cx = h // 2, w // 2
        y0, y1 = max(0, cy - r), min(h, cy + r + 1)
        x0, x1 = max(0, cx - r), min(w, cx + r + 1)
        zone = mask[y0:y1, x0:x1]

        zone_changed = int(zone.sum())
        if valid is not None:
            zone_size = int(valid[y0:y1, x0:x1].sum())
            ring_size = int(valid.sum()) - zone_size
        else:
            zone_size = zone.size
            ring_size = mask.size - zone_size
        total_changed = int(mask.sum())

        zone_ratio = zone_changed / zone_size if zone_size else 0.0
        ring_ratio = (total_changed - zone_changed) / ring_size if ring_size > 0 else 0.0

        camera = cfg.ignore_camera_motion and ring_ratio > cfg.camera_limit
        raw_motion = zone_ratio >= cfg.min_area and zone_changed > 0
        motion = raw_motion and not camera

        self.stats.frames += 1
        if motion:
            self.stats.motion_frames += 1
        if camera:
            self.stats.camera_frames += 1

        fired = self._step(motion, raw_motion, now_ms)

        return MotionResult(
            state=self._state,
            motion=motion,
            camera_motion=camera,
            fired=fired,
            zone_ratio=zone_ratio,
            ring_ratio=ring_ratio,
            mask=mask,
            diff=diff,
            zone_box=(x0, y0, x1 - x0, y1 - y0),
            camera_shift=(dx * k, dy * k),
        )

    def tick(self, now_ms: float) -> bool:
        """Можно звать между кадрами, чтобы отложенный выстрел не ждал следующего кадра."""
        if self._state == MotionState.PENDING and now_ms >= self._fire_at:
            self._fire(now_ms)
            return True
        return False

    # --------------------------------------------------------- state machine
    def _step(self, motion: bool, raw_motion: bool, now: float) -> bool:
        cfg = self.config
        st = self._state

        if st == MotionState.COOLDOWN:
            if now < self._cooldown_until:
                return False
            st = self._state = MotionState.WAIT_CALM if cfg.rearm_on_calm else MotionState.IDLE

        if st == MotionState.WAIT_CALM:
            if raw_motion:
                return False
            self._state = MotionState.IDLE
            return False

        if st == MotionState.PENDING:
            if now >= self._fire_at:
                self._fire(now)
                return True
            return False

        # IDLE / ARMING
        if not motion:
            self._streak = 0
            self._state = MotionState.IDLE
            return False

        self._streak += 1
        if self._streak < max(1, cfg.confirm_frames):
            self._state = MotionState.ARMING
            return False

        self._streak = 0
        if cfg.fire_delay_ms > 0:
            self._fire_at = now + cfg.fire_delay_ms
            self._state = MotionState.PENDING
            return False

        self._fire(now)
        return True

    def _fire(self, now: float) -> None:
        self.stats.triggers += 1
        self.stats.last_trigger_ms = now
        self.stats.trigger_times_ms.append(now)
        if len(self.stats.trigger_times_ms) > 200:
            del self.stats.trigger_times_ms[:-200]
        self._cooldown_until = now + self.config.cooldown_ms
        self._state = MotionState.COOLDOWN
        if self.on_fire:
            self.on_fire(now)
