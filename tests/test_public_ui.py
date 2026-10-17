from fastapi.testclient import TestClient

from emviary.api import create_app


def public_client(service, frame):
    config = service.settings.config.model_dump()
    config["public_frame_id"] = frame[0]
    service.save_configuration(config)
    return TestClient(create_app(service, schedule=False))


def test_public_home_waits_for_delivery_and_never_exposes_frame_settings(service, frame):
    client = public_client(service, frame)
    service.prepare(frame[0], "2026-10-08", offline=True)
    response = client.get("/")
    assert response.status_code == 200
    assert "The first artwork is on its way" in response.text
    assert 'src="/display.jpg"' not in response.text
    assert frame[0] not in response.text and frame[1] not in response.text
    assert "config_revision" not in response.text and "firmware_timezone" not in response.text
    assert 'href="/library"' in response.text
    assert 'href="/manage"' in response.text


def test_public_home_and_mirror_keep_last_delivery_as_buffer_advances(service, frame):
    client = public_client(service, frame)
    first = service.prepare(frame[0], "2026-10-08", offline=True)
    headers = {"Authorization": "Bearer " + frame[1], "X-Firmware-Version": "v2.19.0"}
    assert client.get("/v1/image", headers=headers).status_code == 200
    assert service.store.frame(frame[0])["active_image_id"] != first["id"]
    delivered = client.get("/display.jpg").content
    assert delivered == service.cache_path(first["preview_path"]).read_bytes()
    home = client.get("/")
    assert 'alt="Last cloud-confirmed frame artwork"' in home.text
    assert 'src="/display.jpg"' in home.text
    assert frame[0] not in home.text and frame[1] not in home.text
    service.prepare(frame[0], "2026-10-08", force=True, offline=True)
    assert client.get("/display.jpg").content == delivered


def test_library_search_sort_and_counts_are_species_renders(service):
    works = service.settings.artworks
    chickadee = next(a for a in works if a["common_name"] == "Black-capped Chickadee")
    bluejay = next(a for a in works if a["common_name"] == "Blue Jay")
    service.settings.artworks = [chickadee, {**chickadee, "id": "second-chickadee"}, bluejay]
    with service.store.connect() as db:
        service.store.count_render(
            db, {"artwork": chickadee, "artworks": [chickadee, chickadee, bluejay]}
        )
        service.store.count_render(db, {"artwork": bluejay})
    client = TestClient(create_app(service, schedule=False))
    response = client.get("/library?sort=most")
    assert response.status_code == 200
    assert response.text.index("<h2>Blue Jay</h2>") < response.text.index(
        "<h2>Black-capped Chickadee</h2>"
    )
    assert "Species renders: 1" in response.text
    assert "2 illustrations" in response.text
    assert "Species renders: 2" in response.text
    assert "once per composition" in response.text
    assert "not page views" in response.text
    search = client.get("/library", params={"q": "poecile"})
    assert "<h2>Black-capped Chickadee</h2>" in search.text
    assert "<h2>Blue Jay</h2>" not in search.text
    assert chickadee["source_url"] not in search.text
    assert chickadee["credit"] not in search.text
    assert "CC BY-SA 4.0" not in search.text


def test_library_filters_empty_state_and_escape(service):
    client = TestClient(create_app(service, schedule=False))
    response = client.get("/library", params={"q": '<script>alert("x")</script>'})
    assert "No artwork matches" in response.text
    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text
    assert 'href="/library"' in response.text
    reference = client.get("/library?status=reference")
    assert "Web reference only" in reference.text
    assert "Species renders: 0" in reference.text
    first = client.get("/library")
    assert first.text.count('<article class="card library-card artwork-card"') == 24
    assert "Page 1 of " in first.text
    assert client.get("/library?p=-4").status_code == 200


def test_public_gallery_exposes_prepared_and_past_images_only_for_public_frame(service, frame):
    client = public_client(service, frame)
    first = service.prepare(frame[0], "2026-10-08", offline=True)
    second = service.prepare(frame[0], "2026-10-08", force=True, offline=True)
    current = service.prepare(frame[0], "2026-10-08", force=True, offline=True)
    with service.store.connect() as db:
        db.execute(
            "UPDATE frames SET last_served_etag=? WHERE id=?",
            ('"' + current["body_hash"] + '"', frame[0]),
        )
    ready = service.prepare(frame[0], "2026-10-08", force=True, offline=True)
    before = service.store.bird_counts()
    home = client.get("/")
    assert home.status_code == 200
    assert "Coming up" in home.text and "Next button" in home.text
    assert (
        "Past compositions" in home.text and 'alt="Last cloud-confirmed frame artwork"' in home.text
    )
    for record in [first, second, ready]:
        path = f"/display/images/{record['id']}.jpg"
        assert path in home.text and client.get(path).status_code == 200
    assert service.store.bird_counts() == before
    service.store.add_frame("private-frame", service.settings.config.frame_defaults)
    private = service.prepare("private-frame", "2026-10-08", offline=True)
    assert client.get(f"/display/images/{private['id']}.jpg").status_code == 404
    with service.store.connect() as db:
        db.execute("UPDATE images SET hidden=1 WHERE id=?", (first["id"],))
    assert client.get(f"/display/images/{first['id']}.jpg").status_code == 404
    config = service.settings.config.model_dump()
    config["public_frame_id"] = None
    service.save_configuration(config)
    assert client.get(f"/display/images/{ready['id']}.jpg").status_code == 404
    assert "Coming up" not in client.get("/").text


def test_public_gallery_hides_missing_preview_files(service, frame):
    client = public_client(service, frame)
    record = service.prepare(frame[0], "2026-10-08", offline=True)
    service.cache_path(record["preview_path"]).unlink()
    assert "Next button" not in client.get("/").text
    assert client.get(f"/display/images/{record['id']}.jpg").status_code == 404


def test_public_gallery_deduplicates_shared_prepared_picture_with_both_roles(service, frame):
    from datetime import UTC, datetime

    service.clock = lambda: datetime(2026, 10, 8, 8, 30, tzinfo=UTC)
    client = public_client(service, frame)
    ready = service.prepare(frame[0], "2026-10-08", offline=True)
    with service.store.connect() as db:
        service._publish_slot(
            db,
            frame[0],
            "scheduled",
            ready["id"],
            service.daily_schedule(service.store.frame(frame[0]), service.clock().date())["cycle"],
        )
    home = client.get("/").text
    assert "Daily refresh · Next button" in home
    assert home.count('src="/display/next-daily.jpg"') == 1
    assert f'src="/display/images/{ready["id"]}.jpg"' not in home
