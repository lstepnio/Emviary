import re

from fastapi.testclient import TestClient
from test_owner import sign_in

from emviary.api import config_payload, create_app
from emviary.settings import FramePolicy


def test_matching_frame_network_skips_password_without_cookie_and_remains_revocable(
    service, frame, tmp_path, monkeypatch
):
    owner, _ = sign_in(service, tmp_path, monkeypatch)
    policy = service.settings.config.frame_defaults.model_copy(
        update={"management_trusted_wan": True}
    )
    service.store.set_policy(frame[0], policy)
    service.prepare(frame[0], offline=True)
    app = create_app(service, schedule=False)
    local = TestClient(app, base_url="https://emviary.majjix.com", client=("8.8.8.8", 443))
    other = TestClient(app, base_url="https://emviary.majjix.com", client=("8.8.4.4", 443))
    assert local.get("/manage/session").status_code == 401
    assert (
        local.get("/v1/image", headers={"Authorization": "Bearer " + frame[1]}).status_code == 200
    )
    result = local.get("/manage/settings?frame=" + frame[0])
    assert result.status_code == 200 and "set-cookie" not in result.headers
    assert "Management access" in result.text
    assert other.get("/manage/session", headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 401
    csrf = re.search(r'name="csrf" value="([^"]+)"', result.text).group(1)
    assert (
        local.post(
            "/manage/password", data={"csrf": csrf, "password": "a-new-long-password-value"}
        ).status_code
        == 403
    )
    endpoint = "/manage/frames/test-frame/management-access"
    assert local.post(endpoint, data={"csrf": "wrong"}).status_code == 403
    assert (
        local.post(
            endpoint, data={"csrf": csrf}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert local.post(endpoint, data={"csrf": csrf}, follow_redirects=False).status_code == 303
    assert local.get("/manage/session").status_code == 401
    # The normal password session still works from another network.
    assert owner.get("/manage").status_code == 200


def test_cloud_debug_setting_is_off_by_default_and_does_not_send_management_trust_to_frame():
    import json

    config = json.loads(config_payload({"policy": FramePolicy().model_dump_json()}))["config"]
    assert config["debug_log_enabled"] is False
    assert "management_trusted_wan" not in config
    config = json.loads(
        config_payload(
            {
                "policy": FramePolicy(
                    firmware_debug_logging=True, management_trusted_wan=True
                ).model_dump_json()
            }
        )
    )["config"]
    assert config["debug_log_enabled"] is True
    assert "management_trusted_wan" not in config


def test_hairpin_management_authentication_is_revocable_and_does_not_issue_a_cookie(
    service, frame, tmp_path, monkeypatch
):
    sign_in(service, tmp_path, monkeypatch)
    monkeypatch.setenv("EMVIARY_TRUSTED_PROXY_IPS", "172.18.0.5/32")
    monkeypatch.setenv("EMVIARY_TRUSTED_LOCAL_IPS", "192.168.10.1")
    service.store.set_policy(frame[0], FramePolicy(management_trusted_wan=True))
    service.prepare(frame[0], offline=True)
    app = create_app(service, schedule=False)
    local = TestClient(app, base_url="https://emviary.majjix.com", client=("172.18.0.5", 443))
    headers = {"X-Forwarded-For": "192.168.10.1"}
    assert local.get("/manage/session", headers=headers).status_code == 401
    assert (
        local.get(
            "/v1/image", headers={**headers, "Authorization": "Bearer " + frame[1]}
        ).status_code
        == 200
    )
    session = local.get("/manage/session", headers=headers)
    assert session.status_code == 200 and "set-cookie" not in session.headers
    csrf = session.json()["csrf"]
    assert (
        local.get("/manage", headers={"X-Forwarded-For": "192.168.10.2"}).url.path
        == "/manage/login"
    )
    assert (
        local.get(
            "/manage/session", headers={"X-Forwarded-For": "192.168.10.1, 1.1.1.1"}
        ).status_code
        == 401
    )
    assert (
        local.post(
            "/manage/frames/test-frame/management-access",
            headers=headers,
            data={"csrf": csrf},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert local.get("/manage/session", headers=headers).status_code == 401
