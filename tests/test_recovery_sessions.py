import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_owner import sign_in

from emviary.api import create_app
from emviary.recovery_sessions import MAX_EVENTS, RecoverySessions
from emviary.store import RevisionConflict


@pytest.fixture
def sessions(service):
    return RecoverySessions(service.store)


def session(sessions, frame):
    return sessions.create(frame[0], {"version": "v-test", "parts": []}, "aabbcc001122")


def challenge(value, **extra):
    return dict(
        session_id=value["session_id"],
        nonce=value["nonce"],
        boot_id="0123456789abcdef",
        device_id="aabbcc001122",
        firmware="v-test",
        bundle_sha256=value["bundle_sha256"],
        **extra,
    )


def test_session_lease_conflict_expiry_and_settings_guard(service, frame, sessions):
    now = datetime.now(UTC)
    sessions.clock = lambda: now
    value = session(sessions, frame)
    with pytest.raises(HTTPException) as caught:
        session(sessions, frame)
    assert caught.value.status_code == 409
    policy = service.settings.config.frame_defaults
    with pytest.raises(RevisionConflict):
        service.store.set_policy(frame[0], policy)
    sessions.clock = lambda: now + timedelta(seconds=91)
    replacement = session(sessions, frame)
    assert replacement["session_id"] != value["session_id"]
    assert sessions.get(frame[0], value["session_id"])["state"] == "superseded"
    with pytest.raises(HTTPException):
        sessions.renew(frame[0], value["session_id"])


def test_only_correlated_complete_image_and_panel_can_finish(service, frame, sessions):
    value = session(sessions, frame)
    data = challenge(value)
    for key, wrong in (
        ("nonce", "wrong"),
        ("firmware", "old"),
        ("device_id", "aabbcc001199"),
        ("bundle_sha256", "a" * 64),
    ):
        with pytest.raises(HTTPException):
            sessions.image_requested(
                service.store.frame(frame[0]),
                dict(data, **{key: wrong}),
                {"id": 1, "body_hash": "b" * 64},
                frame[1],
            )
    sessions.image_requested(
        service.store.frame(frame[0]), data, {"id": 1, "body_hash": "b" * 64}, frame[1]
    )
    with pytest.raises(HTTPException):
        sessions.finish(frame[0], value["session_id"], True)
    for changed in ({"boot_id": "0123456789abcdee"}, {"image_sha256": "c" * 64}):
        with pytest.raises(HTTPException):
            sessions.acknowledge(
                service.store.frame(frame[0]),
                dict(data, phase="image_verified", image_sha256="b" * 64, **changed)
                if "image_sha256" not in changed
                else dict(data, phase="image_verified", **changed),
            )
    with pytest.raises(HTTPException):
        sessions.acknowledge(
            service.store.frame(frame[0]),
            dict(data, phase="panel_refreshed", image_sha256="b" * 64),
        )
    for phase in ("image_verified", "panel_refreshed"):
        sessions.acknowledge(
            service.store.frame(frame[0]), dict(data, phase=phase, image_sha256="b" * 64)
        )
    assert sessions.finish(frame[0], value["session_id"], True)["state"] == "completed"
    service.store.set_policy(frame[0], service.settings.config.frame_defaults)


def test_pending_binding_survives_interrupt_and_activates_only_after_exact_fetch(
    service, frame, sessions
):
    value = session(sessions, frame)
    current = service.store.frame(frame[0])
    policy = service.settings.config.frame_defaults.model_copy(update={"name": "Restored"})
    token = "new-test-token"
    sessions.stage_binding(current, policy, token, value["session_id"])
    assert service.store.authenticate(frame[1])
    assert service.store.authenticate(token) is None
    assert sessions.authenticate(token, value["session_id"], "wrong") is None
    pending = sessions.authenticate(token, value["session_id"], value["nonce"])
    assert pending and pending["config_revision"] == current["config_revision"] + 1
    assert service.store.frame(frame[0])["policy"] == current["policy"]
    with pytest.raises(HTTPException):
        sessions.image_requested(
            pending,
            dict(challenge(value), device_id="aabbcc001199"),
            {"id": 1, "body_hash": "b" * 64},
            token,
        )
    assert service.store.authenticate(frame[1])
    sessions.image_requested(pending, challenge(value), {"id": 1, "body_hash": "b" * 64}, token)
    assert service.store.authenticate(frame[1]) is None
    assert service.store.authenticate(token)
    # Repeated fetch cannot rotate twice.
    sessions.image_requested(
        service.store.frame(frame[0]), challenge(value), {"id": 1, "body_hash": "b" * 64}, token
    )
    assert service.store.frame(frame[0])["config_revision"] == current["config_revision"] + 1


def test_checkpoint_redaction_and_bounds(frame, sessions):
    value = session(sessions, frame)
    for bad in (
        {"password": "secret"},
        {"operation": "raw serial text"},
        {"elapsed_ms": -1},
        {"evidence": {"token": "secret"}},
    ):
        with pytest.raises(HTTPException):
            sessions.event(frame[0], value["session_id"], bad)
    for _ in range(MAX_EVENTS):
        sessions.event(frame[0], value["session_id"], {"state": "booted"})
    with pytest.raises(HTTPException) as caught:
        sessions.event(frame[0], value["session_id"], {"state": "booted"})
    assert caught.value.status_code == 429
    assert len(sessions.get(frame[0], value["session_id"])["events"]) == MAX_EVENTS


def test_owner_routes_require_authentication_and_csrf(service, frame, tmp_path, monkeypatch):
    base = "/manage/usb-recovery/sessions/" + frame[0]
    anonymous = TestClient(create_app(service, schedule=False))
    assert anonymous.post(base).status_code == 401
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    assert client.post(base, data={"csrf": "wrong"}).status_code == 403
    created = client.post(base, data={"csrf": csrf, "device_id": "aabbcc001122"})
    assert created.status_code == 200
    value = created.json()
    assert "token" not in json.dumps(value)
    path = base + "/" + value["session_id"]
    assert client.get(path).status_code == 200
    assert anonymous.get(path).status_code == 401
    assert client.post(path + "/renew", data={"csrf": csrf}).status_code == 200
    assert (
        client.post(
            path + "/complete", data={"csrf": csrf, "physical_confirmed": "yes"}
        ).status_code
        == 409
    )
    assert client.post(path + "/cancel", data={"csrf": csrf}).json()["state"] == "cancelled"


def test_recovery_image_and_ack_are_separate_positive_evidence(service, frame):
    service.prepare_due()
    sessions = RecoverySessions(service.store)
    value = session(sessions, frame)
    data = challenge(value)
    headers = {"Authorization": "Bearer " + frame[1], "X-Firmware-Version": "v-test"}
    for key, suffix in (
        ("session_id", "Session"),
        ("nonce", "Nonce"),
        ("boot_id", "Boot"),
        ("device_id", "Device-Id"),
        ("bundle_sha256", "Bundle-Sha256"),
    ):
        headers["X-Emviary-Recovery-" + suffix] = data[key]
    client = TestClient(create_app(service, schedule=False))
    ordinary = client.get("/v1/image", headers={"Authorization": "Bearer " + frame[1]})
    assert ordinary.status_code == 200
    response = client.get(
        "/v1/image", headers=dict(headers, **{"If-None-Match": ordinary.headers["etag"]})
    )
    assert response.status_code == 200
    assert response.headers["x-recovery-image-sha256"]
    assert "cloud_requested" in sessions.get(frame[0], value["session_id"])["evidence"]
    assert "image_verified" not in sessions.get(frame[0], value["session_id"])["evidence"]
    for phase in ("image_verified", "panel_refreshed"):
        ack = client.post(
            "/v1/recovery/ack",
            headers=headers,
            json=dict(data, phase=phase, image_sha256=response.headers["x-recovery-image-sha256"]),
        )
        assert ack.status_code == 200, ack.text
    assert sessions.finish(frame[0], value["session_id"], True)["state"] == "completed"
    assert client.post("/v1/recovery/ack", headers=headers, content="x" * 2049).status_code == 413


def test_staged_policy_same_token_cancellation_expiry_and_store_restart(service, frame, sessions):
    from emviary.store import Store

    value = session(sessions, frame)
    original = service.store.frame(frame[0])
    sessions.stage_binding(
        original, service.settings.config.frame_defaults, frame[1], value["session_id"]
    )
    reloaded = RecoverySessions(Store(service.store.path))
    pending = reloaded.authenticate(frame[1], value["session_id"], value["nonce"])
    assert pending["config_revision"] == original["config_revision"] + 1
    assert service.store.authenticate(frame[1])["config_revision"] == original["config_revision"]
    sessions.finish(frame[0], value["session_id"], cancel=True)
    assert reloaded.authenticate(frame[1], value["session_id"], value["nonce"])
    assert service.store.authenticate(frame[1])
    # Cancellation releases the lease while preserving a potentially written credential.
    sessions.image_requested(
        reloaded.authenticate(frame[1], value["session_id"], value["nonce"]),
        challenge(value),
        {"id": 1, "body_hash": "b" * 64},
        frame[1],
    )
    replacement = session(sessions, frame)
    sessions.stage_binding(
        service.store.frame(frame[0]),
        service.settings.config.frame_defaults,
        "pending-expiring-token",
        replacement["session_id"],
    )
    sessions.clock = lambda: datetime.now(UTC) + timedelta(hours=25)
    assert (
        sessions.authenticate(
            "pending-expiring-token", replacement["session_id"], replacement["nonce"]
        )
        is None
    )
    assert service.store.authenticate(frame[1])


def test_binding_compare_and_set_preserves_concurrent_generation(service, frame, sessions):
    value = session(sessions, frame)
    original = service.store.frame(frame[0])
    sessions.stage_binding(
        original, service.settings.config.frame_defaults, "pending-token", value["session_id"]
    )
    pending = sessions.authenticate("pending-token", value["session_id"], value["nonce"])
    with service.store.connect() as db:
        db.execute("UPDATE frames SET config_revision=config_revision+1 WHERE id=?", (frame[0],))
    with pytest.raises(HTTPException):
        sessions.image_requested(
            pending, challenge(value), {"id": 1, "body_hash": "b" * 64}, "pending-token"
        )
    assert service.store.authenticate(frame[1])
    assert service.store.authenticate("pending-token") is None


def test_cancel_after_possible_nvs_write_accepts_late_exact_handoff(service, frame, sessions):
    value = session(sessions, frame)
    sessions.stage_binding(
        service.store.frame(frame[0]),
        service.settings.config.frame_defaults,
        "new-written-token",
        value["session_id"],
    )
    sessions.finish(frame[0], value["session_id"], cancel=True)
    assert sessions.get(frame[0], value["session_id"])["pending_binding"]
    pending = sessions.authenticate("new-written-token", value["session_id"], value["nonce"])
    assert pending and service.store.authenticate(frame[1])
    assert sessions.authenticate("new-written-token", value["session_id"], "wrong") is None
    sessions.image_requested(
        pending, challenge(value), {"id": 1, "body_hash": "b" * 64}, "new-written-token"
    )
    assert service.store.authenticate("new-written-token")
    assert service.store.authenticate(frame[1]) is None
    for phase in ("image_verified", "panel_refreshed"):
        sessions.acknowledge(
            service.store.frame(frame[0]),
            dict(challenge(value), phase=phase, image_sha256="b" * 64),
        )


def test_new_session_preserves_exact_old_pending_but_cannot_replace_it(service, frame, sessions):
    first = session(sessions, frame)
    sessions.stage_binding(
        service.store.frame(frame[0]),
        service.settings.config.frame_defaults,
        "possibly-written-token",
        first["session_id"],
    )
    sessions.finish(frame[0], first["session_id"], cancel=True)
    second = session(sessions, frame)
    assert second["session_id"] == first["session_id"]
    assert second["nonce"] == first["nonce"] and second["state"] == "active"
    assert second["pending_binding"]["session_id"] == first["session_id"]
    with pytest.raises(HTTPException) as caught:
        sessions.stage_binding(
            service.store.frame(frame[0]),
            service.settings.config.frame_defaults,
            "replacement-token",
            second["session_id"],
        )
    assert caught.value.status_code == 409
    assert service.store.authenticate(frame[1])
    assert sessions.authenticate("possibly-written-token", first["session_id"], first["nonce"])
    with pytest.raises(HTTPException):
        sessions.stage_binding(
            service.store.frame(frame[0]),
            service.settings.config.frame_defaults,
            "different-token",
            first["session_id"],
        )


def test_pending_token_promotion_requires_exact_activated_generation(service, frame, sessions):
    from emviary.owner import write_private
    from emviary.recovery_sessions import promote_pending_token

    value = session(sessions, frame)
    directory = service.settings.data_dir / "provisioning"
    active_path = directory / (frame[0] + ".token")
    pending_path = directory / (frame[0] + "." + value["session_id"] + ".pending.token")
    write_private(active_path, frame[1] + "\n")
    write_private(pending_path, "written-token\n")
    sessions.stage_binding(
        service.store.frame(frame[0]),
        service.settings.config.frame_defaults,
        "written-token",
        value["session_id"],
    )
    assert not promote_pending_token(service, frame[0], value["session_id"])
    assert active_path.read_text().strip() == frame[1] and pending_path.exists()
    sessions.finish(frame[0], value["session_id"], cancel=True)
    pending = sessions.authenticate("written-token", value["session_id"], value["nonce"])
    sessions.image_requested(
        pending, challenge(value), {"id": 1, "body_hash": "b" * 64}, "written-token"
    )
    assert promote_pending_token(service, frame[0], value["session_id"])
    assert active_path.read_text().strip() == "written-token" and not pending_path.exists()
    assert active_path.stat().st_mode & 0o777 == 0o600
    # A stale private file cannot overwrite a newer active database generation.
    write_private(pending_path, frame[1] + "\n")
    assert not promote_pending_token(service, frame[0], value["session_id"])
    assert active_path.read_text().strip() == "written-token"


def test_unresolved_pending_expiry_is_visible_and_retains_current_credential(
    service, frame, sessions
):
    value = session(sessions, frame)
    sessions.stage_binding(
        service.store.frame(frame[0]),
        service.settings.config.frame_defaults,
        "expired-pending",
        value["session_id"],
    )
    sessions.finish(frame[0], value["session_id"], cancel=True)
    sessions.clock = lambda: datetime.now(UTC) + timedelta(hours=25)
    report = sessions.get(frame[0], value["session_id"])
    assert report["pending_binding"]["expired"]
    assert sessions.authenticate("expired-pending", value["session_id"], value["nonce"]) is None
    assert service.store.authenticate(frame[1])
    # After the bounded pending validity, explicitly provisioning the same frame can resume.
    replacement = session(sessions, frame)
    sessions.stage_binding(
        service.store.frame(frame[0]),
        service.settings.config.frame_defaults,
        "next-usb-restore",
        replacement["session_id"],
    )
    assert service.store.authenticate(frame[1])


def test_pending_session_auto_resume_retains_absolute_expiry_and_refuses_new_bundle(
    service, frame, sessions
):
    first = session(sessions, frame)
    sessions.stage_binding(
        service.store.frame(frame[0]),
        service.settings.config.frame_defaults,
        "possibly-written-token",
        first["session_id"],
    )
    sessions.finish(frame[0], first["session_id"], cancel=True)
    for manifest in (
        {"version": "v-next", "parts": []},
        {"version": "v-test", "parts": [{"sha256": "changed"}]},
    ):
        with pytest.raises(HTTPException) as caught:
            sessions.create(frame[0], manifest, "aabbcc001122")
        assert caught.value.status_code == 409
        assert caught.value.detail["code"] == "pending_binding_bundle_mismatch"
        assert caught.value.detail["session_id"] == first["session_id"]
        assert caught.value.detail["expected_firmware"] == "v-test"
    resumed = session(sessions, frame)
    assert resumed["session_id"] == first["session_id"] and resumed["nonce"] == first["nonce"]
    assert resumed["expires_at"] == first["expires_at"]
    assert service.store.authenticate(frame[1])
    pending = sessions.authenticate(
        "possibly-written-token", resumed["session_id"], resumed["nonce"]
    )
    assert pending
    sessions.image_requested(
        pending, challenge(resumed), {"id": 1, "body_hash": "b" * 64}, "possibly-written-token"
    )
    assert service.store.authenticate("possibly-written-token")


def test_pending_session_resume_never_bypasses_a_competing_live_lease(service, frame, sessions):
    first = session(sessions, frame)
    sessions.stage_binding(
        service.store.frame(frame[0]),
        service.settings.config.frame_defaults,
        "possibly-written-token",
        first["session_id"],
    )
    with pytest.raises(HTTPException) as caught:
        session(sessions, frame)
    assert caught.value.status_code == 409
    assert sessions.get(frame[0], first["session_id"])["state"] == "active"


def test_owner_boot_transition_discards_old_picture_proof_but_keeps_pending_binding(
    service, frame, sessions
):
    value = session(sessions, frame)
    data = challenge(value)
    current = service.store.frame(frame[0])
    sessions.image_requested(current, data, {"id": 1, "body_hash": "b" * 64}, frame[1])
    for phase in ("image_verified", "panel_refreshed"):
        sessions.acknowledge(current, dict(data, phase=phase, image_sha256="b" * 64))
    unchanged = sessions.transition_boot(frame[0], value["session_id"], data)
    assert "panel_refreshed" in unchanged["evidence"]
    # A candidate may already have been written, so reboot cannot revoke it.
    sessions.stage_binding(
        current,
        service.settings.config.frame_defaults,
        "possibly-written-token",
        value["session_id"],
    )
    new_boot = dict(data, boot_id="ffffffffffffffff")
    transitioned = sessions.transition_boot(frame[0], value["session_id"], new_boot)
    assert transitioned["session_id"] == value["session_id"]
    assert transitioned["nonce"] == value["nonce"]
    assert transitioned["boot_id"] == "ffffffffffffffff"
    assert transitioned["image_id"] is None and transitioned["image_sha256"] is None
    assert set(transitioned["evidence"]) == {"booted"}
    assert transitioned["pending_binding"]["session_id"] == value["session_id"]
    pending = sessions.authenticate("possibly-written-token", value["session_id"], value["nonce"])
    assert pending and service.store.authenticate(frame[1])
    with pytest.raises(HTTPException):
        sessions.finish(frame[0], value["session_id"], True)
    with pytest.raises(HTTPException):
        sessions.acknowledge(
            pending, dict(new_boot, phase="panel_refreshed", image_sha256="b" * 64)
        )
    with pytest.raises(HTTPException):
        sessions.image_requested(
            pending, data, {"id": 1, "body_hash": "b" * 64}, "possibly-written-token"
        )
    sessions.image_requested(
        pending, new_boot, {"id": 2, "body_hash": "c" * 64}, "possibly-written-token"
    )
    assert service.store.authenticate("possibly-written-token")


def test_owner_boot_transition_refuses_wrong_device_firmware_bundle_and_expired_lease(
    service, frame, sessions
):
    value = session(sessions, frame)
    data = challenge(value)
    for changed in (
        {"device_id": "aabbcc009999"},
        {"firmware": "v-other"},
        {"bundle_sha256": "a" * 64},
        {"boot_id": "not-a-boot"},
    ):
        with pytest.raises(HTTPException):
            sessions.transition_boot(frame[0], value["session_id"], dict(data, **changed))
    assert sessions.get(frame[0], value["session_id"])["boot_id"] is None
    sessions.clock = lambda: datetime.now(UTC) + timedelta(seconds=91)
    with pytest.raises(HTTPException):
        sessions.transition_boot(frame[0], value["session_id"], data)


def test_boot_transition_route_requires_owner_and_csrf(service, frame, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    value = session(RecoverySessions(service.store), frame)
    path = "/manage/usb-recovery/sessions/" + frame[0] + "/" + value["session_id"] + "/boot"
    data = challenge(value)
    assert TestClient(create_app(service, schedule=False)).post(path, data=data).status_code == 401
    assert client.post(path, data=dict(data, csrf="wrong")).status_code == 403
    result = client.post(path, data=dict(data, csrf=csrf))
    assert result.status_code == 200
    assert result.json()["session_id"] == value["session_id"]
    assert result.json()["nonce"] == value["nonce"] and result.json()["boot_id"] == data["boot_id"]


def test_first_owner_hello_tentatively_identifies_unknown_frame_until_authenticated_fetch(
    service, frame, sessions
):
    value = sessions.create(frame[0], {"version": "v-test", "parts": []})
    assert value["device_id"] is None
    data = challenge(value)
    identified = sessions.transition_boot(frame[0], value["session_id"], data)
    assert identified["device_id"] == data["device_id"]
    with service.store.connect() as db:
        assert not db.execute(
            "SELECT 1 FROM recovery_device_identity WHERE frame_id=?", (frame[0],)
        ).fetchone()
    with pytest.raises(HTTPException):
        sessions.transition_boot(
            frame[0], value["session_id"], dict(data, device_id="aabbcc009999")
        )
    sessions.image_requested(
        service.store.frame(frame[0]), data, {"id": 1, "body_hash": "b" * 64}, frame[1]
    )
    with service.store.connect() as db:
        assert (
            db.execute(
                "SELECT device_id FROM recovery_device_identity WHERE frame_id=?", (frame[0],)
            ).fetchone()[0]
            == data["device_id"]
        )
    with pytest.raises(HTTPException):
        sessions.transition_boot(
            frame[0], value["session_id"], dict(data, device_id="aabbcc009999")
        )


@pytest.mark.parametrize("missing", ["booted", "cloud_requested", "image_verified"])
def test_finish_refuses_partial_proof_even_with_panel_checkpoint(service, frame, sessions, missing):
    value = session(sessions, frame)
    data = challenge(value)
    sessions.image_requested(
        service.store.frame(frame[0]), data, {"id": 1, "body_hash": "b" * 64}, frame[1]
    )
    for phase in ("image_verified", "panel_refreshed"):
        sessions.acknowledge(
            service.store.frame(frame[0]), dict(data, phase=phase, image_sha256="b" * 64)
        )
    with service.store.connect() as db:
        proof = json.loads(
            db.execute(
                "SELECT evidence FROM recovery_sessions WHERE id=?", (value["session_id"],)
            ).fetchone()[0]
        )
        proof.pop(missing)
        db.execute(
            "UPDATE recovery_sessions SET evidence=? WHERE id=?",
            (json.dumps(proof), value["session_id"]),
        )
    assert sessions.get(frame[0], value["session_id"])["verification"] == "pending"
    with pytest.raises(HTTPException) as caught:
        sessions.finish(frame[0], value["session_id"], True)
    assert caught.value.status_code == 409


def test_verification_failure_and_successful_retry_are_explicit(service, frame, sessions):
    value = session(sessions, frame)
    data = challenge(value)
    current = service.store.frame(frame[0])
    sessions.image_requested(current, data, {"id": 1, "body_hash": "b" * 64}, frame[1])
    assert sessions.get(frame[0], value["session_id"])["verification"] == "pending"
    sessions.acknowledge(current, dict(data, phase="image_verified", image_sha256="b" * 64))
    sessions.acknowledge(current, dict(data, phase="failed", error="display_failed"))
    assert sessions.get(frame[0], value["session_id"])["verification"] == "failed"
    with pytest.raises(HTTPException):
        sessions.finish(frame[0], value["session_id"], True)
    sessions.acknowledge(current, dict(data, phase="panel_refreshed", image_sha256="b" * 64))
    assert sessions.get(frame[0], value["session_id"])["verification"] == "verified"
    completed = sessions.finish(frame[0], value["session_id"], True)
    assert completed["state"] == "completed"
    assert "error" not in completed["evidence"]
    assert sessions.finish(frame[0], value["session_id"], True)["state"] == "completed"


@pytest.mark.parametrize(
    "changed",
    [
        {"boot_id": "0123456789abcdee"},
        {"image_id": "2"},
        {"image_sha256": "c" * 64},
        {"image_id": None},
    ],
)
def test_physical_confirmation_is_bound_to_exact_boot_and_picture(
    service, frame, sessions, changed
):
    value = session(sessions, frame)
    data = challenge(value)
    current = service.store.frame(frame[0])
    sessions.image_requested(current, data, {"id": 1, "body_hash": "b" * 64}, frame[1])
    for phase in ("image_verified", "panel_refreshed"):
        sessions.acknowledge(current, dict(data, phase=phase, image_sha256="b" * 64))
    expected = {"boot_id": data["boot_id"], "image_id": "1", "image_sha256": "b" * 64}
    with pytest.raises(HTTPException) as caught:
        sessions.finish(frame[0], value["session_id"], True, expected=expected | changed)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "picture_changed"
    assert sessions.get(frame[0], value["session_id"])["state"] == "active"
    assert (
        sessions.finish(frame[0], value["session_id"], True, expected=expected)["state"]
        == "completed"
    )
    assert (
        sessions.finish(frame[0], value["session_id"], True, expected=expected)["state"]
        == "completed"
    )
    with pytest.raises(HTTPException):
        sessions.finish(frame[0], value["session_id"], True, expected=expected | changed)
