'''
Запуск из консоли
python -m testing.benchmark
'''

import hashlib
import time
from collections import deque

from src import ThreadedCapture


def main() -> None:
    x, y, w, h = 0, 0, 1600, 900
    target_fps = 144  # Попробуйте разные значения
    measure_seconds = 5.0

    capture = ThreadedCapture(x, y, w, h, fps=target_fps).start()

    # Скользящее окно для сглаживания замеров
    frame_times = deque(maxlen=30)
    last_hash = None
    changed_count = 0
    frame_count = 0

    start_time = time.perf_counter()
    last_frame_time = start_time

    try:
        while time.perf_counter() - start_time < measure_seconds:
            frame, timestamp = capture.read(timeout=2.0)
            if frame is None:
                continue

            now = time.perf_counter()
            frame_times.append(now)
            frame_count += 1

            # Хеш для проверки уникальности
            frame_hash = hashlib.md5(frame.tobytes()).hexdigest()
            if last_hash is not None and frame_hash != last_hash:
                changed_count += 1
            last_hash = frame_hash

            # Раз в 30 кадров выводим текущий FPS
            if len(frame_times) >= 2:
                elapsed = frame_times[-1] - frame_times[0]
                if elapsed > 0:
                    current_fps = (len(frame_times) - 1) / elapsed
                    print(f"\rТекущий FPS: {current_fps:.1f} | Кадров: {frame_count} | Уникальных: {changed_count}", end="")
    finally:
        capture.stop()

    # Итоговый расчёт
    total_time = time.perf_counter() - start_time
    overall_fps = frame_count / total_time if total_time > 0 else 0

    print(f"\n\n=== Результаты ===")
    print(f"Целевой FPS: {target_fps}")
    print(f"Фактический средний FPS: {overall_fps:.2f}")
    print(f"Всего кадров: {frame_count}")
    print(f"Уникальных кадров: {changed_count}")
    print(f"Захвачено потоком: {capture.captured}, выброшено: {capture.dropped}")
    print(f"Время измерения: {total_time:.2f} сек")


if __name__ == "__main__":
    main()