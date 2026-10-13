import base64
import hashlib
import json
import struct
import zlib
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from test_owner import sign_in

from emviary.api import create_app
from emviary.settings import FramePolicy, WifiNetwork
from emviary.usb_recovery import recovery_manifest


def read_nvs(data):
    """Independent NVS entry/CRC inspection, rather than calling the writer's reader."""
    assert len(data) == 0x6000 and data[-4096:] == b"\xff" * 4096
    fields = {}
    for page in range(0, len(data), 4096):
        if data[page : page + 32] == b"\xff" * 32:
            continue
        assert data[page + 8] == 0xFE
        index = 64
        while index < 4096:
            entry = data[page + index : page + index + 32]
            if entry == b"\xff" * 32:
                break
            assert (
                zlib.crc32(entry[:4] + entry[8:], 0xFFFFFFFF) == struct.unpack("<I", entry[4:8])[0]
            )
            key = entry[8:24].split(b"\0")[0].decode()
            if entry[1] == 0x21:
                size = struct.unpack("<H", entry[24:26])[0]
                value = data[page + index + 32 : page + index + 32 + size]
                assert zlib.crc32(value, 0xFFFFFFFF) == struct.unpack("<I", entry[28:32])[0]
                fields[key] = value[:-1].decode()
            else:
                assert entry[1] == 1
                fields[key] = entry[24]
            index += entry[2] * 32
    return fields


def test_cloud_restore_requires_consent_and_csrf_and_preserves_cloud_state(
    service, frame, tmp_path, monkeypatch
):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    path = "/manage/usb-recovery/cloud-settings/" + frame[0]
    assert TestClient(create_app(service, schedule=False)).post(path).status_code == 401
    token_path = service.settings.data_dir / "provisioning" / (frame[0] + ".token")
    token_path.parent.mkdir()
    token_path.write_text(frame[1] + "\n")
    policy = FramePolicy(
        wifi_networks=[WifiNetwork(ssid=" Gift network ", password="saved-pw-123")]
    )
    service.store.set_policy(frame[0], policy)
    before = service.store.frame(frame[0])["policy"]
    payload = {"csrf": csrf, "ssid": " Gift network ", "replace_local_settings": "yes"}
    assert client.post(path, data={**payload, "csrf": "bad"}).status_code == 403
    assert client.post(path, data={**payload, "replace_local_settings": "no"}).status_code == 400
    assert (
        client.post(path, data=payload, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    result = client.post(path, data=payload)
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    value = result.json()
    assert value["address"] == 0x9000 and value["size"] == 0x6000
    binary = base64.b64decode(value["data"])
    assert hashlib.sha256(binary).hexdigest() == value["sha256"]
    fields = read_nvs(binary)
    assert fields["wifi_ssid"] == " Gift network " and fields["wifi_pass"] == "saved-pw-123"
    assert fields["access_token"] == frame[1]
    assert fields["image_url"] == service.settings.config.public_base_url + "/v1/image"
    assert fields["http_password"] == value["local_password"] and len(value["local_password"]) == 24
    assert fields["debug_log"] == 0 and fields["rotation_mode"] == 1 and fields["deep_sleep"] == 1
    assert service.store.frame(frame[0])["policy"] == before
    assert token_path.read_text() == frame[1] + "\n"


def test_missing_device_token_is_rebound_without_owner_cli(service, frame, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    before = service.store.frame(frame[0])
    path = "/manage/usb-recovery/cloud-settings/" + frame[0]
    result = client.post(
        path,
        data={
            "csrf": csrf,
            "replace_local_settings": "yes",
            "ssid": "Home Wi-Fi",
            "password": "new-password-123",
        },
    )
    assert result.status_code == 200
    fields = read_nvs(base64.b64decode(result.json()["data"]))
    assert service.store.authenticate(frame[1]) is None
    assert service.store.authenticate(fields["access_token"])["id"] == frame[0]
    token_path = service.settings.data_dir / "provisioning" / (frame[0] + ".token")
    assert token_path.stat().st_mode & 0o777 == 0o600
    assert token_path.read_text().strip() == fields["access_token"]
    after = service.store.frame(frame[0])
    policy = json.loads(after["policy"])
    original = json.loads(before["policy"])
    assert {k: v for k, v in policy.items() if k != "wifi_networks"} == {
        k: v for k, v in original.items() if k != "wifi_networks"
    }
    assert policy["wifi_networks"] == [{"ssid": "Home Wi-Fi", "password": "new-password-123"}]


def test_failed_preparation_never_changes_binding_or_policy(service, frame, tmp_path, monkeypatch):
    from emviary import recovery_nvs

    client, csrf = sign_in(service, tmp_path, monkeypatch)
    before = service.store.frame(frame[0])

    def fail(config):
        raise RuntimeError("Preparation unavailable")

    monkeypatch.setattr(recovery_nvs, "build", fail)
    response = client.post(
        "/manage/usb-recovery/cloud-settings/" + frame[0],
        data={
            "csrf": csrf,
            "replace_local_settings": "yes",
            "ssid": "Home",
            "password": "password-123",
        },
    )
    assert response.status_code == 503
    assert service.store.frame(frame[0]) == before
    assert service.store.authenticate(frame[1])
    assert not (service.settings.data_dir / "provisioning" / (frame[0] + ".token")).exists()


def test_verification_requires_target_frame_fresh_contact_and_expected_firmware(
    service, frame, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    other = service.store.add_frame("other-frame", service.settings.config.frame_defaults)
    path = "/manage/usb-recovery/status/" + frame[0]
    since = client.get(path).json()["checked_at"]
    service.store.device_sample(frame[0], {"ssid": "Home"}, "v0.8.1")
    service.store.device_sample("other-frame", {"ssid": "Home"}, recovery_manifest()["version"])
    assert not client.get(path, params={"since": since}).json()["connected"]
    service.store.device_sample(frame[0], {"ssid": "Home"}, recovery_manifest()["version"])
    result = client.get(path, params={"since": since})
    assert result.json()["connected"] and result.headers["cache-control"] == "no-store"
    assert "token" not in result.text and "local_ip" not in result.text
    assert not client.get(path).json()["connected"]
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert client.get(path, params={"since": future}).status_code == 400
    assert other
