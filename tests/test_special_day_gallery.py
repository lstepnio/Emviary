from fastapi.testclient import TestClient

from emviary.api import create_app
from emviary.special_day_gallery import CATALOG, FILES, VERSION


def test_approved_collection_is_public_framed_and_cached(service):
    client = TestClient(create_app(service, schedule=False))
    page = client.get("/special-days")
    assert page.status_code == 200
    assert page.text.count("data-special-open=") == 19
    assert page.text.count('class="finished-frame__art"') >= 19
    assert len(CATALOG) == len(FILES) == 19
    assert "my favorite" in page.text.lower()
    assert "/special-days" in client.get("/").text
    assert "Explore special days" in client.get("/").text
    for item in CATALOG:
        response = client.get(f"/special-day-media/{VERSION}/{item['filename']}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert "immutable" in response.headers["cache-control"]
    assert client.get(f"/special-day-media/{VERSION}/catalog.json").status_code == 404
    assert client.get("/special-day-media/old/anything.jpg").status_code == 404
