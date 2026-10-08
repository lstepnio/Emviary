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
    assert 'alt="Current frame artwork"' in home.text
    assert 'src="/display.jpg"' in home.text
    assert frame[0] not in home.text and frame[1] not in home.text
    service.prepare(frame[0], "2026-10-08", force=True, offline=True)
    assert client.get("/display.jpg").content == delivered


def test_library_search_sort_and_counts_are_compositions(service):
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
    assert "1 renders · 2 rotation images" in response.text
    assert "2 renders · 1 rotation images" in response.text
    assert "once per composition" in response.text
    assert "not page views" in response.text
    search = client.get("/library", params={"q": "poecile"})
    assert "<h2>Black-capped Chickadee</h2>" in search.text
    assert "<h2>Blue Jay</h2>" not in search.text
    assert chickadee["source_url"] in search.text
    assert chickadee["credit"] in search.text
    assert "CC BY-SA 4.0" in search.text


def test_library_filters_empty_state_and_escape(service):
    client = TestClient(create_app(service, schedule=False))
    response = client.get("/library", params={"q": '<script>alert("x")</script>'})
    assert "No artwork matches" in response.text
    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text
    assert 'href="/library"' in response.text
    reference = client.get("/library?status=reference")
    assert "Web reference only" in reference.text
    assert "0 matching rotation images" in reference.text
    first = client.get("/library")
    assert first.text.count('<article class="card library-card">') == 24
    assert "Page 1 of " in first.text
    assert client.get("/library?p=-4").status_code == 200
