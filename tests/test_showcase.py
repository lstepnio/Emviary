from fastapi.testclient import TestClient
from test_owner import sign_in

from emviary.api import create_app
from emviary.showcase import MEDIA_ROOT, MEDIA_TYPES, MEDIA_URL


def test_showcase_is_public_and_all_published_media_are_available(service):
    client = TestClient(create_app(service, schedule=False))
    response = client.get("/showcase")
    assert response.status_code == 200
    assert "autoplay" not in response.text
    assert response.text.count("<video controls") == 4
    assert response.text.count("data-animation-toggle=") == 2
    for filename, media_type in MEDIA_TYPES.items():
        assert MEDIA_URL + "/" + filename in response.text
        result = client.get(MEDIA_URL + "/" + filename, headers={"Range": "bytes=0-63"})
        assert result.status_code in (200, 206)
        assert result.headers["content-type"].startswith(media_type)
        assert result.headers["x-content-type-options"] == "nosniff"


def test_media_route_rejects_unpublished_files_and_versions(service):
    client = TestClient(create_app(service, schedule=False))
    for path in (
        MEDIA_URL + "/prompts.json",
        MEDIA_URL + "/render_motion.py",
        MEDIA_URL + "/missing.webp",
        MEDIA_URL + "/..%2Fapi.py",
        "/showcase-media/unknown/01-studio-front.webp",
    ):
        assert client.get(path).status_code == 404


def test_showcase_video_supports_range_requests_for_seeking(service):
    client = TestClient(create_app(service, schedule=False))
    name = "emviary-showcase-1080p.mp4"
    response = client.get(MEDIA_URL + "/" + name, headers={"Range": "bytes=100-199"})
    assert response.status_code == 206
    assert len(response.content) == 100
    assert response.content == (MEDIA_ROOT / name).read_bytes()[100:200]
    assert response.headers["content-range"].startswith("bytes 100-199/")


def test_owner_frame_surround_keeps_private_delivery_source(service, frame, tmp_path, monkeypatch):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    first = service.prepare(frame[0], "2026-10-08", offline=True)
    service.store.telemetry(frame[0], 80, "v0.6.0", "demo", first["body_hash"])
    home = client.get("/manage").text
    assert 'class="finished-frame__art"' in home
    assert f'src="/manage/frames/{frame[0]}/display"' in home
    assert 'src="/display.jpg"' not in home
    assert 'src="' + MEDIA_URL + '/07-frame-overlay.webp"' in home
    anonymous = TestClient(create_app(service, schedule=False))
    assert anonymous.get(f"/manage/frames/{frame[0]}/display").status_code == 401
