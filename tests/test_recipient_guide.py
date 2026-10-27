import json

from fastapi.testclient import TestClient

from emviary.api import create_app
from emviary.settings import FramePolicy


def test_recipient_guide_needs_no_login_and_reads_no_private_frame_data(service, frame):
    policy = FramePolicy(
        wifi_networks=[{"ssid": "PRIVATE-GIFT-WIFI", "password": "PRIVATE-PASSWORD"}],
        management_trusted_wan=True,
    )
    service.store.set_policy(frame[0], policy)
    before = dict(service.store.frame(frame[0]))
    samples = service.store.device_samples(frame[0])
    client = TestClient(create_app(service, schedule=False))
    response = client.get("/guide")
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    assert frame[0] not in response.text and frame[1] not in response.text
    assert "PRIVATE-GIFT-WIFI" not in response.text and "PRIVATE-PASSWORD" not in response.text
    assert dict(service.store.frame(frame[0])) == before
    assert service.store.device_samples(frame[0]) == samples
    assert json.loads(before["policy"])["management_trusted_wan"]


def test_guide_is_discoverable_without_a_registered_public_frame(service):
    config = service.settings.config.model_dump()
    config["public_frame_id"] = None
    service.save_configuration(config)
    client = TestClient(create_app(service, schedule=False))
    assert 'href="/guide"' in client.get("/").text
    guide = client.get("/guide")
    assert guide.status_code == 200
    assert 'href="/guide" aria-current="page"' in guide.text
