from test_owner import sign_in


def test_focused_management_pages(service, frame, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    home = client.get("/manage").text
    assert "On the frame" in home and "Ready for next refresh" in home
    assert 'name="password"' not in home and 'name="max_birds"' not in home
    assert 'name="max_birds"' in client.get("/manage/appearance").text
    assert 'name="date"' in client.get("/manage/events").text
    assert 'name="latitude"' in client.get("/manage/settings").text
    assert "PhotoFrame - XXXXX" in client.get("/manage/recovery").text
    response = client.post(
        "/manage/public",
        data={"csrf": csrf, "frame": frame[0]},
        headers={"Referer": "https://emviary.majjix.com/manage/settings"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/manage/settings?saved=1"
    assert "Changes saved." in client.get(response.headers["location"]).text
    response = client.post(
        "/manage/public",
        data={"csrf": csrf, "frame": frame[0]},
        headers={"Referer": "https://evil.example/manage/settings"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/manage"


def test_owner_preview_is_last_delivered_not_prepared(service, frame, tmp_path, monkeypatch):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    first = service.prepare(frame[0], "2026-10-08", offline=True)
    service.store.telemetry(frame[0], 80, "v0.6.0", "demo", first["body_hash"])
    service.prepare(frame[0], "2026-10-08", offline=True, force=True)
    response = client.get("/manage/frames/" + frame[0] + "/display")
    assert response.content == service.cache_path(first["preview_path"]).read_bytes()
    assert response.headers["cache-control"] == "no-store"
    client.post(
        "/manage/logout",
        data={
            "csrf": __import__("re")
            .search(r'name="csrf" value="([^"]+)"', client.get("/manage").text)
            .group(1)
        },
    )
    assert client.get("/manage/frames/" + frame[0] + "/display").status_code == 401
