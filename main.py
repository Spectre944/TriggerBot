import hashlib

from src import ThreadedCapture


def main() -> None:
    x, y, w, h = 0, 0, 400, 300
    fps = 30
    max_frames = 100

    capture = ThreadedCapture(x, y, w, h, fps=fps).start()

    last_hash = None
    frame_count = 0
    changed_count = 0

    try:
        while frame_count < max_frames:
            frame, timestamp = capture.read(timeout=2.0)
            if frame is None:
                print("Таймаут ожидания кадра")
                continue

            frame_count += 1
            frame_hash = hashlib.md5(frame.tobytes()).hexdigest()

            if last_hash is None:
                print(f"Кадр {frame_count}: первый. Timestamp: {timestamp}")
            elif frame_hash != last_hash:
                changed_count += 1
                print(f"Кадр {frame_count}: отличается. Timestamp: {timestamp}")
            else:
                print(f"Кадр {frame_count}: идентичен предыдущему. Timestamp: {timestamp}")

            last_hash = frame_hash
    finally:
        capture.stop()

    print(f"\nИтого: {changed_count} уникальных кадров из {frame_count}")
    print(f"Захвачено потоком: {capture.captured}, выброшено: {capture.dropped}")


if __name__ == "__main__":
    main()