import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_owner import sign_in
from test_public_ui import public_client

from emviary.api import create_app
from emviary.backup_validation import verify_backup
from emviary.service import Service


def report(image, **extra):
    return {
        "offline_image_id": image["id"],
        "offline_mode": False,
        "previous_result": "success",
        "previous_http_status": 200,
        **extra,
    }


def observe(service, frame, image, **extra):
    service.display_history.observe(frame[0], image["body_hash"], report(image, **extra), "v0.8.10")


def test_real_fetch_confirm_and_history_journey_excludes_unseen_preparations(
    service, frame, tmp_path, monkeypatch
):
    fox = service.prepare(frame[0], offline=True)
    public = public_client(service, frame)
    owner, _ = sign_in(service, tmp_path, monkeypatch)
    headers = {"Authorization": "Bearer " + frame[1], "X-Firmware-Version": "v0.8.10"}
    assert public.get("/v1/image", headers=headers).status_code == 200
    raccoon = service.store.active_image(service.store.frame(frame[0]))
    assert raccoon["id"] != fox["id"]
    assert service.store.past_compositions(frame[0]) == []
    assert "display not yet confirmed" in owner.get("/manage").text
    assert "Prepared" in public.get("/").text
    assert "may have gaps" in owner.get("/manage").text
    # A later wake reports the fox while fetching today's new image. The
    # unconsumed raccoon must never enter confirmed history.
    service.prepare(frame[0], force=True, offline=True)
    latest = service.store.active_image(service.store.frame(frame[0]))
    reply = public.get(
        "/v1/image",
        headers={
            **headers,
            "If-None-Match": fox["body_hash"],
            "X-Frame-Metrics": json.dumps(report(fox)),
        },
    )
    assert reply.status_code == 200
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM image_transfers").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM image_display_reports").fetchone()[0] == 1
    past = service.store.past_compositions(frame[0], latest["id"], 10)
    assert [i["id"] for i in past] == [fox["id"]]
    for html in (owner.get("/manage").text, public.get("/").text):
        history = (
            html.split("<h3>Past compositions</h3>")[-1]
            if "<h3>Past" in html
            else html.split("<h2>Past compositions</h2>")[-1]
        )
        assert str(fox["id"]) + "/preview" in history or str(fox["id"]) + ".jpg" in history
        assert "Frame reported" in history
        assert str(raccoon["id"]) + "/preview" not in history
        assert str(raccoon["id"]) + ".jpg" not in history
    assert public.get(f"/display/images/{raccoon['id']}.jpg").status_code == 404


@pytest.mark.parametrize(
    "fault", ["failed", "missing", "unknown_firmware", "conflict", "wrong_frame"]
)
def test_bad_or_ambiguous_reports_never_promote_sent_pictures(service, frame, fault):
    image = service.prepare(frame[0], offline=True)
    other = service.prepare(frame[0], offline=True, force=True)
    metrics = report(image)
    firmware, tag = "v0.8.10", image["body_hash"]
    if fault == "failed":
        metrics["previous_result"] = "failed"
    elif fault == "missing":
        metrics.pop("previous_http_status")
    elif fault == "unknown_firmware":
        firmware = "v2.19.0"
    elif fault == "conflict":
        tag = other["body_hash"]
    else:
        service.store.add_frame("other", service.settings.config.frame_defaults)
        image = service.prepare("other", offline=True)
        metrics, tag = report(image), image["body_hash"]
    service.display_history.sent(frame[0], other["id"], 200)
    service.display_history.observe(frame[0], tag, metrics, firmware)
    assert service.store.past_compositions(frame[0]) == []


def test_repeated_304_confirms_previous_picture_without_promoting_new_buffer(
    service, frame, monkeypatch
):
    image = service.prepare(frame[0], offline=True)
    client = TestClient(create_app(service, schedule=False))
    headers = {"Authorization": "Bearer " + frame[1], "X-Firmware-Version": "v0.8.10"}
    initial = client.get("/v1/image", headers=headers)
    monkeypatch.setattr(service, "select_image", lambda *args: (image, False))
    for _ in range(2):
        result = client.get(
            "/v1/image",
            headers={
                **headers,
                "If-None-Match": initial.headers["etag"],
                "X-Frame-Metrics": json.dumps(report(image)),
            },
        )
        assert result.status_code == 304
    assert service.display_history.latest(frame[0])["id"] == image["id"]
    assert [i["id"] for i in service.store.past_compositions(frame[0])] == [image["id"]]


def test_positive_report_survives_current_fetch_503_and_previews_never_count(service, frame):
    image = service.prepare(frame[0], offline=True)
    client = public_client(service, frame)
    client.get("/display/next-daily.jpg")
    client.get("/v1/preview", headers={"Authorization": "Bearer " + frame[1]})
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM image_transfers").fetchone()[0] == 0
    service.cache_path(image["path"]).unlink()
    response = client.get(
        "/v1/image",
        headers={
            "Authorization": "Bearer " + frame[1],
            "X-Firmware-Version": "v0.8.10",
            "If-None-Match": image["body_hash"],
            "X-Frame-Metrics": json.dumps(report(image)),
        },
    )
    assert response.status_code == 503
    assert service.display_history.latest(frame[0])["id"] == image["id"]
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM image_transfers").fetchone()[0] == 0


def test_offline_display_report_can_confirm_a_cached_picture_after_cloud_failure(service, frame):
    image = service.prepare(frame[0], offline=True)
    service.display_history.observe(
        frame[0],
        "",
        report(
            image,
            offline_mode=True,
            offline_rotations=1,
            previous_result="failed",
            previous_http_status=0,
        ),
        "v0.8.10",
    )
    assert service.display_history.latest(frame[0])["source"] == "offline_cache_report"


def test_restart_imports_only_recoverable_legacy_reports_once(service, frame):
    image = service.prepare(frame[0], offline=True)
    for offset, metrics in enumerate((report(image), report(image, previous_result="failed"), {})):
        with service.store.connect() as db:
            db.execute(
                "INSERT INTO device_samples(frame_id,recorded_at,firmware,metrics) VALUES(?,?,?,?)",
                (
                    frame[0],
                    (service.clock() + timedelta(seconds=offset)).isoformat(),
                    "v0.8.10",
                    json.dumps(metrics),
                ),
            )
            db.execute("UPDATE display_history_state SET legacy_import_complete=0")
    for _ in range(2):
        restarted = Service(service.settings, service.providers, service.converter, service.clock)
    found = restarted.display_history.latest(frame[0])
    assert found["id"] == image["id"] and found["recovered"] == 1
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM image_display_reports").fetchone()[0] == 1


def test_report_order_is_observation_order_not_render_id(service, frame):
    first = service.prepare(frame[0], offline=True)
    second = service.prepare(frame[0], offline=True, force=True)
    clock = [service.clock()]
    service.clock = lambda: clock[0]
    observe(service, frame, second)
    clock[0] += timedelta(minutes=1)
    observe(service, frame, first)
    assert [i["id"] for i in service.store.past_compositions(frame[0], limit=10)] == [
        first["id"],
        second["id"],
    ]


def test_history_backup_restore_and_pruning_keep_honest_metadata(service, frame, tmp_path):
    image = service.prepare(frame[0], offline=True)
    observe(service, frame, image)
    backup = service.backup(tmp_path / "history-backup")
    assert verify_backup(backup)["restore_rehearsal"] == "passed"
    with service.store.connect() as db:
        db.execute("UPDATE frames SET active_image_id=NULL,max_delivered_image_id=NULL")
        db.execute("DELETE FROM prepared_slots")
        db.execute("DELETE FROM images WHERE id=?", (image["id"],))
        assert db.execute("SELECT image_id FROM image_display_reports").fetchone()[0] is None
    assert service.store.past_compositions(frame[0]) == []


def test_history_query_streams_report_index_without_large_manifest_sort(service, frame):
    with service.store.connect() as db:
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT i.* FROM image_display_reports r "
            "INDEXED BY image_display_reports_frame_time JOIN images i ON i.id=r.image_id "
            "WHERE r.frame_id=? AND i.frame_id=? AND i.hidden=0 "
            "ORDER BY r.reported_at DESC,r.id DESC",
            (frame[0], frame[0]),
        ).fetchall()
        assert not any("TEMP B-TREE" in r[3] for r in plan)


def test_recovery_requires_correlated_panel_ack_and_records_it_once(service, frame):
    from fastapi import HTTPException
    from test_recovery_sessions import challenge

    from emviary.recovery_sessions import RecoverySessions

    image = service.prepare(frame[0], offline=True)
    sessions = RecoverySessions(service.store, now=service.clock)
    value = sessions.create(frame[0], {"version": "v-test", "parts": []}, "aabbcc001122")
    data = challenge(value)
    current = service.store.frame(frame[0])
    sessions.image_requested(current, data, image, frame[1])
    assert service.display_history.latest(frame[0]) is None
    with pytest.raises(HTTPException):
        sessions.acknowledge(
            current, dict(data, phase="panel_refreshed", image_sha256=image["body_hash"])
        )
    sessions.acknowledge(
        current, dict(data, phase="image_verified", image_sha256=image["body_hash"])
    )
    assert service.display_history.latest(frame[0]) is None
    for _ in range(2):
        sessions.acknowledge(
            current, dict(data, phase="panel_refreshed", image_sha256=image["body_hash"])
        )
    assert service.display_history.latest(frame[0])["source"] == "recovery_panel_ack"
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM image_display_reports").fetchone()[0] == 1


def test_unknown_cursor_future_image_and_unauthenticated_fetch_do_not_confirm(service, frame):
    image = service.prepare(frame[0], offline=True)
    client = TestClient(create_app(service, schedule=False))
    assert (
        client.get(
            "/v1/image",
            headers={"X-Firmware-Version": "v0.8.10", "X-Frame-Metrics": json.dumps(report(image))},
        ).status_code
        == 401
    )
    service.display_history.observe(frame[0], "", report(image, offline_image_id=999999), "v0.8.10")
    service.clock = lambda: datetime.fromisoformat(image["created_at"]) - timedelta(seconds=1)
    observe(service, frame, image)
    assert service.display_history.latest(frame[0]) is None
