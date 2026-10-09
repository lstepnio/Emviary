import json
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from test_owner import sign_in

from emviary.api import create_app
from emviary.settings import FramePolicy, SpecialDay


def anonymous_client(service):
    return TestClient(create_app(service, schedule=False), base_url="https://emviary.majjix.com")


def test_owner_html_auth_redirect_preserves_safe_destination(service, frame):
    client = anonymous_client(service)
    response = client.get(
        "/manage/battery?frame=test-frame",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    destination = urlsplit(response.headers["location"])
    assert destination.path == "/manage/login"
    assert parse_qs(destination.query) == {"return": ["/manage/battery?frame=test-frame"]}
    login = client.get(response.headers["location"])
    assert 'name="return" value="/manage/battery?frame=test-frame"' in login.text
    assert 'class="sidebar"' not in login.text

    assert client.get("/manage/battery", follow_redirects=False).status_code == 401
    assert (
        client.get(
            "/manage/frames/test-frame/preview",
            headers={"Accept": "text/html"},
            follow_redirects=False,
        ).status_code
        == 401
    )
    response = client.post(
        "/manage/frames/test-frame/settings",
        data={"csrf": "expired", "password": "private-sent-value"},
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert "location" not in response.headers
    assert "private-sent-value" not in response.text


@pytest.mark.parametrize(
    ("destination", "expected"),
    [
        ("https://evil.example/manage", "/manage"),
        ("//evil.example/manage", "/manage"),
        ("/manage/login", "/manage"),
        ("/outside", "/manage"),
        ("/manage/battery?frame=test-frame", "/manage/battery?frame=test-frame"),
    ],
)
def test_login_only_returns_to_safe_owner_destination(
    service, frame, tmp_path, monkeypatch, destination, expected
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    login = client.get("/manage/login", params={"return": destination})
    csrf = re.search(r'name="csrf" value="([^"]+)"', login.text).group(1)
    assert f'name="return" value="{expected}"' in login.text
    response = client.post(
        "/manage/login",
        data={
            "csrf": csrf,
            "password": "a-long-test-owner-password",
            "return": destination,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == expected


def test_public_presentation_assets_cache_without_caching_owner_pages(
    service, frame, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    page = client.get("/manage/appearance")
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["x-frame-options"] == "DENY"
    csp = page.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "form-action 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "<style>" not in page.text and "<script>" not in page.text

    public = anonymous_client(service)
    urls = re.findall(r'(?:href|src)="(/assets/[^\"]+/ui\.(?:css|js))"', page.text)
    assert len(urls) == 2
    for url in urls:
        asset = public.get(url)
        assert asset.status_code == 200
        assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert asset.headers["x-content-type-options"] == "nosniff"
        expected_type = "text/css" if url.endswith(".css") else "text/javascript"
        assert asset.headers["content-type"].startswith(expected_type)
    assert public.get("/assets/invalid/ui.css").status_code == 404
    assert public.get(urls[0].replace(".css", ".html")).status_code == 404


def test_validation_error_is_accessible_and_does_not_echo_credentials(
    service, frame, tmp_path, monkeypatch
):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    before = json.loads(service.store.frame(frame[0])["policy"])
    private_password = "private-invalid-wifi-password"
    response = client.post(
        "/manage/frames/test-frame/wifi",
        data={
            "csrf": csrf,
            "action": "save",
            "ssid": "x" * 33,
            "password": private_password,
        },
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 400
    assert 'data-request-error role="alert"' in response.text
    assert private_password not in response.text
    assert csrf not in response.text
    assert json.loads(service.store.frame(frame[0])["policy"]) == before


def test_gallery_removal_restore_retains_context_and_confirms_result(
    service, frame, tmp_path, monkeypatch
):
    first = service.prepare(frame[0], "2026-10-08", offline=True)
    service.prepare(frame[0], "2026-10-08", force=True, offline=True)
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    context = "/manage/images?frame=test-frame&removed=false&offset=24"
    response = client.post(
        f"/manage/images/{first['id']}/remove",
        data={"csrf": csrf, "return": context},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert parse_qs(urlsplit(response.headers["location"]).query) == {
        "frame": ["test-frame"],
        "removed": ["false"],
        "offset": ["24"],
        "result": ["removed"],
    }
    result = client.get(response.headers["location"])
    assert "Image removed from navigation" in result.text
    assert 'role="status"' in result.text
    assert client.get(f"/manage/images/{first['id']}/preview").status_code == 404
    response = client.post(
        f"/manage/images/{first['id']}/restore",
        data={"csrf": csrf, "return": context.replace("false", "true")},
        follow_redirects=False,
    )
    assert parse_qs(urlsplit(response.headers["location"]).query) == {
        "frame": ["test-frame"],
        "removed": ["true"],
        "offset": ["24"],
        "result": ["restored"],
    }
    assert "Image restored to navigation" in client.get(response.headers["location"]).text
    assert client.get(f"/manage/images/{first['id']}/preview").status_code == 200


def test_special_day_html_queue_confirms_service_state_and_keeps_jpeg_compatibility(
    service, frame, tmp_path, monkeypatch
):
    day = SpecialDay(
        id="birthday",
        date="2000-10-08",
        label="Happy Birthday!",
        theme="birthday",
        artwork_id="habird-bubo-virginianus",
    )
    policy = service.settings.config.frame_defaults.model_dump()
    policy["special_days"] = [day.model_dump()]
    service.store.set_policy(frame[0], FramePolicy.model_validate(policy))
    first = service.prepare(frame[0], "2026-10-09", offline=True)
    service.store.telemetry(frame[0], 80, "v0.6.2", "", first["body_hash"])
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    endpoint = "/manage/frames/test-frame/special-days/birthday/preview"
    response = client.post(
        endpoint,
        data={"csrf": csrf},
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    active = service.store.active_image(service.store.frame(frame[0]))
    assert response.headers["location"] == f"/manage/images/{active['id']}/review"
    result = client.get(response.headers["location"])
    assert "Artwork prepared and queued" in result.text
    assert "does not confirm a physical panel update" in result.text
    assert 'role="status"' in result.text
    assert service.delivered_image(service.store.frame(frame[0]))["id"] == first["id"]
    assert json.loads(service.store.frame(frame[0])["policy"])["special_days"] == [day.model_dump()]
    jpeg = client.post(endpoint, data={"csrf": csrf})
    assert jpeg.status_code == 200
    assert jpeg.headers["content-type"] == "image/jpeg"
    assert jpeg.content.startswith(b"\xff\xd8")
    assert service.delivered_image(service.store.frame(frame[0]))["id"] == first["id"]
    service.prepare(frame[0], "2026-10-09", force=True, offline=True)
    historical = client.get(response.headers["location"])
    assert "This is a saved preview. The next-image queue has moved on." in historical.text
    assert "Artwork prepared and queued" not in historical.text
    delivered = client.get(f"/manage/images/{first['id']}/review")
    assert "This artwork was last delivered to the frame." in delivered.text
    assert "Artwork prepared and queued" not in delivered.text


def test_missing_public_page_has_recovery_shell_but_api_stays_json(service):
    client = anonymous_client(service)
    page = client.get("/page-that-does-not-exist", headers={"Accept": "text/html"})
    assert page.status_code == 404
    assert page.headers["content-type"].startswith("text/html")
    assert "Page unavailable" in page.text and "Emviary" in page.text
    assert "Return to the frame" in page.text
    assert 'class="sidebar"' not in page.text
    api = client.get("/v1/endpoint-that-does-not-exist", headers={"Accept": "text/html"})
    assert api.status_code == 404
    assert api.headers["content-type"] == "application/json"
    assert api.json() == {"detail": "Not Found"}


def test_unsaved_special_day_summary_does_not_claim_saved_enabled_state(
    service, frame, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    page = client.get("/manage/events")
    summary = re.search(r'id="event-new"><summary>(.*?)</summary>', page.text).group(1)
    assert "Add a special day" in summary and "New event" in summary
    assert "Enabled" not in summary and "Disabled" not in summary


def test_battery_frame_filter_and_mountain_timestamps(service, frame, tmp_path, monkeypatch):
    other = "second-frame"
    service.store.add_frame(other, service.settings.config.frame_defaults)
    for identifier, percent in ((frame[0], 75), (other, 50)):
        service.store.telemetry(identifier, percent, "v0.6.2", "", "", usb_connected=False)
    timestamp = "2026-10-09T04:22:31.889317+00:00"
    with service.store.connect() as db:
        db.execute("UPDATE battery_samples SET recorded_at=?", (timestamp,))
    client, _ = sign_in(service, tmp_path, monkeypatch)
    filtered = client.get("/manage/battery?frame=test-frame")
    assert filtered.status_code == 200
    assert "test-frame" in filtered.text and other not in filtered.text
    assert "75%" in filtered.text and "50%" not in filtered.text
    assert "Oct 8, 10:22 PM MDT" in filtered.text
    assert timestamp not in filtered.text
    assert "Mountain time" in filtered.text
    assert "View all frames" in filtered.text
    assert other in client.get("/manage/battery").text
    assert client.get("/manage/battery?frame=unknown").status_code == 404
