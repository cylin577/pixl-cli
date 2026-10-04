import json
import os
import urllib.error
import urllib.request
import zipfile

PROXY_BASE = "https://ghs.cylin577.fyi/"
REPO_LIST_URL = (
    "https://raw.githubusercontent.com/cylin577/pixl-cli/main/pixl_cli/repos.yaml"
)
API_BASE = "https://api.github.com"
CACHE_DIR = os.environ.get(
    "PIXL_CLI_CACHE",
    os.path.join(os.path.expanduser("~"), ".cache", "pixl-cli"),
)
RELEASES_DIR = os.path.join(CACHE_DIR, "releases")

OTA_PREFIX = "pixjs_ota_v"
OTA_SUFFIX = ".zip"


class ReleaseError(Exception):
    pass


def _bundled_repos_path():
    return os.path.join(os.path.dirname(__file__), "repos.yaml")


def _http_get(url, headers=None, timeout=15.0):
    request = urllib.request.Request(url, headers=headers or {})
    request.add_header("User-Agent", "pixl-cli")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as e:
        raise ReleaseError(f"request failed: {url}: {e}")


def _parse_repos(data):
    import yaml

    document = yaml.safe_load(data)
    if not isinstance(document, dict) or not isinstance(document.get("repos"), list):
        raise ReleaseError("repo list must be a mapping with a 'repos' list")
    repos = []
    for entry in document["repos"]:
        if isinstance(entry, str):
            entry = {"repo": entry}
        if not isinstance(entry, dict) or not entry.get("repo"):
            raise ReleaseError("each repo entry needs a 'repo' field")
        slug = str(entry["repo"]).strip()
        repos.append(
            {
                "repo": slug,
                "name": entry.get("name") or slug,
                "description": entry.get("description") or "",
            }
        )
    if not repos:
        raise ReleaseError("repo list is empty")
    return repos


def load_repo_list(url=None, timeout=5.0):
    url = url or REPO_LIST_URL
    try:
        return _parse_repos(_http_get(url, timeout=timeout))
    except ReleaseError:
        pass
    with open(_bundled_repos_path(), "rb") as f:
        return _parse_repos(f.read())


def list_releases(slug, token=None, timeout=15.0):
    url = f"{API_BASE}/repos/{slug}/releases?per_page=100"
    headers = {"Accept": "application/vnd.github+json"}
    token = token or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        payload = json.loads(_http_get(url, headers=headers, timeout=timeout))
    except ValueError as e:
        raise ReleaseError(f"invalid release response for {slug}: {e}")
    if not isinstance(payload, list):
        message = payload.get("message") if isinstance(payload, dict) else None
        raise ReleaseError(f"cannot list releases for {slug}: {message or 'unexpected response'}")
    releases = []
    for item in payload:
        tag = item.get("tag_name")
        if not tag:
            continue
        releases.append(
            {
                "tag": tag,
                "name": item.get("name") or tag,
                "published": item.get("published_at") or "",
                "prerelease": bool(item.get("prerelease")),
                "assets": [a.get("name") for a in item.get("assets", []) if a.get("name")],
            }
        )
    return releases


def asset_name(tag, board):
    return f"{tag}_{board.upper()}{OTA_SUFFIX}"


def release_asset_url(slug, tag, board):
    return (
        f"https://github.com/{slug}/releases/download/{tag}/{asset_name(tag, board)}"
    )


def proxy_url(url):
    return PROXY_BASE + url


def download(url, dest, progress=None, timeout=60.0, chunk_size=65536):
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    request = urllib.request.Request(url)
    request.add_header("User-Agent", "pixl-cli")
    tmp = dest + ".part"
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with open(tmp, "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        os.replace(tmp, dest)
    except (urllib.error.URLError, OSError) as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise ReleaseError(f"download failed: {url}: {e}")
    return dest


def download_release(slug, tag, board, dest_dir=None, progress=None, timeout=60.0):
    dest_dir = dest_dir or os.path.join(RELEASES_DIR, tag)
    dest = os.path.join(dest_dir, asset_name(tag, board))
    if os.path.exists(dest):
        return dest
    return download(proxy_url(release_asset_url(slug, tag, board)), dest, progress, timeout)


def find_ota(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        names = [
            n
            for n in zf.namelist()
            if os.path.basename(n).startswith(OTA_PREFIX)
            and os.path.basename(n).endswith(OTA_SUFFIX)
        ]
    return sorted(names, key=os.path.basename)


def extract_ota(zip_path, dest_dir=None):
    members = find_ota(zip_path)
    if not members:
        raise ReleaseError(f"no {OTA_PREFIX}*{OTA_SUFFIX} inside {zip_path}")
    member = members[-1]
    dest_dir = dest_dir or os.path.dirname(os.path.abspath(zip_path))
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(member) as src:
            dest = os.path.join(dest_dir, os.path.basename(member))
            tmp = dest + ".part"
            with open(tmp, "wb") as out:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
            os.replace(tmp, dest)
    return dest
