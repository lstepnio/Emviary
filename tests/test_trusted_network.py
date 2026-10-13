import json
from datetime import UTC, datetime, timedelta

import pytest
from starlette.requests import Request

from emviary.store import Store
from emviary.trusted_network import network_session, record_frame_network, source_public_ip

NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)
PUBLIC_IP = "8.8.8.8"


def request(peer=PUBLIC_IP, headers=(), path="/manage"):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "query_string": b"",
            "server": ("example.com", 443),
            "client": (peer, 43210),
            "headers": [(name.encode(), value.encode()) for name, value in headers],
        }
    )


@pytest.fixture
def trusted_frame(service, frame, tmp_path, monkeypatch):
    monkeypatch.delenv("EMVIARY_TRUSTED_PROXY_IPS", raising=False)
    monkeypatch.setenv("EMVIARY_SECRET_DIR", str(tmp_path / "secrets"))
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "owner-auth.json").write_text(
        json.dumps({"hash": "ab" * 32, "salt": "cd" * 16})
    )
    # Keep tests independent of policy-model construction during integration.
    with service.store.connect() as db:
        policy = json.loads(service.store.frame(frame[0])["policy"])
        policy["management_trusted_wan"] = True
        db.execute("UPDATE frames SET policy=? WHERE id=?", (json.dumps(policy), frame[0]))
    return frame


def record(service, frame, peer=PUBLIC_IP, now=NOW, extra_headers=()):
    record_frame_network(
        request(peer, [("authorization", "Bearer " + frame[1]), *extra_headers], "/v1/image"),
        service,
        service.store.frame(frame[0]),
        now=now,
    )


def test_matching_wan_is_request_local_and_revalidated(service, trusted_frame):
    record(service, trusted_frame)
    session = network_session(request(), service, now=NOW)
    assert session and set(session) == {"csrf", "network_access"}
    assert PUBLIC_IP not in json.dumps(session)
    assert session == network_session(request(), service, now=NOW)
    assert not network_session(request("1.1.1.1"), service, now=NOW)
    record(service, trusted_frame, peer="1.1.1.1")
    assert not network_session(request(), service, now=NOW)
    assert network_session(request("1.1.1.1"), service, now=NOW)
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM owner_sessions").fetchone()[0] == 0


def test_opt_out_and_stale_or_future_contact_denied(service, trusted_frame):
    record(service, trusted_frame)
    assert network_session(request(), service, now=NOW + timedelta(hours=48))
    assert not network_session(request(), service, now=NOW + timedelta(hours=48, seconds=1))
    assert not network_session(request(), service, now=NOW - timedelta(seconds=1))
    with service.store.connect() as db:
        db.execute("UPDATE frames SET policy='{}' WHERE id=?", (trusted_frame[0],))
    assert not network_session(request(), service, now=NOW)


def test_csrf_rotates_by_day_and_password(service, trusted_frame, tmp_path):
    record(service, trusted_frame)
    first = network_session(request(), service, now=NOW)["csrf"]
    assert network_session(request(), service, now=NOW + timedelta(days=1))["csrf"] != first
    path = tmp_path / "secrets" / "owner-auth.json"
    path.write_text(json.dumps({"hash": "ef" * 32}))
    assert network_session(request(), service, now=NOW)["csrf"] != first
    path.unlink()
    assert not network_session(request(), service, now=NOW)


def test_only_authentic_image_requests_record(service, trusted_frame):
    for path, token in [("/v1/image", "bad"), ("/manage", trusted_frame[1])]:
        record_frame_network(
            request(headers=[("authorization", "Bearer " + token)], path=path),
            service,
            service.store.frame(trusted_frame[0]),
            now=NOW,
        )
    assert not service.store.frame_network_contacts()
    assert not network_session(request(), service, now=NOW)
    record(service, trusted_frame)
    original = service.store.frame_network_contacts()
    record_frame_network(
        request("1.1.1.1", [("authorization", "Bearer bad")], "/v1/image"),
        service,
        service.store.frame(trusted_frame[0]),
        now=NOW,
    )
    assert service.store.frame_network_contacts() == original


def test_contact_table_is_additive_and_persists(service, trusted_frame):
    before = service.store.frame(trusted_frame[0])
    record(service, trusted_frame)
    reopened = Store(service.store.path)
    assert reopened.frame(trusted_frame[0]) == before
    assert reopened.frame_network_contacts() == service.store.frame_network_contacts()


def test_authentication_cannot_record_another_frame(service, trusted_frame):
    service.store.add_frame("second-frame", service.settings.config.frame_defaults)
    record_frame_network(
        request(headers=[("authorization", "Bearer " + trusted_frame[1])], path="/v1/image"),
        service,
        service.store.frame("second-frame"),
        now=NOW,
    )
    assert not service.store.frame_network_contacts()


@pytest.mark.parametrize(
    "peer",
    [
        "127.0.0.1",
        "192.168.1.2",
        "10.0.0.1",
        "100.64.0.1",
        "169.254.1.2",
        "192.0.2.1",
        "0.0.0.0",
        "224.0.0.1",
        "240.1.2.3",
        "::1",
        "fe80::1",
        "fd00::1",
        "ff02::1",
        "2001:db8::1",
        "::",
        "bad",
        "8.8.8.8:123",
        "fe80::1%eth0",
    ],
)
def test_non_public_sources_cannot_be_spoofed(peer, monkeypatch):
    monkeypatch.delenv("EMVIARY_TRUSTED_PROXY_IPS", raising=False)
    assert source_public_ip(request(peer, [("x-forwarded-for", PUBLIC_IP)])) is None


def test_untrusted_forward_headers_are_ignored(monkeypatch):
    monkeypatch.delenv("EMVIARY_TRUSTED_PROXY_IPS", raising=False)
    assert source_public_ip(request("1.1.1.1", [("x-forwarded-for", PUBLIC_IP)])) == "1.1.1.1"
    assert source_public_ip(request("::ffff:8.8.8.8")) == PUBLIC_IP
    assert source_public_ip(request("2606:4700:4700::1111")) == "2606:4700:4700::1111"


def test_explicit_proxy_trust_walks_from_right_and_fails_closed(monkeypatch):
    monkeypatch.setenv("EMVIARY_TRUSTED_PROXY_IPS", "172.18.0.5/32")
    assert source_public_ip(request("172.18.0.5", [("x-forwarded-for", PUBLIC_IP)])) == PUBLIC_IP
    assert (
        source_public_ip(
            request(
                "172.18.0.5",
                [
                    ("x-forwarded-for", PUBLIC_IP + ", 1.1.1.1"),
                ],
            )
        )
        == "1.1.1.1"
    )
    for value in ["", "bad", PUBLIC_IP + ", 192.168.1.2", "172.18.0.5", "8.8.8.8:443"]:
        assert source_public_ip(request("172.18.0.5", [("x-forwarded-for", value)])) is None
    assert (
        source_public_ip(
            request(
                "172.18.0.5",
                [
                    ("x-forwarded-for", PUBLIC_IP),
                    ("x-forwarded-for", "1.1.1.1"),
                ],
            )
        )
        is None
    )
    assert source_public_ip(request("172.18.0.6", [("x-forwarded-for", PUBLIC_IP)])) is None
    monkeypatch.setenv("EMVIARY_TRUSTED_PROXY_IPS", "172.18.0.5/32,bad")
    assert source_public_ip(request("172.18.0.5", [("x-forwarded-for", PUBLIC_IP)])) is None


def test_repeat_contacts_write_hourly_but_network_changes_write_immediately(service, trusted_frame):
    record(service, trusted_frame)
    record(service, trusted_frame, now=NOW + timedelta(minutes=59))
    assert service.store.frame_network_contacts()[0]["authenticated_at"] == NOW.isoformat()
    record(service, trusted_frame, now=NOW + timedelta(hours=1))
    assert (
        service.store.frame_network_contacts()[0]["authenticated_at"]
        == (NOW + timedelta(hours=1)).isoformat()
    )
    record(service, trusted_frame, peer="1.1.1.1", now=NOW + timedelta(hours=1, minutes=1))
    assert service.store.frame_network_contacts()[0]["public_ip"] == "1.1.1.1"
    record(service, trusted_frame, peer="192.168.1.2")
    assert not service.store.frame_network_contacts()
