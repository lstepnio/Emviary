from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from emviary.api import create_app
from emviary.thumbnails import thumbnail


def test_gallery_thumbnail_is_small_cached_and_does_not_change_master(service):
    client = TestClient(create_app(service, schedule=False))
    artwork = next(a for a in service.settings.artworks if a["approved"])
    master = service.settings.art_dir / artwork["asset"]
    before = master.read_bytes()
    thumbnail.cache_clear()
    url = "/art-thumbnail/" + artwork["id"]
    response = client.get(url)
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
    with Image.open(BytesIO(response.content)) as image:
        assert image.width <= 480 and image.height <= 360
        with Image.open(master) as source:
            assert abs(image.width / image.height - source.width / source.height) < 0.02
    assert master.read_bytes() == before
    assert client.get(url).content == response.content
    assert thumbnail.cache_info().hits == 1 and thumbnail.cache_info().maxsize == 64
    cached = client.get(url, headers={"If-None-Match": response.headers["etag"]})
    assert cached.status_code == 304 and not cached.content
    assert client.get("/art-thumbnail/unknown-artwork").status_code == 404
    assert 'src="/art-thumbnail/' in client.get("/library").text
    assert client.get("/art/" + artwork["id"]).content == before
