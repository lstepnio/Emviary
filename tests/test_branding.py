from fastapi.testclient import TestClient

from emviary.api import create_app


def test_branding_and_legacy_frame_endpoint(service):
    app = create_app(service, schedule=False)
    client = TestClient(app, base_url="https://emviary.majjix.com")
    assert "Emviary" in client.get("/").text
    assert app.title == "Emviary"
    old = TestClient(app, base_url="https://eink.majjix.com", follow_redirects=False)
    response = old.get("/manage?example=1")
    assert response.status_code == 308
    assert response.headers["location"] == "https://emviary.majjix.com/manage?example=1"
    assert old.get("/v1/image").status_code == 401
    assert old.get("/healthz").status_code == 200
