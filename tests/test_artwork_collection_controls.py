from test_owner import sign_in


def test_catalog_filters_and_pagination_preserve_new_context(service, tmp_path, monkeypatch):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    artworks = service.settings.artworks
    example = next(a for a in artworks if a.get("pose"))
    result = client.get(
        "/manage/artwork", params={"style": example["style"], "pose": example["pose"]}
    )
    matching = [
        a
        for a in artworks
        if a.get("style") == example["style"] and a.get("pose") == example["pose"]
    ]
    assert result.text.count('<article class="card library-card artwork-card"') == min(
        24, len(matching)
    )
    assert 'name="style"' in result.text and 'name="pose"' in result.text
    assert "Pose not recorded" in result.text
    result = client.get("/manage/artwork?season=winter&review=unreviewed&sort=least")
    assert "season=winter" in result.text
    assert 'name="review"' not in result.text
    assert "Least rendered" in result.text
    assert "Panel review" not in result.text


def test_selected_bulk_rotation_and_delete_are_atomic_and_guarded(
    service, frame, tmp_path, monkeypatch
):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    approved = [a for a in service.settings.artworks if a["approved"]]
    reference = next(a for a in service.settings.artworks if not a["approved"])
    first = service.prepare(frame[0], offline=True)
    chosen = next(a for a in approved if a["id"] == first["artwork_id"])
    before = (service.settings.art_dir / chosen["asset"]).read_bytes()
    url = "/manage/artwork/bulk"
    payload = {
        "csrf": csrf,
        "action": "exclude",
        "selected_" + chosen["id"]: "1",
        "return": "/manage/artwork?style=test&pose=missing&season=winter&sort=least&p=2",
    }
    assert client.post(url, data={**payload, "csrf": "wrong"}).status_code == 403
    response = client.post(url, data=payload, follow_redirects=False)
    assert response.status_code == 303
    assert "pose=missing&season=winter" in response.headers["location"]
    assert chosen["id"] in service.store.excluded_artworks()
    assert service.cache_path(first["preview_path"]).is_file()
    mixed = {**payload, "action": "include", "selected_" + reference["id"]: "1"}
    assert client.post(url, data=mixed).status_code == 409
    assert chosen["id"] in service.store.excluded_artworks()
    assert (
        client.post(url, data={**payload, "action": "include"}, follow_redirects=False).status_code
        == 303
    )
    assert chosen["id"] not in service.store.excluded_artworks()
    assert (
        client.post(url, data={**payload, "action": "delete"}, follow_redirects=False).status_code
        == 303
    )
    assert chosen["id"] in {a["id"] for a in service.deleted_artwork_entries()}
    assert (service.settings.art_dir / chosen["asset"]).read_bytes() == before
    assert service.cache_path(first["preview_path"]).is_file()
    assert client.post(url, data={"csrf": csrf, "action": "exclude"}).status_code == 400


def test_excluding_final_approved_artwork_is_rejected(service, tmp_path, monkeypatch):
    approved = next(a for a in service.settings.artworks if a["approved"])
    service.settings.artworks = [approved]
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    response = client.post(
        "/manage/artwork/bulk",
        data={"csrf": csrf, "action": "exclude", "selected_" + approved["id"]: "1"},
    )
    assert response.status_code == 409
    assert not service.store.excluded_artworks()
