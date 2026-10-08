from io import BytesIO

from PIL import Image
from test_owner import sign_in


def test_history_remove_and_restore_are_recoverable_and_guarded(
    service, frame, tmp_path, monkeypatch
):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    assert "No saved images yet" in client.get("/manage/images").text
    first = service.prepare(frame[0], "2026-10-08", offline=True)
    headers = {"Authorization": "Bearer " + frame[1], "X-Firmware-Version": "v2.19.0"}
    assert client.get("/v1/image", headers=headers).status_code == 200
    newer = service.store.active_image(service.store.frame(frame[0]))
    first_url = f"/manage/images/{first['id']}"
    url = f"/manage/images/{newer['id']}"
    assert client.post(first_url + "/remove", data={"csrf": csrf}).status_code == 409
    assert (
        client.post(url + "/remove", data={"csrf": csrf}, follow_redirects=False).status_code == 303
    )
    assert client.get(url + "/preview").status_code == 404
    removed = client.get("/manage/images?removed=true")
    assert "Restore to history" in removed.text
    assert client.get(url + "/preview?removed=true").status_code == 200
    assert client.post(url + "/restore", data={"csrf": "wrong"}).status_code == 403
    assert (
        client.post(url + "/restore", data={"csrf": csrf}, follow_redirects=False).status_code
        == 303
    )
    assert client.get(url + "/preview").status_code == 200
    assert service.delivered_image(service.store.frame(frame[0]))["id"] == first["id"]


def test_artwork_management_filters_and_exclusion(service, frame, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    assert client.get("/manage/artwork").text.count('<article class="card library-card">') == 24
    result = client.get("/manage/artwork?q=poecile")
    assert "Black-capped Chickadee" in result.text
    assert "<h2>Blue Jay</h2>" not in result.text
    art = next(a for a in service.settings.artworks if a["approved"])
    assert (
        client.post(
            "/manage/artwork/" + art["id"],
            data={"csrf": csrf, "exclude": "1"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert "Restore to rotation" in client.get("/manage/artwork?status=excluded").text
    assert "No artwork matches" in client.get("/manage/artwork?q=unknown-bird-name").text
    assert (
        "Exclude from rotation</button>" not in client.get("/manage/artwork?status=reference").text
    )


def test_special_day_collection_upload_empty_and_review_flow(service, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    assert "Your special-day collection starts here" in client.get("/manage/event-art").text
    output = BytesIO()
    Image.new("RGB", (100, 100), "red").save(output, format="PNG")
    artwork = service.event_art.upload(output.getvalue(), "Winter lights", "Artist <name>")
    result = client.get("/manage/event-art")
    assert "Awaiting review" in result.text
    assert "Artist &lt;name&gt;" in result.text
    assert "Approve for special days" in result.text
    assert "Permanently remove artwork" in result.text
    assert (
        client.post(
            "/manage/event-art/" + artwork["id"],
            data={"csrf": csrf, "action": "approve"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    approved = client.get("/manage/event-art")
    assert "Return to review" in approved.text
