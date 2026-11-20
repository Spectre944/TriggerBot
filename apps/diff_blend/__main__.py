"""
Difference Blend — отдельное приложение.

    python -m apps.diff_blend            # обычный запуск
    python -m apps.diff_blend --demo     # без wincam, синтетический источник
"""
import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from apps.diff_blend.backend import DiffBlendBackend
from src.qt_utils import FrameProvider


def main() -> int:
    QQuickStyle.setStyle("Fusion")
    app = QGuiApplication(sys.argv)

    provider = FrameProvider()
    backend = DiffBlendBackend(provider, parent=app)  # живёт дольше QML-движка
    if "--demo" in sys.argv:
        backend.sourceKind = "demo"
    if "--autostart" in sys.argv or "--demo" in sys.argv:
        backend.start()

    engine = QQmlApplicationEngine()
    engine.addImageProvider("frames", provider)
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(Path(__file__).with_name("DiffBlend.qml"))
    if not engine.rootObjects():
        return 1

    code = app.exec()
    backend.stop()
    del engine  # сначала удаляем QML, потом backend
    return code


if __name__ == "__main__":
    sys.exit(main())
