from __future__ import annotations

import math
import time
from collections import deque

import numpy as np
from PySide6.QtCore import Property as _P
from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot

from src.processing import MotionConfig, MotionDetector, MotionState
from src.qt_props import ro_property, rw_property
from src.qt_utils import FrameProvider, load_bgr, load_bgra, upscale_nearest
from src.sources import StaticScene, make_background, make_target_sprite

STATE_RU = {
    MotionState.IDLE: "ожидание",
    MotionState.ARMING: "подтверждение",
    MotionState.PENDING: "задержка",
    MotionState.COOLDOWN: "кулдаун",
    MotionState.WAIT_CALM: "ждём покоя",
}


class MotionLabBackend(QObject):
    sceneChanged = Signal()      # фон / размеры / спрайт
    geometryChanged = Signal()   # положение ROI и цели (каждый кадр)
    configChanged = Signal()     # параметры детектора и симуляции
    frameChanged = Signal()      # статистика кадра
    fired = Signal(bool)         # выстрел (True = попадание)

    def __init__(self, provider: FrameProvider, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.scene = StaticScene(make_background(1280, 720, seed=7), 240, 240)
        self._custom_sprite_path: str | None = None

        # ---- детектор
        d = MotionConfig()
        self._sensitivity = d.sensitivity
        self._zone_radius = d.zone_radius
        self._min_area = d.min_area
        self._confirm_frames = d.confirm_frames
        self._fire_delay = d.fire_delay_ms
        self._cooldown = d.cooldown_ms
        self._rearm_on_calm = d.rearm_on_calm
        self._compensate = d.compensate_camera
        self._ignore_camera = d.ignore_camera_motion
        self._camera_limit = d.camera_limit
        self._downscale = d.downscale
        self.detector = MotionDetector(d)

        # ---- симуляция
        self._lab_fps = 60
        self._noise = 0.0
        self._target_speed = 400.0     # px/с
        self._target_height = self.scene.sprite.size[1]
        self._target_offset_y = 0      # смещение траектории цели относительно прицела, px
        self._auto_pass = False
        self._pass_pause = 400         # мс между проходами
        self._sway_amp = 0             # покачивание камеры, px
        self._sway_hz = 0.5
        self._paused = False

        # ---- состояние прохода цели
        self._pass_active = False
        self._pass_dir = 1
        self._pass_end_x = 0.0
        self._next_pass_at = 0.0
        self._pass_shots = 0
        self._anchor_x, self._anchor_y = self.scene.roi_x, self.scene.roi_y

        # ---- статистика
        self._t0 = time.perf_counter()
        self._frame_id = 0
        self._bg_id = 1
        self._sprite_id = 1
        self._zone_pct = 0.0
        self._ring_pct = 0.0
        self._state = STATE_RU[MotionState.IDLE]
        self._motion = False
        self._camera = False
        self._shift_x = 0
        self._shift_y = 0
        self._hits = 0
        self._misses = 0
        self._passes = 0
        self._passes_hit = 0
        self._extra_shots = 0
        self._fps = 0.0
        self._proc_ms = 0.0
        self._log: deque[str] = deque(maxlen=14)
        self._shots: deque[dict] = deque(maxlen=40)
        self._times: deque[float] = deque(maxlen=60)

        self._publish_scene()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(int(1000 / self._lab_fps))

    # =============================================================== properties
    # --- детектор (изменение сразу уходит в конфиг)
    sensitivity = rw_property(float, "_sensitivity", configChanged, "configChanged", "_sync_config")
    zoneRadius = rw_property(int, "_zone_radius", configChanged, "configChanged", "_sync_config")
    minArea = rw_property(float, "_min_area", configChanged, "configChanged", "_sync_config")
    confirmFrames = rw_property(int, "_confirm_frames", configChanged, "configChanged", "_sync_config")
    fireDelayMs = rw_property(float, "_fire_delay", configChanged, "configChanged", "_sync_config")
    cooldownMs = rw_property(float, "_cooldown", configChanged, "configChanged", "_sync_config")
    rearmOnCalm = rw_property(bool, "_rearm_on_calm", configChanged, "configChanged", "_sync_config")
    compensateCamera = rw_property(bool, "_compensate", configChanged, "configChanged", "_sync_config")
    ignoreCamera = rw_property(bool, "_ignore_camera", configChanged, "configChanged", "_sync_config")
    cameraLimit = rw_property(float, "_camera_limit", configChanged, "configChanged", "_sync_config")
    downscale = rw_property(int, "_downscale", configChanged, "configChanged", "_sync_config")

    # --- симуляция
    labFps = rw_property(int, "_lab_fps", configChanged, "configChanged", "_restart_timer")
    noise = rw_property(float, "_noise", configChanged, "configChanged")
    targetSpeed = rw_property(float, "_target_speed", configChanged, "configChanged")
    targetHeight = rw_property(int, "_target_height", configChanged, "configChanged", "_rebuild_sprite")
    targetOffsetY = rw_property(int, "_target_offset_y", configChanged, "configChanged")
    autoPass = rw_property(bool, "_auto_pass", configChanged, "configChanged")
    passPauseMs = rw_property(int, "_pass_pause", configChanged, "configChanged")
    swayAmp = rw_property(int, "_sway_amp", configChanged, "configChanged")
    swayHz = rw_property(float, "_sway_hz", configChanged, "configChanged")
    paused = rw_property(bool, "_paused", configChanged, "configChanged")

    # --- сцена
    bgId = ro_property(int, "_bg_id", sceneChanged)
    spriteId = ro_property(int, "_sprite_id", sceneChanged)

    def _scene_w(self): return self.scene.size[0]
    def _scene_h(self): return self.scene.size[1]
    def _roi_w(self): return self.scene.roi_w
    def _roi_h(self): return self.scene.roi_h
    def _sprite_w(self): return self.scene.sprite.size[0]
    def _sprite_h(self): return self.scene.sprite.size[1]

    sceneW = _P(int, _scene_w, notify=sceneChanged)
    sceneH = _P(int, _scene_h, notify=sceneChanged)
    roiW = _P(int, _roi_w, notify=sceneChanged)
    roiH = _P(int, _roi_h, notify=sceneChanged)
    spriteW = _P(int, _sprite_w, notify=sceneChanged)
    spriteH = _P(int, _sprite_h, notify=sceneChanged)

    roiX = _P(float, lambda s: s.scene.roi_x, notify=geometryChanged)
    roiY = _P(float, lambda s: s.scene.roi_y, notify=geometryChanged)
    spriteX = _P(float, lambda s: s.scene.sprite.x, notify=geometryChanged)
    spriteY = _P(float, lambda s: s.scene.sprite.y, notify=geometryChanged)
    spriteVisible = _P(bool, lambda s: s.scene.sprite.visible, notify=geometryChanged)
    passActive = _P(bool, lambda s: s._pass_active, notify=geometryChanged)
    pixelThreshold = _P(int, lambda s: s.detector.config.pixel_threshold, notify=configChanged)

    # --- статистика
    frameId = ro_property(int, "_frame_id", frameChanged)
    zonePct = ro_property(float, "_zone_pct", frameChanged)
    ringPct = ro_property(float, "_ring_pct", frameChanged)
    stateName = ro_property(str, "_state", frameChanged)
    motion = ro_property(bool, "_motion", frameChanged)
    cameraMotion = ro_property(bool, "_camera", frameChanged)
    shiftX = ro_property(int, "_shift_x", frameChanged)
    shiftY = ro_property(int, "_shift_y", frameChanged)
    fps = ro_property(float, "_fps", frameChanged)
    procMs = ro_property(float, "_proc_ms", frameChanged)
    hits = ro_property(int, "_hits", frameChanged)
    misses = ro_property(int, "_misses", frameChanged)
    passes = ro_property(int, "_passes", frameChanged)
    passesHit = ro_property(int, "_passes_hit", frameChanged)
    extraShots = ro_property(int, "_extra_shots", frameChanged)
    triggers = _P(int, lambda s: s.detector.stats.triggers, notify=frameChanged)
    frames = _P(int, lambda s: s.detector.stats.frames, notify=frameChanged)
    motionFrames = _P(int, lambda s: s.detector.stats.motion_frames, notify=frameChanged)
    cameraFrames = _P(int, lambda s: s.detector.stats.camera_frames, notify=frameChanged)
    log = _P(list, lambda s: list(s._log), notify=frameChanged)
    shots = _P(list, lambda s: list(s._shots), notify=frameChanged)

    # ================================================================== slots
    @Slot(float, float)
    def moveRoi(self, x: float, y: float) -> None:
        """Перетаскивание окна захвата (= поворот камеры)."""
        self._anchor_x, self._anchor_y = x, y
        self.scene.move_roi(x, y)
        self._anchor_x, self._anchor_y = self.scene.roi_x, self.scene.roi_y
        self.geometryChanged.emit()

    @Slot(float, float)
    def nudgeRoi(self, dx: float, dy: float) -> None:
        self.moveRoi(self._anchor_x + dx, self._anchor_y + dy)

    @Slot(float, float)
    def moveSprite(self, x: float, y: float) -> None:
        """Ручное перетаскивание цели."""
        sp = self.scene.sprite
        sp.x, sp.y, sp.visible = x, y, True
        self._pass_active = False
        self.geometryChanged.emit()

    @Slot()
    def startPass(self) -> None:
        sc, sp = self.scene, self.scene.sprite
        sw, sh = sp.size
        cx, cy = sc.crosshair
        self._pass_dir = -self._pass_dir
        sp.y = cy - sh * 0.35 + self._target_offset_y
        margin = 10 + self._sway_amp
        if self._pass_dir > 0:
            sp.x = sc.roi_x - sw - margin
            self._pass_end_x = sc.roi_x + sc.roi_w + margin
        else:
            sp.x = sc.roi_x + sc.roi_w + margin
            self._pass_end_x = sc.roi_x - sw - margin
        sp.visible = True
        self._pass_active = True
        self._pass_shots = 0
        self.geometryChanged.emit()

    @Slot()
    def hideTarget(self) -> None:
        self._pass_active = False
        self._auto_pass = False
        self.scene.sprite.visible = False
        self.configChanged.emit()
        self.geometryChanged.emit()

    @Slot()
    def resetCounters(self) -> None:
        self.detector.reset()
        self._hits = self._misses = self._passes = self._passes_hit = self._extra_shots = 0
        self._log.clear()
        self._shots.clear()
        self._t0 = time.perf_counter()
        self.frameChanged.emit()

    @Slot()
    def resetDetectorDefaults(self) -> None:
        d = MotionConfig()
        for name, val in [("sensitivity", d.sensitivity), ("zoneRadius", d.zone_radius),
                          ("minArea", d.min_area), ("confirmFrames", d.confirm_frames),
                          ("fireDelayMs", d.fire_delay_ms), ("cooldownMs", d.cooldown_ms),
                          ("rearmOnCalm", d.rearm_on_calm), ("compensateCamera", d.compensate_camera),
                          ("ignoreCamera", d.ignore_camera_motion), ("cameraLimit", d.camera_limit),
                          ("downscale", d.downscale)]:
            self.setProperty(name, val)

    @Slot(QUrl)
    @Slot(str)
    def loadBackground(self, url) -> None:
        path = url.toLocalFile() if isinstance(url, QUrl) else str(url)
        try:
            img = load_bgr(path)
        except ValueError as e:
            self._log.appendleft(str(e))
            self.frameChanged.emit()
            return
        self.scene.set_background(img)
        self._anchor_x, self._anchor_y = self.scene.roi_x, self.scene.roi_y
        self.detector.reset(keep_stats=True)
        self._publish_scene()

    @Slot()
    def generateBackground(self) -> None:
        w, h = self.scene.size
        self.scene.set_background(make_background(w, h, seed=int(time.time()) % 10000))
        self.detector.reset(keep_stats=True)
        self._publish_scene()

    @Slot(QUrl)
    @Slot(str)
    def loadTarget(self, url) -> None:
        path = url.toLocalFile() if isinstance(url, QUrl) else str(url)
        try:
            load_bgra(path, 8)  # проверка, что открывается
        except ValueError as e:
            self._log.appendleft(str(e))
            self.frameChanged.emit()
            return
        self._custom_sprite_path = path
        self._rebuild_sprite()

    @Slot()
    def defaultTarget(self) -> None:
        self._custom_sprite_path = None
        self._rebuild_sprite()

    @Slot(int, int)
    def setRoiSize(self, w: int, h: int) -> None:
        cx, cy = self.scene.crosshair
        self.scene.set_roi_size(w, h)
        self.moveRoi(cx - self.scene.roi_w / 2, cy - self.scene.roi_h / 2)
        self.detector.reset(keep_stats=True)
        self._publish_scene()

    # ================================================================ internals
    def _sync_config(self) -> None:
        c = self.detector.config
        c.sensitivity = float(self._sensitivity)
        c.zone_radius = int(self._zone_radius)
        c.min_area = float(self._min_area)
        c.confirm_frames = int(self._confirm_frames)
        c.fire_delay_ms = float(self._fire_delay)
        c.cooldown_ms = float(self._cooldown)
        c.rearm_on_calm = bool(self._rearm_on_calm)
        c.compensate_camera = bool(self._compensate)
        c.ignore_camera_motion = bool(self._ignore_camera)
        c.camera_limit = float(self._camera_limit)
        if c.downscale != int(self._downscale):
            c.downscale = int(self._downscale)
            self.detector.reset(keep_stats=True)

    def _restart_timer(self) -> None:
        self._timer.start(int(1000 / max(1, self._lab_fps)))

    def _rebuild_sprite(self) -> None:
        h = max(10, int(self._target_height))
        if self._custom_sprite_path:
            bgr, alpha = load_bgra(self._custom_sprite_path, h)
        else:
            bgr, alpha = make_target_sprite(h)
        self.scene.set_sprite(bgr, alpha)
        self._publish_scene()

    def _publish_scene(self) -> None:
        self.provider.set("bg", self.scene.background)
        sp = self.scene.sprite
        bgra = np.dstack([sp.bgr, (sp.alpha * 255).astype(np.uint8)])
        self.provider.set("sprite", bgra)
        self._bg_id += 1
        self._sprite_id += 1
        self.sceneChanged.emit()
        self.geometryChanged.emit()

    def _now_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0

    def _step(self) -> None:
        if self._paused:
            return
        now = self._now_ms()
        dt = 1.0 / max(1, self._lab_fps)
        sc, sp = self.scene, self.scene.sprite

        # --- камера: покачивание вокруг точки, куда пользователь поставил ROI
        if self._sway_amp > 0:
            off = math.sin(2 * math.pi * self._sway_hz * now / 1000.0) * self._sway_amp
            sc.move_roi(self._anchor_x + off, self._anchor_y)
        elif (sc.roi_x, sc.roi_y) != (self._anchor_x, self._anchor_y):
            sc.move_roi(self._anchor_x, self._anchor_y)

        # --- цель
        if self._pass_active:
            sp.x += self._pass_dir * self._target_speed * dt
            if (self._pass_dir > 0 and sp.x >= self._pass_end_x) or \
               (self._pass_dir < 0 and sp.x <= self._pass_end_x):
                self._finish_pass(now)
        elif self._auto_pass and now >= self._next_pass_at:
            self.startPass()

        # --- кадр и детектор
        t = time.perf_counter()
        frame = sc.render_roi()
        res = self.detector.process(frame, now)
        self._proc_ms = self._proc_ms * 0.9 + (time.perf_counter() - t) * 1000 * 0.1

        if res.fired:
            self._on_fire(now, res.zone_ratio)

        # --- визуализация
        self.provider.set("roi", frame)
        self.provider.set("mask", self._mask_image(res, frame.shape))

        self._zone_pct = res.zone_ratio * 100
        self._ring_pct = res.ring_ratio * 100
        self._state = STATE_RU[res.state]
        self._motion = res.motion
        self._camera = res.camera_motion
        self._shift_x, self._shift_y = res.camera_shift

        self._times.append(time.perf_counter())
        if len(self._times) > 1:
            self._fps = (len(self._times) - 1) / (self._times[-1] - self._times[0])
        self._frame_id += 1
        self.geometryChanged.emit()
        self.frameChanged.emit()

    def _finish_pass(self, now: float) -> None:
        self._pass_active = False
        self.scene.sprite.visible = False
        self._passes += 1
        if self._pass_shots > 0:
            self._passes_hit += 1
        self._next_pass_at = now + self._pass_pause

    def _on_fire(self, now: float, zone_ratio: float) -> None:
        cx, cy = self.scene.crosshair
        hit = self.scene.sprite_covers(cx, cy)
        if hit:
            self._hits += 1
        else:
            self._misses += 1
        if self._pass_active:
            self._pass_shots += 1
            if self._pass_shots > 1:
                self._extra_shots += 1
        self._shots.append({"x": cx, "y": cy, "hit": hit})
        n = self.detector.stats.triggers
        self._log.appendleft(
            f"#{n:<3} {now / 1000:7.2f}s  {'ПОПАЛ ' if hit else 'мимо  '}  зона {zone_ratio * 100:4.0f}%"
        )
        self.fired.emit(hit)

    def _mask_image(self, res, shape) -> np.ndarray:
        h, w = shape[:2]
        out = np.zeros((h, w, 3), np.uint8)
        if res.mask is None:
            return out
        k = max(1, self.detector.config.downscale)
        diff = upscale_nearest(np.clip(res.diff * 3, 0, 255).astype(np.uint8), k)
        mask = upscale_nearest(res.mask, k)
        mh, mw = min(h, mask.shape[0]), min(w, mask.shape[1])
        out[:mh, :mw] = diff[:mh, :mw, None] // 3            # тусклая разница
        if res.fired:
            color = (60, 60, 255)      # красный
        elif res.camera_motion:
            color = (150, 150, 150)    # серый: подавлено как движение камеры
        elif res.motion:
            color = (60, 200, 255)     # жёлтый: движение в зоне
        else:
            color = (120, 220, 90)     # зелёный: изменённые пиксели
        out[:mh, :mw][mask[:mh, :mw]] = color
        return out
