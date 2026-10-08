import copy

from fastapi.testclient import TestClient

from emviary.api import create_app
from emviary.firmware_updates import ASSET_NAME, REPOSITORY, FirmwareUpdates
from emviary.settings import FramePolicy


def release(tag="v0.3.1", **changes):
    result = {
        "tag_name": tag,
        "draft": False,
        "prerelease": "-" in tag,
        "assets": [
            {
                "name": ASSET_NAME,
                "size": 2048,
                "digest": "sha256:" + "a" * 64,
                "browser_download_url": f"https://github.com/{REPOSITORY}/releases/download/{tag}/{ASSET_NAME}",
            }
        ],
    }
    result.update(changes)
    return result


def checker(releases):
    updates = FirmwareUpdates()
    updates.releases = lambda: releases
    return updates


def test_automatic_prerelease_and_versions():
    updates = checker([release("v0.3.1"), release("v0.4.0-rc.1")])
    result = updates.check(FramePolicy(), "v0.3.0")
    assert result["tag_name"] == "v0.4.0-rc.1"
    assert result["update_available"] and result["sha256"] == "a" * 64
    assert result["size"] == 2048
    assert updates.check(FramePolicy(), "dev04c423f")["update_available"]
    assert not updates.check(FramePolicy(), "v0.5.0")["update_available"]
    assert not checker([release()]).check(FramePolicy(), "v0.3.1")["update_available"]


def test_policy_gates_and_pin():
    updates = checker([release(), release("v0.4.0")])
    for mode in ("disabled", "manual"):
        assert updates.check(FramePolicy(firmware_updates=mode), "v0.3.0")["assets"] == []
    policy = FramePolicy(firmware_updates="manual", firmware_pinned_version="v0.3.1")
    assert updates.check(policy, "v0.3.0")["tag_name"] == "v0.3.1"
    policy.firmware_pinned_version = "v0.3.2"
    assert not updates.check(policy, "v0.3.0")["update_available"]
    policy.firmware_updates = "disabled"
    policy.firmware_pinned_version = "v0.3.1"
    assert not updates.check(policy, "v0.3.0")["update_available"]


def test_invalid_assets_and_drafts():
    cases = [release(draft=True), release(assets=None), release(assets={})]
    for key, value in (
        ("name", "another-board.bin"),
        ("digest", ""),
        ("digest", "sha256:bad"),
        ("size", 0x380001),
        ("size", 0),
        ("browser_download_url", "https://evil.example/firmware.bin"),
        (
            "browser_download_url",
            f"https://github.com/other/repo/releases/download/v0.3.1/{ASSET_NAME}",
        ),
    ):
        item = copy.deepcopy(release())
        item["assets"][0][key] = value
        cases.append(item)
    for item in cases:
        assert not checker([item]).check(FramePolicy(), "v0.3.0")["update_available"]


def test_endpoint_auth_and_no_delivery_mutation(service, frame):
    app = create_app(service, schedule=False)
    app.state.firmware_updates = checker([release()])
    client = TestClient(app)
    before = dict(service.store.frame(frame[0]))
    assert client.get("/v1/firmware?current=v0.3.0").status_code == 401
    response = client.get(
        "/v1/firmware?current=v0.3.0", headers={"Authorization": "Bearer " + frame[1]}
    )
    assert response.status_code == 200 and response.json()["update_available"]
    assert dict(service.store.frame(frame[0])) == before
    assert frame[1] not in response.text


def test_admin_policy_auth_csrf_and_validation(service, frame, tmp_path, monkeypatch):
    import json

    from test_owner import sign_in

    client, csrf = sign_in(service, tmp_path, monkeypatch)
    page = client.get("/manage").text
    assert "https://github.com/lstepnio/Emviary-firmware/releases" in page
    assert '<option value="automatic" selected>Automatic</option>' in page
    url = "/manage/frames/test-frame/settings"
    data = {
        "csrf": csrf,
        "wake": "03:15",
        "max_birds": "3",
        "preset": "balanced",
        "dither": "stucki",
        "firmware_updates": "manual",
        "firmware_pinned_version": "v0.3.1",
    }
    assert client.post(url, data={**data, "csrf": "wrong"}).status_code == 403
    assert client.post(url, data={**data, "firmware_pinned_version": "evil/url"}).status_code == 400
    assert client.post(url, data=data, follow_redirects=False).status_code == 303
    policy = json.loads(service.store.frame(frame[0])["policy"])
    assert policy["firmware_updates"] == "manual"
    assert policy["firmware_pinned_version"] == "v0.3.1"


def test_discovery_cache_and_failure(monkeypatch):
    import httpx

    calls = []
    transport = httpx.MockTransport(
        lambda request: calls.append(request) or httpx.Response(200, json=[release()])
    )
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=transport, **kwargs))
    updates = FirmwareUpdates()
    assert updates.check(FramePolicy(), "v0.3.0")["update_available"]
    assert updates.check(FramePolicy(), "v0.3.0")["update_available"]
    assert len(calls) == 1 and "authorization" not in calls[0].headers
    assert str(calls[0].url).startswith(f"https://api.github.com/repos/{REPOSITORY}/releases")
    updates._expires = 0
    bad = httpx.MockTransport(lambda request: httpx.Response(503))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=bad, **kwargs))
    assert not updates.check(FramePolicy(), "v0.3.0")["update_available"]
