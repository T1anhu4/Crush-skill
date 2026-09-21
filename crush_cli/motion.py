"""Small, accessible terminal activity feedback with no third-party dependencies."""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from typing import TextIO

from crush_cli.presentation import display_width, safe_text, wrap_lines


FRAMES = ('·', '✦', '✧', '✶', '✧', '✦')
INTERVAL = 0.1


def _label(text: str) -> str:
    # A stage must stay on one line and cannot inject terminal controls.
    return safe_text(text).replace('\n', ' ')


def _fit(text: str, cells: int) -> str:
    result = ''
    used = 0
    for char in text:
        width = display_width(char)
        if used + width > cells:
            break
        result += char
        used += width
    return result


def render_frame(label: str, elapsed: float, columns: int, *, color: bool = False) -> str:
    """Render a deterministic frame, leaving the last column free to avoid wrap."""
    cells = max(0, columns - 1)
    elapsed = max(0.0, elapsed)
    star = FRAMES[int(elapsed / INTERVAL) % len(FRAMES)]
    suffix = f'  {elapsed:.1f}s'
    label = _label(label)
    if cells >= 2 + display_width(suffix):
        line = star + ' ' + _fit(label, cells - 2 - display_width(suffix)) + suffix
    else:
        line = _fit(star + ' ' + label, cells)
    return f'\x1b[38;5;180m{line}\x1b[0m' if color and line else line


class Spinner:
    def __init__(self, label: str, enabled: bool = True, *, stream: TextIO | None = None) -> None:
        self.label = label
        self.stream = stream if stream is not None else sys.stdout
        self.enabled = (
            enabled and self.stream.isatty()
            and os.environ.get('TERM', '').lower() != 'dumb'
            and os.environ.get('CRUSH_REDUCED_MOTION') != '1'
        )
        self._color = 'NO_COLOR' not in os.environ
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = 0.0

    def _columns(self) -> int:
        try:
            return os.get_terminal_size(self.stream.fileno()).columns
        except (AttributeError, OSError, ValueError):
            return shutil.get_terminal_size(fallback=(80, 24)).columns

    def _draw(self) -> None:
        frame = render_frame(self.label, time.monotonic() - self._started, self._columns(), color=self._color)
        self.stream.write('\r\x1b[2K' + frame)
        self.stream.flush()

    def __enter__(self) -> Spinner:
        if not self.enabled:
            self.stream.write('\n'.join(wrap_lines(_label(self.label), max(1, self._columns() - 1))) + '\n')
            self.stream.flush()
            return self
        self._stop.clear()
        self._started = time.monotonic()
        self._draw()

        def run() -> None:
            while not self._stop.wait(INTERVAL):
                self._draw()

        self._thread = threading.Thread(target=run, daemon=True)
        try:
            self._thread.start()
        except BaseException:
            self._stop.set()
            self.stream.write('\r\x1b[2K')
            self.stream.flush()
            raise
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self.stream.write('\r\x1b[2K')
            self.stream.flush()
