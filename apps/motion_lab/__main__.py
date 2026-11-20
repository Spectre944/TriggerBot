"""
Motion Lab — отладка детектора движения на статической картинке.

    python -m apps.motion_lab                    # процедурный фон
    python -m apps.motion_lab path/to/shot.png   # свой скриншот как фон
"""
import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from apps.motion_lab.backend import MotionLabBackend
from src.qt_utils import FrameProvider


def main() -> int:
    QQuickStyle.setStyle("Fusion")
    app = QGuiApplication(sys.argv)

    provider = FrameProvider()
    backend = MotionLabBackend(provider, parent=app)  # живёт дольше QML-движка
    images = [a for a in sys.argv[1:] if not a.startswith("-")]
    if images:
        backend.loadBackground(images[0])
    if "--auto" in sys.argv:
        backend.autoPass = True

    engine = QQmlApplicationEngine()
    engine.addImageProvider("frames", provider)
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(Path(__file__).with_name("MotionLab.qml"))
    if not engine.rootObjects():
        return 1

    code = app.exec()
    del engine
    return code


if __name__ == "__main__":
    sys.exit(main())
