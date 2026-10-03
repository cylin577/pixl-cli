import contextlib
import sys
import time

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import msvcrt

    @contextlib.contextmanager
    def cbreak_mode():
        yield

    def read_key(timeout=0.1):
        deadline = time.monotonic() + timeout
        while not msvcrt.kbhit():
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.02)
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(ch2, "esc")
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x03":
            return "ctrl-c"
        if ch == "\x1b":
            return "esc"
        return ch

else:
    import os
    import select
    import termios
    import tty

    @contextlib.contextmanager
    def cbreak_mode():
        attrs = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin)
            yield
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, attrs)

    def read_key(timeout=0.1):
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            return None
        data = os.read(sys.stdin.fileno(), 64)
        if not data:
            return "esc"
        ch = data[:1]
        if ch == b"\x1b":
            if len(data) == 1:
                return "esc"
            if data[1:2] == b"[":
                final = data[-1:]
                return {b"A": "up", b"B": "down", b"C": "right", b"D": "left"}.get(final, "esc")
            if data[1:2] == b"O":
                final = data[-1:]
                return {b"A": "up", b"B": "down"}.get(final, "esc")
            return "esc"
        if ch in (b"\r", b"\n"):
            return "enter"
        if ch == b"\x03":
            return "ctrl-c"
        if ch == b"\x04":
            raise EOFError
        return ch.decode("utf-8", "ignore")
