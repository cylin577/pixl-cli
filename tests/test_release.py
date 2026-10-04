import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pixl_cli import release  # noqa: E402


class FakeResponse:
    def __init__(self, data):
        self._data = data
        self.headers = {"Content-Length": str(len(data))}

    def read(self, size=-1):
        if size < 0:
            size = len(self._data)
        chunk, self._data = self._data[:size], self._data[size:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestParseRepos(unittest.TestCase):
    def test_parses_repo_name_description(self):
        data = b"""
repos:
  - repo: solosky/pixl.js
    name: pixl.js (upstream)
    description: Official releases
"""
        repos = release._parse_repos(data)
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0]["repo"], "solosky/pixl.js")
        self.assertEqual(repos[0]["name"], "pixl.js (upstream)")
        self.assertEqual(repos[0]["description"], "Official releases")

    def test_plain_string_entry_gets_defaults(self):
        repos = release._parse_repos(b"repos:\n  - solosky/pixl.js\n")
        self.assertEqual(repos[0]["name"], "solosky/pixl.js")
        self.assertEqual(repos[0]["description"], "")

    def test_rejects_missing_repos_key(self):
        with self.assertRaises(release.ReleaseError):
            release._parse_repos(b"other: true\n")

    def test_rejects_entry_without_repo(self):
        with self.assertRaises(release.ReleaseError):
            release._parse_repos(b"repos:\n  - name: nope\n")


class TestLoadRepoList(unittest.TestCase):
    def test_uses_remote_when_available(self):
        original = release._http_get
        release._http_get = lambda *a, **k: b"repos:\n  - repo: a/b\n    description: remote\n"
        try:
            repos = release.load_repo_list()
            self.assertEqual(repos, [{"repo": "a/b", "name": "a/b", "description": "remote"}])
        finally:
            release._http_get = original

    def test_falls_back_to_bundled_on_failure(self):
        def boom(*a, **k):
            raise release.ReleaseError("offline")

        original = release._http_get
        release._http_get = boom
        try:
            repos = release.load_repo_list()
        finally:
            release._http_get = original
        slugs = [r["repo"] for r in repos]
        self.assertIn("solosky/pixl.js", slugs)
        self.assertIn("cylin577/pixl.js", slugs)
        self.assertTrue(all(r["description"] for r in repos))


class TestUrls(unittest.TestCase):
    def test_asset_name_and_url(self):
        self.assertEqual(release.asset_name("2.16.0", "oled"), "2.16.0_OLED.zip")
        self.assertEqual(
            release.release_asset_url("solosky/pixl.js", "2.16.0", "LCD"),
            "https://github.com/solosky/pixl.js/releases/download/2.16.0/2.16.0_LCD.zip",
        )

    def test_v_prefixed_tag(self):
        self.assertEqual(
            release.release_asset_url("cylin577/pixl.js", "v2.17.1", "OLED"),
            "https://github.com/cylin577/pixl.js/releases/download/v2.17.1/v2.17.1_OLED.zip",
        )

    def test_proxy_wraps_url(self):
        url = release.release_asset_url("a/b", "1.0", "OLED")
        self.assertEqual(
            release.proxy_url(url),
            "https://ghs.cylin577.fyi/https://github.com/a/b/releases/download/1.0/1.0_OLED.zip",
        )


class TestDownload(unittest.TestCase):
    def test_download_streams_to_dest(self):
        calls = []
        original = release.urllib.request.urlopen
        release.urllib.request.urlopen = lambda *a, **k: FakeResponse(b"hello world")
        try:
            with tempfile.TemporaryDirectory() as d:
                dest = os.path.join(d, "sub", "file.bin")
                release.download("http://example.test/x", dest, progress=lambda o, t: calls.append((o, t)))
                with open(dest, "rb") as f:
                    self.assertEqual(f.read(), b"hello world")
        finally:
            release.urllib.request.urlopen = original
        self.assertTrue(calls)
        self.assertEqual(calls[-1], (11, 11))


class TestExtractOta(unittest.TestCase):
    def _make_outer(self, path, members):
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in members.items():
                zf.writestr(name, data)

    def test_extracts_inner_ota(self):
        with tempfile.TemporaryDirectory() as d:
            outer = os.path.join(d, "2.16.0_OLED.zip")
            self._make_outer(
                outer,
                {
                    "pixljs.hex": b"hex",
                    "pixjs_ota_v7.zip": b"ota-bytes",
                    "fw_readme.txt": b"readme",
                },
            )
            ota = release.extract_ota(outer)
            self.assertEqual(os.path.basename(ota), "pixjs_ota_v7.zip")
            with open(ota, "rb") as f:
                self.assertEqual(f.read(), b"ota-bytes")
            self.assertFalse(os.path.exists(ota + ".part"))

    def test_errors_when_no_ota(self):
        with tempfile.TemporaryDirectory() as d:
            outer = os.path.join(d, "bad.zip")
            self._make_outer(outer, {"pixljs.hex": b"hex"})
            with self.assertRaises(release.ReleaseError):
                release.extract_ota(outer)


if __name__ == "__main__":
    unittest.main()
