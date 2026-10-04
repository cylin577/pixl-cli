import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pixl_cli import fuse_fs  # noqa: E402


class TestMountHelpers(unittest.TestCase):
    def test_plain_dir_is_not_mounted(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(fuse_fs.is_mounted(d))
            self.assertFalse(fuse_fs.is_stale_mount(d))

    def test_missing_path_is_not_mounted(self):
        self.assertFalse(fuse_fs.is_mounted("/no/such/path/here"))

    def test_ensure_mountpoint_creates_nested_dir(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "a", "b", "c")
            result = fuse_fs.ensure_mountpoint(target)
            self.assertEqual(result, target)
            self.assertTrue(os.path.isdir(target))

    def test_ensure_mountpoint_keeps_existing_dir(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(fuse_fs.ensure_mountpoint(d), d)

    def test_unmount_non_mount_returns_false(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(fuse_fs.unmount(d))

    def test_unmount_returns_true_when_helper_succeeds(self):
        from unittest import mock

        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            self.assertTrue(fuse_fs.unmount("/tmp/x"))

    def test_unmount_falls_through_missing_binaries(self):
        from unittest import mock

        calls = []

        def fake_run(cmd, capture_output=True):
            calls.append(cmd[0])
            if cmd[0] in ("fusermount", "fusermount3"):
                raise FileNotFoundError(cmd[0])
            return mock.Mock(returncode=0)

        with mock.patch("subprocess.run", side_effect=fake_run):
            self.assertTrue(fuse_fs.unmount("/tmp/x"))
        self.assertEqual(calls, ["fusermount", "fusermount3", "umount"])


if __name__ == "__main__":
    unittest.main()
