from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from emviary.api import create_app
from emviary.service import Service, preparation_lock


def test_download_cycles_buffer_but_preserves_delivered_image_and_schedule(service, frame):
    frame_id, token = frame
    first = service.prepare(frame_id)
    headers = {"Authorization": f"Bearer {token}", "X-Firmware-Version": "test"}
    client = TestClient(create_app(service, schedule=False))
    response = client.get("/v1/image", headers=headers)
    assert response.status_code == 200
    assert response.content == service.cache_path(first["path"]).read_bytes()
    following = service.store.active_image(service.store.frame(frame_id))
    assert following["id"] != first["id"]
    assert service.delivered_image(service.store.frame(frame_id))["id"] == first["id"]
    headers["If-None-Match"] = response.headers["etag"]
    second = client.get("/v1/image", headers=headers)
    assert second.status_code == 200
    assert second.content == service.cache_path(following["path"]).read_bytes()
    assert second.headers["etag"] != response.headers["etag"]
    assert service.store.pending_refills() == []
    assert '"rotate_cron":["15 3 *"]' in second.headers["x-config-payload"]


def test_duplicate_fetch_and_preview_do_not_create_extra_successors(service, frame):
    frame_id, token = frame
    first = service.prepare(frame_id)
    client = TestClient(create_app(service, schedule=False))
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/v1/preview", headers=headers).status_code == 200
    assert client.get("/v1/image", headers=headers).status_code == 200
    assert service.store.frame(frame_id)["active_image_id"] == first["id"]
    service.image_delivered(frame_id, first["id"], None, "test", "", first["body_hash"])
    following = service.store.frame(frame_id)["active_image_id"]
    service.image_delivered(frame_id, first["id"], None, "test", "", first["body_hash"])
    assert service.store.frame(frame_id)["active_image_id"] == following
    assert service.store.pending_refills() == []


def test_busy_lock_persists_queue_and_restart_recovers(service, frame):
    frame_id, token = frame
    first = service.prepare(frame_id)
    with preparation_lock(service.settings.data_dir):
        response = TestClient(create_app(service, schedule=False)).get(
            "/v1/image", headers={"Authorization": f"Bearer {token}", "X-Firmware-Version": "test"}
        )
        assert response.status_code == 200
        assert service.store.pending_refills()[0]["consumed_image_id"] == first["id"]
        assert service.store.frame(frame_id)["active_image_id"] == first["id"]
    restarted = Service(service.settings, providers=service.providers, converter=service.converter)
    restarted.refill_pending()
    assert restarted.store.pending_refills() == []
    assert restarted.store.frame(frame_id)["active_image_id"] != first["id"]


def test_failed_refill_returns_good_image_and_bounds_retry(service, frame):
    frame_id, token = frame
    first = service.prepare(frame_id)
    converter = service.converter

    def fail(*args, **kwargs):
        raise RuntimeError("Render failed")

    service.converter = fail
    response = TestClient(create_app(service, schedule=False)).get(
        "/v1/image", headers={"Authorization": f"Bearer {token}", "X-Firmware-Version": "test"}
    )
    assert response.status_code == 200
    assert response.content == service.cache_path(first["path"]).read_bytes()
    pending = service.store.pending_refills()[0]
    now = datetime.fromisoformat(pending["last_attempt_at"])
    service.refill_pending(now=now + timedelta(minutes=1))
    assert service.store.pending_refills()[0]["attempts"] == 1
    service.refill_pending(now=now + timedelta(minutes=16))
    service.refill_pending(now=now + timedelta(minutes=32))
    service.refill_pending(now=now + timedelta(minutes=48))
    assert service.store.pending_refills()[0]["attempts"] == 3
    assert service.store.frame(frame_id)["active_image_id"] == first["id"]
    with service.store.connect() as db:
        jobs = db.execute("SELECT * FROM jobs WHERE status='failed'").fetchall()
    assert len(jobs) == 1
    assert jobs[0]["attempts"] == 3
    service.converter = converter
    service.refill_pending(now=now + timedelta(days=1))
    assert service.store.pending_refills() == []
    assert service.store.frame(frame_id)["active_image_id"] != first["id"]


def test_nightly_preparation_supersedes_consumed_queue(service, frame):
    frame_id, _ = frame
    first = service.prepare(frame_id, "2026-10-07")
    service.store.request_refill(frame_id, first["id"])
    scheduled = service.prepare(frame_id, "2026-10-08")
    service.refill_pending(now=datetime(2026, 10, 8, 9, tzinfo=UTC))
    assert service.store.pending_refills() == []
    assert service.store.frame(frame_id)["active_image_id"] == scheduled["id"]


def test_navigation_history_skips_removed_and_latest_does_not_follow_cursor(service, frame):
    from emviary.api import etag_for

    frame_id, token = frame
    first = service.prepare(frame_id)
    second = service.prepare(frame_id, force=True)
    third = service.prepare(frame_id, force=True)
    with service.store.connect() as db:
        db.execute("UPDATE images SET hidden=1 WHERE id=?", (second["id"],))
    client = TestClient(create_app(service, schedule=False))
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Image-Navigation": "previous",
        "If-None-Match": etag_for(service.store.frame(frame_id), third),
    }
    previous = client.get("/v1/image", headers=headers)
    assert previous.content == service.cache_path(first["path"]).read_bytes()
    headers.update({"X-Image-Navigation": "next", "If-None-Match": previous.headers["etag"]})
    assert (
        client.get("/v1/image", headers=headers).content
        == service.cache_path(third["path"]).read_bytes()
    )
    headers["X-Image-Navigation"] = "latest"
    assert (
        client.get("/v1/image", headers=headers).content
        == service.cache_path(third["path"]).read_bytes()
    )
    headers.update({"X-Image-Navigation": "previous", "If-None-Match": previous.headers["etag"]})
    assert client.get("/v1/image", headers=headers).status_code == 304
    headers["X-Image-Navigation"] = "bad"
    assert client.get("/v1/image", headers=headers).status_code == 400


def test_counts_are_per_successful_species_render_and_survive_removal(service, frame):
    import json

    frame_id, _ = frame
    first = service.prepare(frame_id)
    artworks = json.loads(first["manifest"])["artworks"]
    assert service.store.bird_counts() == {a["scientific_name"]: 1 for a in artworks}
    service.prepare(frame_id)
    assert service.store.bird_counts() == {a["scientific_name"]: 1 for a in artworks}
    with service.store.connect() as db:
        db.execute("UPDATE images SET hidden=1 WHERE id=?", (first["id"],))
    restarted = Service(service.settings, providers=service.providers, converter=service.converter)
    assert restarted.store.bird_counts() == service.store.bird_counts()


def test_backup_preserves_navigable_image_history(service, frame, tmp_path):
    first = service.prepare(frame[0])
    second = service.prepare(frame[0], force=True)
    backup = tmp_path / "history-backup"
    service.backup(backup)
    for image in [first, second]:
        assert (backup / "active-cache" / service.cache_path(image["path"]).name).is_file()
        assert (backup / "active-cache" / service.cache_path(image["preview_path"]).name).is_file()


def test_removed_cached_image_is_replaced_without_restoring_it(service, frame):
    frame_id, _ = frame
    removed = service.prepare(frame_id)
    with service.store.connect() as db:
        db.execute("UPDATE images SET hidden=1 WHERE id=?", (removed["id"],))
    replacement = service.prepare(frame_id)
    assert replacement["id"] != removed["id"]
    assert replacement["revision"] == removed["revision"] + 1
    assert not replacement["hidden"]
    assert service.prepare(frame_id)["id"] == replacement["id"]
    with service.store.connect() as db:
        assert db.execute("SELECT hidden FROM images WHERE id=?", (removed["id"],)).fetchone()[0]


def test_stale_removed_navigation_cursor_never_resends_removed_image(service, frame):
    from emviary.api import etag_for

    frame_id, token = frame
    removed = service.prepare(frame_id)
    following = service.prepare(frame_id, force=True)
    with service.store.connect() as db:
        db.execute("UPDATE images SET hidden=1 WHERE id=?", (removed["id"],))
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Image-Navigation": "previous",
        "If-None-Match": etag_for(service.store.frame(frame_id), removed),
    }
    response = TestClient(create_app(service, schedule=False)).get("/v1/image", headers=headers)
    assert response.status_code == 200
    assert response.content == service.cache_path(following["path"]).read_bytes()
    with service.store.connect() as db:
        db.execute("UPDATE images SET hidden=1 WHERE id=?", (following["id"],))
    assert (
        TestClient(create_app(service, schedule=False))
        .get("/v1/image", headers=headers)
        .status_code
        == 503
    )
