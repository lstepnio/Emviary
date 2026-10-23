from test_owner import sign_in


def test_focused_management_pages(service, frame, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    home = client.get("/manage").text
    assert (
        "Last picture sent to frame" in home and "Daily refresh" in home and "Next button" in home
    )
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


def test_overview_past_compositions_follow_current_and_hide_removed(
    service, frame, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    images = [service.prepare(frame[0], "2026-10-08", offline=True, force=True) for _ in range(4)]
    from test_display_history import observe

    for image in images[:3]:
        observe(service, frame, image)
    service.store.telemetry(frame[0], 80, "v0.8.4", "demo", images[2]["body_hash"])
    home = client.get("/manage").text
    assert "Past compositions" in home
    assert "/manage/images/" + str(images[1]["id"]) + "/preview" in home
    assert "/manage/images/" + str(images[0]["id"]) + "/preview" in home
    assert "/manage/images/" + str(images[3]["id"]) + "/preview" not in home
    with service.store.connect() as db:
        db.execute("UPDATE images SET hidden=1 WHERE id=?", (images[1]["id"],))
    home = client.get("/manage").text
    assert "/manage/images/" + str(images[1]["id"]) + "/preview" not in home
