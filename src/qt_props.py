"""Мини-хелпер, чтобы не писать по 10 строк на каждое Qt-свойство."""
from PySide6.QtCore import Property


def rw_property(type_, attr: str, notify, notify_name: str, on_change: str | None = None):
    """Read/write Property: хранит значение в self.<attr>, эмитит self.<notify_name>."""

    def getter(self):
        return getattr(self, attr)

    def setter(self, value):
        if getattr(self, attr) == value:
            return
        setattr(self, attr, value)
        getattr(self, notify_name).emit()
        if on_change:
            getattr(self, on_change)()

    return Property(type_, getter, setter, notify=notify)


def ro_property(type_, attr: str, notify):
    return Property(type_, lambda self: getattr(self, attr), notify=notify)
