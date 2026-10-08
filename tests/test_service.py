import gzip
import json
import shutil
import sqlite3
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from einkartifact.api import create_app
from einkartifact.render import choose_art, validate_epdgz
from einkartifact.settings import FramePolicy, Settings
from einkartifact.store import Store


def test_http_cache_and_config_change_without_repainting(service, frame):
    frame_id, token = frame
    prepared = service.prepare(frame_id, "2026-10-08")
    with TestClient(create_app(service, schedule=False)) as client:
        headers = {"Authorization": f"Bearer {token}"}
        first = client.get("/v1/image", headers=headers)
        assert first.status_code == 200
        assert "content-encoding" not in first.headers
        assert int(first.headers["content-length"]) == len(first.content)
        assert len(gzip.decompress(first.content)) == 192000
        assert json.loads(first.headers["x-config-payload"])["config"]["rotate_cron"] == ["15 3 *"]
        tag = first.headers["etag"]
        unchanged = client.get("/v1/image", headers={**headers, "If-None-Match": tag})
        assert unchanged.status_code == 304 and unchanged.content == b""
        weak = client.get("/v1/image", headers={**headers, "If-None-Match": f"W/{tag}"})
        assert weak.status_code == 304
        policy = json.loads(service.store.frame(frame_id)["policy"])
        policy.update(wake_local_time="03:20", firmware_rotate_cron=["20 3 *"])
        service.store.set_policy(frame_id, FramePolicy.model_validate(policy))
        changed = client.get("/v1/image", headers={**headers, "If-None-Match": tag})
        assert changed.status_code == 200
        assert changed.content == first.content
        assert changed.headers["etag"] != tag
        assert json.loads(changed.headers["x-config-payload"])["config"]["rotate_cron"] == [
            "20 3 *"
        ]
        assert service.store.active_image(service.store.frame(frame_id))["id"] == prepared["id"]
        assert service.providers.calls == 1


def test_tokens_geometry_and_preview_are_isolated(service, frame):
    frame_id, token = frame
    second_token = service.store.add_frame("second-frame", service.settings.config.frame_defaults)
    a = service.prepare(frame_id, "2026-10-08")
    b = service.prepare("second-frame", "2026-10-08")
    with TestClient(create_app(service, schedule=False)) as client:
        assert client.get("/v1/image").status_code == 401
        assert client.get("/v1/image", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get("/v1/preview").status_code == 401
        headers = {"Authorization": f"Bearer {token}", "X-Display-Width": "400"}
        assert client.get("/v1/image", headers=headers).status_code == 409
        for t, image in ((token, a), (second_token, b)):
            r = client.get("/v1/image", headers={"Authorization": f"Bearer {t}"})
            assert r.content == service.cache_path(image["path"]).read_bytes()
        new_token = service.store.rotate_token(frame_id)
        assert service.store.authenticate(token) is None
        assert service.store.authenticate(new_token)["id"] == frame_id
        assert client.get("/healthz").status_code == 200
        assert "CC BY-SA 4.0" in client.get("/").text
        assert "Fugleramme" in client.get("/").text
        assert token not in client.get("/credits.json").text


def test_failed_converter_preserves_last_good_and_retry_plan(service, frame):
    frame_id, _ = frame
    good = service.prepare(frame_id, "2026-10-08")
    converter = service.converter

    def broken(*args):
        raise TimeoutError("simulated slow conversion")

    service.converter = broken
    with pytest.raises(TimeoutError):
        service.prepare(frame_id, "2026-10-09")
    assert service.store.active_image(service.store.frame(frame_id))["id"] == good["id"]
    with service.store.connect() as db:
        job = dict(db.execute("SELECT * FROM jobs WHERE local_date='2026-10-09'").fetchone())
    assert job["status"] == "failed" and job["attempts"] == 1
    plan = job["plan"]
    service.converter = converter
    recovered = service.prepare(frame_id, "2026-10-09")
    assert recovered["manifest"] == plan
    assert recovered["revision"] == 1
    assert service.providers.calls == 2
    assert service.prepare(frame_id, "2026-10-09")["id"] == recovered["id"]
    assert service.providers.calls == 2


def test_corrupt_cache_is_not_served_and_repaired_from_saved_plan(service, frame):
    frame_id, token = frame
    good = service.prepare(frame_id, "2026-10-08")
    service.cache_path(good["path"]).write_bytes(b"corrupt")
    with TestClient(create_app(service, schedule=False)) as client:
        assert (
            client.get("/v1/image", headers={"Authorization": f"Bearer {token}"}).status_code == 503
        )
    repaired = service.prepare(frame_id, "2026-10-08")
    assert repaired["body_hash"] == good["body_hash"]
    assert validate_epdgz(service.cache_path(repaired["path"])) == good["body_hash"]
    assert service.providers.calls == 1


def test_invalid_panel_output_never_publishes(service, frame):
    frame_id, _ = frame
    good = service.prepare(frame_id, "2026-10-08")

    def invalid(source, target, preview, *args):
        target.write_bytes(gzip.compress(b"\x44" * 192000))
        Image.new("RGB", (800, 480)).save(preview)

    service.converter = invalid
    with pytest.raises(ValueError, match="color indices"):
        service.prepare(frame_id, "2026-10-09")
    assert service.store.active_image(service.store.frame(frame_id))["id"] == good["id"]


def test_backup_restores_registry_and_active_image(service, frame, tmp_path):
    frame_id, token = frame
    image = service.prepare(frame_id, "2026-10-08")
    backup = tmp_path / "recovery"
    service.backup(backup)
    with sqlite3.connect(backup / "einkartifact.sqlite3") as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    recovered_data = tmp_path / "recovered-data"
    recovered_data.mkdir()
    shutil.copy2(backup / "einkartifact.sqlite3", recovered_data / "einkartifact.sqlite3")
    shutil.copytree(backup / "active-cache", recovered_data / "cache")
    settings = Settings(
        config_path=backup / "site.json",
        data_dir=recovered_data,
        art_dir=backup / "art",
        backup_dir=tmp_path / "recovered-backups",
    )
    store = Store(settings.db_path)
    assert store.authenticate(token)["id"] == frame_id
    assert validate_epdgz(recovered_data / image["path"]) == image["body_hash"]
    assert not (backup / "provisioning").exists()


def test_art_month_filter_and_year_round_fallback(service):
    base = service.settings.artworks[0]
    winter_only = {**base, "id": "winter-only", "months": [12]}
    selected = choose_art([winter_only, base], "2026-07-02", {}, [], "seed")
    assert selected["id"] == base["id"]
    with pytest.raises(ValueError, match="seasonally"):
        choose_art([winter_only], "2026-07-02", {}, [], "seed")


def test_missing_input_and_restart_are_idempotent(service, frame):
    frame_id, _ = frame
    initial = service.prepare(frame_id, "2026-10-08", offline=True)
    from einkartifact.service import Service

    restarted = Service(service.settings, providers=service.providers, converter=service.converter)
    result = restarted.prepare(frame_id, "2026-10-08")
    assert result["body_hash"] == initial["body_hash"]
    assert json.loads(result["manifest"])["inputs"] == {}


def test_due_schedule_is_local_and_manual_prepare_does_not_shift_wake(service, frame):
    frame_id, _ = frame
    first = service.prepare(frame_id, "2026-10-07")
    service.prepare_due(datetime(2026, 10, 8, 8, 29, tzinfo=UTC))  # 02:29 Denver
    assert service.store.active_image(service.store.frame(frame_id))["id"] == first["id"]
    service.prepare_due(datetime(2026, 10, 8, 8, 30, tzinfo=UTC))
    assert service.store.active_image(service.store.frame(frame_id))["local_date"] == "2026-10-08"
    assert json.loads(service.store.frame(frame_id)["policy"])["firmware_rotate_cron"] == ["15 3 *"]
