"""Bounded, credential-free release discovery for the Emviary E1002."""

import json
import re
import threading
import time
from urllib.parse import urlparse

import httpx

REPOSITORY = "lstepnio/Emviary-firmware"
ASSET_NAME = "emviary-seeedstudio_reterminal_e1002.bin"
MAX_SIZE = 0x380000


def version(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?", value)
    if not match:
        return None
    prerelease = match[4]
    parts = tuple((0, int(p)) if p.isdecimal() else (1, p) for p in (prerelease or "").split("."))
    return tuple(int(match[i]) for i in (1, 2, 3)), prerelease is None, parts


def valid_asset(asset, tag):
    url = asset.get("browser_download_url", "")
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    prefix = f"/{REPOSITORY}/releases/download/{tag}/"
    digest = asset.get("digest", "")
    size = asset.get("size")
    return (
        asset.get("name") == ASSET_NAME
        and parsed.scheme == "https"
        and parsed.netloc == "github.com"
        and parsed.path == prefix + ASSET_NAME
        and not parsed.query
        and not parsed.fragment
        and isinstance(size, int)
        and not isinstance(size, bool)
        and 1024 <= size <= MAX_SIZE
        and isinstance(digest, str)
        and re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest) is not None
    )


class FirmwareUpdates:
    def __init__(self):
        self._lock = threading.Lock()
        self._expires = 0
        self._releases = []

    def releases(self):
        with self._lock:
            if time.monotonic() < self._expires:
                return self._releases
            try:
                with httpx.Client(timeout=8, follow_redirects=False, trust_env=False) as client:
                    with client.stream(
                        "GET",
                        f"https://api.github.com/repos/{REPOSITORY}/releases",
                        params={"per_page": 30},
                        headers={"Accept": "application/vnd.github+json"},
                    ) as response:
                        response.raise_for_status()
                        body = bytearray()
                        for chunk in response.iter_bytes(chunk_size=65536):
                            body.extend(chunk)
                            if len(body) > 1_000_000:
                                raise ValueError("Release response too large")
                        releases = json.loads(body)
                    if not isinstance(releases, list):
                        raise ValueError("Invalid release response")
                    self._releases = releases[:30]
            except (httpx.HTTPError, ValueError):
                # Fail closed on discovery failure, without extending stale update offers.
                self._releases = []
            self._expires = time.monotonic() + 600
            return self._releases

    def check(self, policy, current):
        mode = policy.firmware_updates
        pin = policy.firmware_pinned_version
        result = {"tag_name": current, "assets": [], "update_available": False, "policy": mode}
        if mode == "disabled" or (mode == "manual" and not pin):
            return result
        current_version = version(current)
        candidates = []
        for release in self.releases():
            if not isinstance(release, dict) or release.get("draft", True):
                continue
            tag = release.get("tag_name", "")
            candidate = version(tag) if isinstance(tag, str) else None
            if (
                not candidate
                or (current_version is not None and candidate <= current_version)
                or (pin and tag != pin)
            ):
                continue
            assets = release.get("assets", [])
            if not isinstance(assets, list):
                continue
            for asset in assets[:30]:
                if isinstance(asset, dict) and valid_asset(asset, tag):
                    candidates.append((candidate, tag, asset, release.get("prerelease", False)))
        if not candidates:
            return result
        _, tag, asset, prerelease = max(candidates, key=lambda item: item[0])
        digest = asset["digest"].split(":", 1)[1].lower()
        result.update(
            tag_name=tag,
            assets=[
                {
                    "name": ASSET_NAME,
                    "browser_download_url": asset["browser_download_url"],
                    "size": asset["size"],
                    "digest": "sha256:" + digest,
                    "sha256": digest,
                }
            ],
            sha256=digest,
            size=asset["size"],
            prerelease=prerelease,
            update_available=True,
        )
        return result
