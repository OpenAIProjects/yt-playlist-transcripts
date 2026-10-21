"""Small dependency-free console progress indicators shared by the pipeline."""

from __future__ import annotations

import sys
import threading


class ProgressBar:
    def __init__(self, label: str, total: int, stream=None, width: int = 24):
        self.label = label
        self.total = max(total, 0)
        self.stream = stream or sys.stderr
        self.width = width
        self.tty = bool(getattr(self.stream, "isatty", lambda: False)())

    def update(self, completed: int, detail: str = "") -> None:
        completed = min(max(completed, 0), self.total)
        fraction = completed / self.total if self.total else 0
        filled = round(self.width * fraction)
        bar = "#" * filled + "-" * (self.width - filled)
        percent = f"{fraction:.0%}" if self.total else "no work"
        line = f"{self.label} [{bar}] {completed}/{self.total} ({percent})"
        if detail:
            line += f" | {detail}"
        if self.tty:
            self.stream.write("\r\x1b[2K" + line)
            if completed >= self.total:
                self.stream.write("\n")
        else:
            self.stream.write(line + "\n")
        self.stream.flush()


class Spinner:
    """Show activity during a task whose total duration is unknown."""

    def __init__(self, message: str, stream=None, interval: float = 0.12):
        self.message = message
        self.stream = stream or sys.stderr
        self.interval = interval
        self.tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        if not self.tty:
            self.stream.write(self.message + "\n")
            self.stream.flush()
            return self

        def animate():
            frames = "|/-\\"
            index = 0
            while not self._stop.is_set():
                self.stream.write(f"\r\x1b[2K{frames[index % len(frames)]} {self.message}")
                self.stream.flush()
                index += 1
                self._stop.wait(self.interval)

        self._thread = threading.Thread(target=animate, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self._thread:
            self._stop.set()
            self._thread.join()
            self.stream.write("\r\x1b[2K")
            self.stream.flush()
        return False
