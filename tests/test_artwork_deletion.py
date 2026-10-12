import json

from fastapi.testclient import TestClient
from test_owner import sign_in

from emviary.api import create_app
from emviary.service import Service


def test_delete_is_private_persistent_and_preserves_history(service, frame, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    first = service.prepare(frame[0], offline=True)
    art = next(a for a in service.settings.artworks if a["id"] == first["artwork_id"])
    url = "/manage/artwork/" + art["id"]
    before = (service.settings.art_dir / art["asset"]).read_bytes()
    anonymous = TestClient(create_app(service, schedule=False))
    assert anonymous.post(url + "/delete").status_code == 401
    assert client.post(url + "/delete", data={"csrf": "wrong"}).status_code == 403
    response = client.post(
        url + "/delete",
        data={"csrf": csrf, "return": "/manage/artwork?sort=most&p=2"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/manage/artwork?sort=most&p=2"
    assert art["id"] not in {a["id"] for a in service.settings.artworks}
    assert anonymous.get("/art/" + art["id"]).status_code == 404
    assert anonymous.get("/art-thumbnail/" + art["id"]).status_code == 404
    assert art["id"] not in anonymous.get("/credits.json").text
    assert anonymous.get(url + "/thumbnail").status_code == 401
    assert client.get(url + "/thumbnail").status_code == 200
    assert "Restore artwork" in client.get("/manage/artwork?status=deleted").text
    assert (service.settings.art_dir / art["asset"]).read_bytes() == before
    assert service.cache_path(first["preview_path"]).is_file()
    assert json.loads(first["manifest"])["artwork"]["id"] == art["id"]
    restarted = Service(service.settings, providers=service.providers, converter=service.converter)
    assert art["id"] not in {a["id"] for a in restarted.settings.artworks}
    response = client.post(url + "/restore", data={"csrf": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert client.get("/art/" + art["id"]).content == before


def test_bulk_delete_removes_exactly_artworks_outside_rotation(service, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    excluded_art = next(a for a in service.settings.artworks if a["approved"])
    with service.store.connect() as db:
        db.execute("INSERT INTO excluded_artworks VALUES(?)", (excluded_art["id"],))
    expected = {
        a["id"]
        for a in service.settings.artworks
        if not a["approved"] or a["id"] == excluded_art["id"]
    }
    kept = {a["id"] for a in service.settings.artworks} - expected
    response = client.post(
        "/manage/artwork/bulk-delete", data={"csrf": csrf}, follow_redirects=False
    )
    assert response.status_code == 303
    assert {a["id"] for a in service.settings.artworks} == kept
    assert {a["id"] for a in service.deleted_artwork_entries()} == expected
    # Restoration retains the original excluded state rather than silently activating it.
    client.post("/manage/artwork/" + excluded_art["id"] + "/restore", data={"csrf": csrf})
    assert excluded_art["id"] in service.store.excluded_artworks()
    assert "Keep at least one artwork" not in client.get("/manage/artwork").text


def test_cannot_delete_final_rotation_artwork(service):
    artworks = list(service.settings.artworks)
    try:
        service.delete_artworks([a["id"] for a in artworks])
    except ValueError as exc:
        assert "at least one" in str(exc)
    else:
        raise AssertionError("Deletion must leave a usable rotation")
    assert service.deleted_artwork_entries() == []
