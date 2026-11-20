# src/__init__.py
#
# wincam (DXGI) есть только под Windows, поэтому импортируем его лениво:
# остальная часть пакета (обработка, детектор, лаборатория) работает везде.

try:
    from .win_cam import ThreadedCapture
except ImportError:  # pragma: no cover - нет wincam / не Windows
    ThreadedCapture = None

__all__ = [
    "ThreadedCapture",
]
