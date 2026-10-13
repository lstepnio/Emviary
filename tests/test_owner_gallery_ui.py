from io import BytesIO

from PIL import Image
from test_owner import sign_in


def test_artwork_management_filters_and_exclusion(service, frame, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    assert (
        client.get("/manage/artwork").text.count('<article class="card library-card artwork-card"')
        == 24
    )
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


def test_special_day_collection_upload_empty_and_ready_flow(service, frame, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    assert "No special-day artwork yet" in client.get("/manage/event-art").text
    output = BytesIO()
    Image.new("RGB", (100, 100), "red").save(output, format="PNG")
    artwork = service.event_art.upload(output.getvalue(), "Winter <lights>", "Artist <name>")
    result = client.get("/manage/event-art")
    assert "Awaiting review" not in result.text
    assert "Winter &lt;lights&gt;" in result.text
    assert "Artist &lt;name&gt;" not in result.text
    assert service.event_art.entries()[0]["source"] == "Artist <name>"
    assert "Approve for special days" not in result.text
    assert "Remove artwork" in result.text
    assert artwork["approved"]
    assert "Return to review" not in result.text


def test_artwork_actions_preserve_context_and_clamp_an_empty_last_page(
    service, tmp_path, monkeypatch
):
    from urllib.parse import parse_qs, urlsplit

    template = next(a for a in service.settings.artworks if a["approved"])
    service.settings.artworks = [
        {**template, "id": f"bird-{i:02}", "common_name": f"Chickadee {i:02}"} for i in range(49)
    ]
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    context = "/manage/artwork?q=Chickadee&status=rotation&sort=most&p=2"
    html = client.get(context).text
    assert 'name="return" value="/manage/artwork?q=Chickadee&amp;status=rotation' in html
    assert "data-library-action" in html and "data-library-feedback" in html
    response = client.post(
        "/manage/artwork/bird-24",
        data={"csrf": csrf, "exclude": "1", "return": context},
        follow_redirects=False,
    )
    assert response.status_code == 303 and response.headers["location"] == context
    page = client.get(response.headers["location"])
    assert "Page 2 of 2" in page.text and 'data-artwork-id="bird-24"' not in page.text
    # Restoring from the Excluded filter retains that filter and search as well.
    restore_context = "/manage/artwork?q=Chickadee&status=excluded&sort=least&p=1"
    response = client.post(
        "/manage/artwork/bird-24",
        data={"csrf": csrf, "exclude": "0", "return": restore_context},
        follow_redirects=False,
    )
    assert response.headers["location"] == restore_context
    # Removing the only item on page 3 returns to page 2, rather than page 1.
    response = client.post(
        "/manage/artwork/bird-48",
        data={"csrf": csrf, "exclude": "1", "return": context.replace("p=2", "p=3")},
    )
    assert parse_qs(urlsplit(str(response.url)).query)["p"] == ["2"]
    assert "Page 2 of 2" in response.text
    for invalid in ("https://evil.example", "//evil.example", "/manage/settings"):
        response = client.post(
            "/manage/artwork/bird-24",
            data={"csrf": csrf, "exclude": "0", "return": invalid},
            follow_redirects=False,
        )
        assert response.headers["location"] == "/manage/artwork"
