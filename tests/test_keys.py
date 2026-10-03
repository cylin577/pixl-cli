import os
import sys
import unittest

from pixl_cli.keys import read_key


class TestReadKey(unittest.TestCase):
    def _via_pipe(self, data):
        r, w = os.pipe()
        os.set_blocking(r, True)
        os.write(w, data)
        os.close(w)
        fake_stdin = open(r, "r", buffering=1)
        old = sys.stdin
        sys.stdin = fake_stdin
        try:
            return read_key(timeout=0.5)
        finally:
            sys.stdin = old
            fake_stdin.close()

    def test_arrow_down_burst(self):
        self.assertEqual(self._via_pipe(b"\x1b[B"), "down")

    def test_arrow_up_burst(self):
        self.assertEqual(self._via_pipe(b"\x1b[A"), "up")

    def test_arrow_up_application_mode(self):
        self.assertEqual(self._via_pipe(b"\x1bOA"), "up")

    def test_enter(self):
        self.assertEqual(self._via_pipe(b"\r"), "enter")

    def test_bare_escape(self):
        self.assertEqual(self._via_pipe(b"\x1b"), "esc")

    def test_plain_char(self):
        self.assertEqual(self._via_pipe(b"q"), "q")

    def test_timeout(self):
        r, w = os.pipe()
        os.set_blocking(r, True)
        fake_stdin = open(r, "r", buffering=1)
        old = sys.stdin
        sys.stdin = fake_stdin
        try:
            self.assertIsNone(read_key(timeout=0.05))
        finally:
            sys.stdin = old
            fake_stdin.close()
