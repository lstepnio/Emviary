import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_owner import sign_in

from emviary.api import config_payload, create_app
from emviary.render import profile_hash
from emviary.settings import FramePolicy


def test_wifi_validation_and_header_bounds():
    original = FramePolicy()
    assert (
        "wifi_networks"
        not in json.loads(config_payload({"policy": original.model_dump_json()}))["config"]
    )
    networks = [{"ssid": "😀" * 8 + str(i), "password": "a" * 63} for i in range(5)]
    # SSID byte length, not Python character count, is the device constraint.
    with pytest.raises(ValidationError):
        FramePolicy(wifi_networks=networks)
    networks = [{"ssid": "😀" * 7 + str(i), "password": "a" * 63} for i in range(5)]
    policy = FramePolicy(wifi_networks=networks)
    payload = config_payload({"policy": policy.model_dump_json()})
    assert len(payload.encode("ascii")) < 1900
    assert json.loads(payload)["config"]["wifi_networks"] == networks
    assert profile_hash(policy.model_dump(), {}) == profile_hash(original.model_dump(), {})
    assert json.loads(payload)["config"]["wifi_keep_existing"] is True
    assert FramePolicy(wifi_networks=[])
    for invalid in (
        [{"ssid": "same", "password": ""}] * 2,
        [{"ssid": "x", "password": ""}] * 6,
        [{"ssid": "a\n", "password": ""}],
        [{"ssid": "x", "password": "short"}],
        [{"ssid": "x", "password": "é" * 8}],
    ):
        with pytest.raises(ValidationError):
            FramePolicy(wifi_networks=invalid)
    assert FramePolicy(wifi_networks=[{"ssid": "x", "password": "f" * 64}])


def test_wifi_auth_management_and_secret_isolation(service, frame, tmp_path, monkeypatch):
    url = "/manage/frames/test-frame/wifi"
    anonymous = TestClient(
        create_app(service, schedule=False), base_url="https://emviary.majjix.com"
    )
    assert (
        anonymous.post(
            url, data={"ssid": "Gift", "password": "private-password", "action": "save"}
        ).status_code
        == 401
    )
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    data = {"csrf": csrf, "ssid": "Home", "password": "private-password", "action": "save"}
    assert client.post(url, data={**data, "csrf": "wrong"}).status_code == 403
    assert client.post(url, data=data, follow_redirects=False).status_code == 303
    assert (
        client.post(url, data={**data, "password": ""}, follow_redirects=False).status_code == 303
    )
    policy = json.loads(service.store.frame(frame[0])["policy"])
    assert policy["wifi_networks"][0]["password"] == "private-password"
    assert "private-password" not in client.get("/manage").text
    assert "private-password" not in json.dumps(service.status())
    assert (
        client.post(
            url,
            data={**data, "ssid": "Guest", "password": "", "open": "on"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert client.post(url, data={**data, "ssid": "Missing", "password": ""}).status_code == 400
    assert (
        client.post(url, data={**data, "action": "remove"}, follow_redirects=False).status_code
        == 303
    )
    assert (
        client.post(
            url, data={**data, "ssid": "Guest", "action": "remove"}, follow_redirects=False
        ).status_code
        == 303
    )
    policy = json.loads(service.store.frame(frame[0])["policy"])
    assert policy["wifi_networks"] == []
    payload = json.loads(config_payload({"policy": json.dumps(policy)}))["config"]
    assert payload["wifi_keep_existing"] is True
    assert payload["wifi_forget_ssids"] == ["Home", "Guest"]
    client.post(url, data=data)
    policy = json.loads(service.store.frame(frame[0])["policy"])
    assert policy["wifi_forget_ssids"] == ["Guest"]
    service.prepare(frame[0], "2026-10-08", offline=True)
    record = service.store.active_image(service.store.frame(frame[0]))
    assert "private-password" not in record["manifest"]
    assert "wifi_networks" not in json.loads(record["manifest"])["policy"]
    assert "wifi_forget_ssids" not in json.loads(record["manifest"])["policy"]
    assert client.get("/v1/image").status_code == 401
    response = client.get("/v1/image", headers={"Authorization": "Bearer " + frame[1]})
    assert response.status_code == 200
    assert (
        json.loads(response.headers["X-Config-Payload"])["config"]["wifi_networks"][0]["password"]
        == "private-password"
    )
    for path in ("/", "/library"):
        assert "private-password" not in anonymous.get(path).text
