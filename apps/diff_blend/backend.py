from __future__ import annotations

import time
from collections import deque

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal, Slot

from src.processing import difference_blend
from src.qt_props import ro_property, rw_property
from src.qt_utils import FrameProvider
from src.sources import DemoSource, ScreenSource


class DiffBlendBackend(QObject):
    settingsChanged = Signal()
    frameChanged = Signal()
    statusChanged = Signal()

    def __init__(self, provider: FrameProvider, parent=None):
        super().__init__(parent)
        self.provider = provider

        # --- настройки (их меняет QML)
        self._source_kind = "screen" if ScreenSource.available() else "demo"
        self._rx, self._ry, self._rw, self._rh = 0, 0, 400, 300
        self._capture_fps = 60
        self._gain = 4.0
        self._threshold = 8
        self._binary = False
        self._mode = "prev"          # "prev" — с предыдущим кадром, "ref" — с опорным снимком
        self._update_rate = 1        # каждый N-й предыдущий кадр (1 = соседние кадры)

        # --- состояние
        self._running = False
        self._frame_id = 0
        self._fps = 0.0
        self._changed_pct = 0.0
        self._max_diff = 0
        self._status = ""
        self._has_reference = False

        self._source = None
        self._history: deque[np.ndarray] = deque(maxlen=16)
        self._reference: np.ndarray | None = None
        self._times: deque[float] = deque(maxlen=60)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    # ------------------------------------------------------------ properties
    sourceKind = rw_property(str, "_source_kind", settingsChanged, "settingsChanged")
    regionX = rw_property(int, "_rx", settingsChanged, "settingsChanged")
    regionY = rw_property(int, "_ry", settingsChanged, "settingsChanged")
    regionW = rw_property(int, "_rw", settingsChanged, "settingsChanged")
    regionH = rw_property(int, "_rh", settingsChanged, "settingsChanged")
    captureFps = rw_property(int, "_capture_fps", settingsChanged, "settingsChanged")
    gain = rw_property(float, "_gain", settingsChanged, "settingsChanged")
    threshold = rw_property(int, "_threshold", settingsChanged, "settingsChanged")
    binary = rw_property(bool, "_binary", settingsChanged, "settingsChanged")
    mode = rw_property(str, "_mode", settingsChanged, "settingsChanged")
    frameStep = rw_property(int, "_update_rate", settingsChanged, "settingsChanged")

    running = ro_property(bool, "_running", statusChanged)
    hasReference = ro_property(bool, "_has_reference", statusChanged)
    status = ro_property(str, "_status", statusChanged)
    frameId = ro_property(int, "_frame_id", frameChanged)
    fps = ro_property(float, "_fps", frameChanged)
    changedPct = ro_property(float, "_changed_pct", frameChanged)
    maxDiff = ro_property(int, "_max_diff", frameChanged)

    @Slot(result=bool)
    def screenAvailable(self) -> bool:
        return ScreenSource.available()

    # ------------------------------------------------------------ control
    @Slot()
    def start(self) -> None:
        self.stop()
        w, h = max(8, self._rw), max(8, self._rh)
        try:
            if self._source_kind == "screen":
                self._source = ScreenSource(self._rx, self._ry, w, h, fps=self._capture_fps).start()
            else:
                self._source = DemoSource(w, h).start()
        except Exception as e:  # noqa: BLE001
            self._set_status(f"Ошибка запуска: {e}")
            return
        self._history.clear()
        self._reference = None
        self._has_reference = False
        self._times.clear()
        self._running = True
        # demo генерирует кадр на каждый опрос -> ограничиваем частотой; screen опрашиваем чаще
        interval = int(1000 / max(1, self._capture_fps)) if self._source_kind == "demo" else 2
        self._timer.start(interval)
        self._set_status(f"Источник: {self._source_kind}, {w}x{h}")

    @Slot()
    def stop(self) -> None:
        self._timer.stop()
        if self._source is not None:
            self._source.stop()
            self._source = None
        if self._running:
            self._running = False
            self._set_status("Остановлено")

    @Slot()
    def snapshotReference(self) -> None:
        if self._history:
            self._reference = self._history[-1].copy()
            self._has_reference = True
            self.statusChanged.emit()

    # ------------------------------------------------------------ loop
    def _poll(self) -> None:
        if self._source is None:
            return
        frame = self._source.read()
        if frame is None:
            return
        frame = frame[..., :3]

        now = time.perf_counter()
        self._times.append(now)
        if len(self._times) > 1:
            self._fps = (len(self._times) - 1) / (self._times[-1] - self._times[0])

        if self._mode == "ref" and self._reference is not None \
                and self._reference.shape == frame.shape:
            ref = self._reference
        elif len(self._history) >= self._update_rate:
            ref = self._history[-self._update_rate]
        else:
            ref = frame
        self._history.append(frame)

        res = difference_blend(frame, ref, gain=self._gain, threshold=self._threshold,
                               binary=self._binary)
        self._changed_pct = res.changed_ratio * 100
        self._max_diff = res.max_diff

        self.provider.set("live", frame)
        self.provider.set("diff", res.image)
        self._frame_id += 1
        self.frameChanged.emit()

    def _set_status(self, text: str) -> None:
        self._status = text
        self.statusChanged.emit()
