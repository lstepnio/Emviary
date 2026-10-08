import re

from fastapi.testclient import TestClient

from emviary.api import create_app
from emviary.owner import set_password
from emviary.service import Service


def sign_in(service, tmp_path, monkeypatch):
    directory = tmp_path / "secrets"
    directory.mkdir()
    monkeypatch.setenv("EMVIARY_SECRET_DIR", str(directory))
    set_password("a-long-test-owner-password")
    client = TestClient(create_app(service, schedule=False), base_url="https://emviary.majjix.com")
    response = client.get("/manage/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)
    response = client.post(
        "/manage/login",
        data={"csrf": csrf, "password": "a-long-test-owner-password"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    response = client.get("/manage")
    csrf = re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)
    return client, csrf


def test_owner_auth_csrf_and_persistent_settings(service, frame, tmp_path, monkeypatch):
    anonymous = TestClient(
        create_app(service, schedule=False), base_url="https://emviary.majjix.com"
    )
    assert anonymous.get("/manage", follow_redirects=False).status_code == 303
    assert anonymous.get("/manage/frames/test-frame/preview").status_code == 401
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    url = "/manage/frames/test-frame/settings"
    data = {
        "csrf": csrf,
        "wake": "04:10",
        "max_birds": "1",
        "preset": "soft",
        "dither": "stucki",
        "labels": "on",
        "weather": "on",
    }
    assert client.post(url, data={**data, "csrf": "wrong"}).status_code == 403
    assert (
        client.post(url, data=data, headers={"Origin": "https://wrong.example"}).status_code == 403
    )
    assert client.post(url, data=data, follow_redirects=False).status_code == 303
    import json

    policy = json.loads(service.store.frame(frame[0])["policy"])
    assert policy["firmware_rotate_cron"] == ["10 4 *"] and policy["max_birds"] == 1
    config = service.settings.config.model_dump()
    config["public_frame_id"] = frame[0]
    config["sites"][0]["locality_radius_km"] = 12
    service.save_configuration(config)
    restarted = Service(service.settings, providers=service.providers, converter=service.converter)
    assert restarted.settings.config.sites[0].locality_radius_km == 12
    assert restarted.settings.config.public_frame_id == frame[0]
    assert "a-long-test-owner-password" not in client.get("/manage").text
    assert (
        client.post("/manage/logout", data={"csrf": csrf}, follow_redirects=False).status_code
        == 303
    )
    assert client.get("/manage", follow_redirects=False).status_code == 303


def test_public_mirror_tracks_device_delivery_not_preparation(service, frame):
    config = service.settings.config.model_dump()
    config["public_frame_id"] = frame[0]
    service.save_configuration(config)
    first = service.prepare(frame[0], "2026-10-08", offline=True)
    client = TestClient(create_app(service, schedule=False))
    headers = {"Authorization": "Bearer " + frame[1], "X-Firmware-Version": "v2.19.0"}
    assert client.get("/v1/image", headers=headers).status_code == 200
    old = client.get("/display.jpg").content
    service.prepare(frame[0], "2026-10-08", force=True, offline=True)
    assert client.get("/display.jpg").content == old
    assert (
        client.get("/v1/image", headers={"Authorization": headers["Authorization"]}).status_code
        == 200
    )
    assert client.get("/display.jpg").content == old
    assert client.get("/v1/image", headers=headers).status_code == 200
    assert service.delivered_image(service.store.frame(frame[0]))["id"] != first["id"]
    assert client.get("/display.jpg").content != old


def test_owner_add_and_provision_keep_tokens_private(service, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    response = client.post(
        "/manage/add-frame",
        data={"csrf": csrf, "id": "new-frame", "site": "denver-gift"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    response = client.get("/manage/frames/new-frame/provision")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    config = response.json()
    assert service.store.authenticate(config["access_token"])["id"] == "new-frame"
    assert config["access_token"] not in client.get("/manage").text
    recovery = client.get("/manage/frames/new-frame/provision?import_file=true")
    assert recovery.status_code == 200
    assert recovery.headers["cache-control"] == "no-store"
    assert recovery.json()["config"]["access_token"] == config["access_token"]
    assert recovery.json()["config"]["image_url"] == config["image_url"]
    assert not any(k.startswith("wifi_") for k in recovery.json()["config"])
    assert "Frame recovery and Wi-Fi setup" in client.get("/manage").text
    assert "PhotoFrame - XXXXX" in client.get("/manage").text
    assert "Settings → Maintenance → Config Backup" in client.get("/manage").text
    response = client.post(
        "/manage/ebird-key",
        data={"csrf": csrf, "key": "a-new-test-ebird-key"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert (tmp_path / "secrets/ebird-api-key").read_text().strip() == "a-new-test-ebird-key"
    assert "a-new-test-ebird-key" not in client.get("/manage").text
