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


def begin_session(client, csrf, frame):
    result = client.post(
        "/manage/usb-recovery/sessions/" + frame[0],
        data={"csrf": csrf, "device_id": "aabbcc001122"},
    )
    assert result.status_code == 200
    return result.json()


def recovery_headers(value, token):
    return {
        "Authorization": "Bearer " + token,
        "X-Firmware-Version": value["expected_firmware"],
        "X-Emviary-Recovery-Session": value["session_id"],
        "X-Emviary-Recovery-Nonce": value["nonce"],
        "X-Emviary-Recovery-Boot": "0123456789abcdef",
        "X-Emviary-Recovery-Device-Id": "aabbcc001122",
        "X-Emviary-Recovery-Bundle-Sha256": value["bundle_sha256"],
    }


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
    session = begin_session(client, csrf, frame)
    payload = {
        "csrf": csrf,
        "ssid": " Gift network ",
        "replace_local_settings": "yes",
        "session_id": session["session_id"],
    }
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
    session = begin_session(client, csrf, frame)
    path = "/manage/usb-recovery/cloud-settings/" + frame[0]
    result = client.post(
        path,
        data={
            "csrf": csrf,
            "replace_local_settings": "yes",
            "ssid": "Home Wi-Fi",
            "password": "new-password-123",
            "session_id": session["session_id"],
        },
    )
    assert result.status_code == 200
    fields = read_nvs(base64.b64decode(result.json()["data"]))
    assert service.store.authenticate(frame[1])
    assert service.store.authenticate(fields["access_token"]) is None
    assert service.store.frame(frame[0]) == before
    token_path = service.settings.data_dir / "provisioning" / (frame[0] + ".token")
    assert not token_path.exists()
    pending_path = token_path.with_name(frame[0] + "." + session["session_id"] + ".pending.token")
    assert pending_path.stat().st_mode & 0o777 == 0o600
    assert pending_path.read_text().strip() == fields["access_token"]
    # Possible USB write followed by cancel does not revoke either usable generation.
    cancelled = client.post(
        "/manage/usb-recovery/sessions/" + frame[0] + "/" + session["session_id"] + "/cancel",
        data={"csrf": csrf},
    )
    assert cancelled.status_code == 200
    service.prepare_due()
    fetched = client.get("/v1/image", headers=recovery_headers(session, fields["access_token"]))
    assert fetched.status_code == 200, fetched.text
    assert service.store.authenticate(frame[1]) is None
    assert service.store.authenticate(fields["access_token"])["id"] == frame[0]
    assert token_path.stat().st_mode & 0o777 == 0o600
    assert token_path.read_text().strip() == fields["access_token"] and not pending_path.exists()
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
    session = begin_session(client, csrf, frame)
    response = client.post(
        "/manage/usb-recovery/cloud-settings/" + frame[0],
        data={
            "csrf": csrf,
            "replace_local_settings": "yes",
            "ssid": "Home",
            "password": "password-123",
            "session_id": session["session_id"],
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


def test_cloud_restore_reuses_unfinished_candidate_without_rotating_again(
    service, frame, tmp_path, monkeypatch
):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    before = service.store.frame(frame[0])
    session = begin_session(client, csrf, frame)
    path = "/manage/usb-recovery/cloud-settings/" + frame[0]
    payload = {
        "csrf": csrf,
        "session_id": session["session_id"],
        "replace_local_settings": "yes",
        "ssid": "Home",
        "password": "password123",
    }
    first = client.post(path, data=payload)
    second = client.post(path, data=payload)
    assert first.status_code == second.status_code == 200
    assert (
        read_nvs(base64.b64decode(first.json()["data"]))["access_token"]
        == read_nvs(base64.b64decode(second.json()["data"]))["access_token"]
    )
    assert service.store.authenticate(frame[1])
    assert service.store.frame(frame[0]) == before


def test_cloud_restore_with_existing_token_stages_changed_network_until_device_proof(
    service, frame, tmp_path, monkeypatch
):
    from emviary.owner import write_private

    client, csrf = sign_in(service, tmp_path, monkeypatch)
    token_path = service.settings.data_dir / "provisioning" / (frame[0] + ".token")
    write_private(token_path, frame[1] + "\n")
    before = service.store.frame(frame[0])
    session = begin_session(client, csrf, frame)
    result = client.post(
        "/manage/usb-recovery/cloud-settings/" + frame[0],
        data={
            "csrf": csrf,
            "session_id": session["session_id"],
            "replace_local_settings": "yes",
            "ssid": "New home",
            "password": "newpassword123",
        },
    )
    assert result.status_code == 200
    assert read_nvs(base64.b64decode(result.json()["data"]))["access_token"] == frame[1]
    assert service.store.frame(frame[0]) == before
    service.prepare_due()
    assert client.get("/v1/image", headers=recovery_headers(session, frame[1])).status_code == 200
    saved = json.loads(service.store.frame(frame[0])["policy"])
    assert saved["wifi_networks"] == [{"ssid": "New home", "password": "newpassword123"}]
    assert token_path.read_text().strip() == frame[1]


def test_cloud_restore_requires_current_session_for_selected_frame(
    service, frame, tmp_path, monkeypatch
):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    path = "/manage/usb-recovery/cloud-settings/" + frame[0]
    payload = {
        "csrf": csrf,
        "replace_local_settings": "yes",
        "ssid": "Home",
        "password": "password123",
    }
    assert client.post(path, data=payload).status_code == 400
    service.store.add_frame("other-frame", service.settings.config.frame_defaults)
    other = begin_session(client, csrf, ("other-frame", ""))
    assert client.post(path, data=dict(payload, session_id=other["session_id"])).status_code == 404
    assert service.store.authenticate(frame[1])


def test_restore_status_prefers_latest_reported_saved_credentialed_network_without_secrets(
    service, frame, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    policy = service.settings.config.frame_defaults.model_copy(
        update={
            "wifi_networks": [
                WifiNetwork(ssid="Open", password=""),
                WifiNetwork(ssid="Home", password="secret-home"),
                WifiNetwork(ssid="Gift", password="secret-gift"),
            ]
        }
    )
    service.store.set_policy(frame[0], policy)
    service.store.device_sample(frame[0], {"ssid": "Gift"}, "v-old")
    # The latest sample may be an update without a repeated network name.
    service.store.device_sample(frame[0], {"free_heap": 123456}, "v-old")
    before = service.store.frame(frame[0])
    response = client.get("/manage/usb-recovery/status/" + frame[0])
    assert response.status_code == 200
    assert response.json()["automatic_restore_ssid"] == "Gift"
    assert response.json()["can_restore_without_input"] is True
    assert "secret-home" not in response.text and "secret-gift" not in response.text
    assert "password" not in response.text and frame[1] not in response.text
    assert service.store.frame(frame[0]) == before
    service.store.device_sample(frame[0], {"ssid": "Open"}, "v-old")
    fallback = client.get("/manage/usb-recovery/status/" + frame[0]).json()
    assert fallback["automatic_restore_ssid"] == "Home" and fallback["can_restore_without_input"]


def test_restore_status_never_offers_unsaved_or_passwordless_profiles(
    service, frame, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    service.store.set_policy(
        frame[0],
        service.settings.config.frame_defaults.model_copy(
            update={"wifi_networks": [WifiNetwork(ssid="Open", password="")]}
        ),
    )
    service.store.device_sample(frame[0], {"ssid": "Device-only network"}, "v-old")
    before = service.store.frame(frame[0])
    result = client.get("/manage/usb-recovery/status/" + frame[0]).json()
    assert result["automatic_restore_ssid"] == "" and result["can_restore_without_input"] is False
    assert service.store.frame(frame[0]) == before
    service.store.set_policy(
        frame[0], service.settings.config.frame_defaults.model_copy(update={"wifi_networks": None})
    )
    result = client.get("/manage/usb-recovery/status/" + frame[0]).json()
    assert result["automatic_restore_ssid"] == "" and result["can_restore_without_input"] is False
