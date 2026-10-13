from test_owner import sign_in


def test_bulk_rotation_accepts_selection_across_loaded_batches_and_is_atomic(
    service, tmp_path, monkeypatch
):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    chosen = [a["id"] for a in service.settings.artworks if a["approved"]][:40]
    payload = {
        "csrf": csrf,
        "action": "exclude",
        "return": "/manage/artwork?sort=least&p=3",
        **{"selected_" + identifier: "1" for identifier in chosen},
    }
    result = client.post("/manage/artwork/bulk", data=payload, follow_redirects=False)
    assert result.status_code == 303
    assert result.headers["location"] == payload["return"]
    assert set(chosen) <= service.store.excluded_artworks()
    before = service.store.excluded_artworks()
    assert (
        client.post(
            "/manage/artwork/bulk", data={**payload, "action": "include", "selected_unknown": "1"}
        ).status_code
        == 404
    )
    assert service.store.excluded_artworks() == before
    result = client.post(
        "/manage/artwork/bulk", data={**payload, "action": "include"}, follow_redirects=False
    )
    assert result.status_code == 303
    assert not set(chosen) & service.store.excluded_artworks()
    too_many = {
        "csrf": csrf,
        "action": "exclude",
        **{"selected_" + str(n): "1" for n in range(501)},
    }
    assert client.post("/manage/artwork/bulk", data=too_many).status_code == 400
