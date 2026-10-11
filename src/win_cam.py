import queue
import threading

from wincam import DXCamera


class ThreadedCapture:
    def __init__(self, x, y, w, h, fps=60, maxsize=2):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.fps = fps
        self.queue = queue.Queue(maxsize=maxsize)
        self._stop_event = threading.Event()
        self._thread = None
        self.captured = 0
        self.dropped = 0

    def _capture_loop(self):
        # DXCamera должен жить внутри потока-владельца
        with DXCamera(self.x, self.y, self.w, self.h, fps=self.fps) as camera:
            while not self._stop_event.is_set():
                frame, timestamp = camera.get_bgr_frame()
                if frame is None:
                    continue
                self.captured += 1
                try:
                    self.queue.put_nowait((frame, timestamp))
                except queue.Full:
                    self.dropped += 1
                    try:
                        self.queue.get_nowait()
                    except queue.Empty:
                        pass
                    self.queue.put_nowait((frame, timestamp))

    def start(self):
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        return self

    def read(self, timeout=1.0):
        """Возвращает самый свежий доступный кадр."""
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None, None

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)