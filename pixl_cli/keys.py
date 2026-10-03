import contextlib
import os
import select
import sys
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
