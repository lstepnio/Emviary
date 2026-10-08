from datetime import date


def test_retention_keeps_last_good_even_when_old(service, frame):
    frame_id, _ = frame
    old = service.prepare(frame_id, "2026-08-01", offline=True)
    newest = service.prepare(frame_id, "2026-08-02", offline=True)
    service._prune_history(date(2026, 10, 8))
    assert not service.cache_path(old["path"]).exists()
    assert service.cache_path(newest["path"]).exists()
    assert service.store.active_image(service.store.frame(frame_id))["id"] == newest["id"]
    with service.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
