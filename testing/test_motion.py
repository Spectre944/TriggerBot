"""
python -m pytest testing -q
"""
import numpy as np

from src.processing import MotionConfig, MotionDetector, MotionState, difference_blend
from src.sources import StaticScene, make_background


def _scene():
    sc = StaticScene(make_background(800, 500, seed=5), 160, 160)
    sc.move_roi(300, 150)
    return sc


def _pass_target(det, sc, speed_px=6, start_ms=0.0, dt=1000 / 60):
    """Проводит цель слева направо через прицел, возвращает число выстрелов."""
    cx, cy = sc.crosshair
    sw, sh = sc.sprite.size
    sc.sprite.visible = True
    sc.sprite.y = cy - sh * 0.4
    x = sc.roi_x - sw
    t = start_ms
    fired = 0
    while x < sc.roi_x + sc.roi_w + 5:
        sc.sprite.x = x
        fired += det.process(sc.render_roi(), t).fired
        x += speed_px
        t += dt
    return fired, t


def test_static_scene_no_trigger():
    sc = _scene()
    det = MotionDetector(MotionConfig())
    for i in range(60):
        assert not det.process(sc.render_roi(), i * 16).fired
    assert det.stats.triggers == 0


def test_target_crossing_triggers():
    sc = _scene()
    det = MotionDetector(MotionConfig(cooldown_ms=2000))
    fired, _ = _pass_target(det, sc)
    assert fired == 1


def test_target_outside_zone_does_not_trigger():
    sc = _scene()
    det = MotionDetector(MotionConfig())
    sc.sprite.visible = True
    sw, sh = sc.sprite.size
    sc.sprite.y = sc.roi_y + sc.roi_h - sh * 0.3   # низко, ниже прицела
    for i, x in enumerate(range(int(sc.roi_x - sw), int(sc.roi_x + sc.roi_w), 6)):
        sc.sprite.x = x
        det.process(sc.render_roi(), i * 16)
    assert det.stats.triggers == 0


def test_camera_pan_is_suppressed():
    sc = _scene()
    det = MotionDetector(MotionConfig())
    shifts = []
    for i in range(80):
        sc.move_roi(200 + i * 4, 150)
        shifts.append(det.process(sc.render_roi(), i * 16).camera_shift)
    assert det.stats.triggers == 0
    assert shifts.count((-4, 0)) > 70


def test_target_crossing_during_camera_pan_triggers():
    """Камера ведётся, а цель бежит навстречу — должно сработать."""
    sc = _scene()
    det = MotionDetector(MotionConfig(cooldown_ms=5000))
    sw, sh = sc.sprite.size
    sc.sprite.visible = True
    fired = 0
    for i in range(90):
        sc.move_roi(200 + i * 2, 150)
        cx, cy = sc.crosshair
        sc.sprite.y = cy - sh * 0.4
        sc.sprite.x = 700 - i * 8
        fired += det.process(sc.render_roi(), i * 16).fired
    assert fired == 1


def test_camera_pan_triggers_when_filter_off():
    sc = _scene()
    det = MotionDetector(MotionConfig(ignore_camera_motion=False, compensate_camera=False))
    for i in range(80):
        sc.move_roi(200 + i * 4, 150)
        det.process(sc.render_roi(), i * 16)
    assert det.stats.triggers > 0


def test_fire_delay():
    sc = _scene()
    det = MotionDetector(MotionConfig(fire_delay_ms=100, cooldown_ms=5000))
    first_motion = None
    cx, cy = sc.crosshair
    sw, sh = sc.sprite.size
    sc.sprite.visible = True
    sc.sprite.y = cy - sh * 0.4
    x, t = sc.roi_x - sw, 0.0
    fired_at = None
    while t < 3000:
        sc.sprite.x = x
        r = det.process(sc.render_roi(), t)
        if r.state == MotionState.PENDING and first_motion is None:
            first_motion = t
        if r.fired:
            fired_at = t
            break
        x += 6
        t += 1000 / 60
    assert first_motion is not None and fired_at is not None
    assert 100 <= fired_at - first_motion < 100 + 20


def test_cooldown_limits_rate():
    det = MotionDetector(MotionConfig(cooldown_ms=500, rearm_on_calm=False, ignore_camera_motion=False))
    rng = np.random.default_rng(0)
    for i in range(60):  # 1 секунда сплошного "движения"
        det.process(rng.integers(0, 255, (64, 64, 3), dtype=np.uint8), i * 1000 / 60)
    assert det.stats.triggers == 2


def test_sensitivity_vs_noise():
    sc = _scene()
    sc.noise = 8
    low = MotionDetector(MotionConfig(sensitivity=40))
    high = MotionDetector(MotionConfig(sensitivity=100, rearm_on_calm=False, cooldown_ms=0,
                                       compensate_camera=False, ignore_camera_motion=False))
    for i in range(60):
        f = sc.render_roi()
        low.process(f, i * 16)
        high.process(f, i * 16)
    assert low.stats.triggers == 0
    assert high.stats.triggers > 0


def test_difference_blend():
    a = np.zeros((4, 4, 3), np.uint8)
    b = a.copy()
    b[0, 0] = (10, 200, 30)
    r = difference_blend(b, a, threshold=5)
    assert r.max_diff == 200
    assert r.changed_ratio == 1 / 16
    assert tuple(r.image[0, 0]) == (10, 200, 30)
