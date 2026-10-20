import json
from html.parser import HTMLParser

from fastapi.testclient import TestClient
from test_owner import sign_in

from emviary.api import create_app
from emviary.settings import SpecialDay


class Elements(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        self.tags.append((tag, dict(attributes)))


def saved_days(service, frame):
    policy = service.settings.config.frame_defaults.model_copy(
        update={
            "special_days": [
                SpecialDay(
                    id="birthday",
                    date="2026-10-20",
                    label="Birthday <party>",
                    message="Happy birthday!",
                    artwork_id="habird-bubo-virginianus",
                ),
                SpecialDay(
                    id="winter", date="2026-12-01", label="Winter", enabled=False, annual=False
                ),
            ]
        }
    )
    service.store.set_policy(frame[0], policy)
    return service.store.frame(frame[0])


def test_special_days_cards_keep_editing_secondary_and_saved_artwork_visible(
    service, frame, tmp_path, monkeypatch
):
    before = saved_days(service, frame)
    client, _ = sign_in(service, tmp_path, monkeypatch)
    response = client.get("/manage/events?frame=" + frame[0])
    assert response.status_code == 200
    page = response.text
    elements = Elements(page).tags
    cards = [
        attrs for tag, attrs in elements if tag == "article" and attrs.get("class") == "event-card"
    ]
    assert len(cards) == 2
    image = next(
        attrs
        for tag, attrs in elements
        if tag == "img" and attrs.get("src") == "/art-thumbnail/habird-bubo-virginianus"
    )
    assert image["class"] == "event-card-image"
    assert "Birthday &lt;party&gt;" in page and "Test on frame" in page
    assert "Yearly" in page and "One time" in page
    details = [
        attrs
        for tag, attrs in elements
        if tag == "details" and attrs.get("id", "").startswith("event-")
    ]
    assert {attrs["id"] for attrs in details} == {"event-birthday", "event-winter", "event-new"}
    assert all("open" not in attrs for attrs in details)
    switches = [attrs for tag, attrs in elements if tag == "input" and "data-event-toggle" in attrs]
    assert len(switches) == 2 and "checked" in switches[0] and "checked" not in switches[1]
    assert "Higher priority wins; ties use saved order" not in page
    for required in ('name="artwork_id"', "/special-days/import", "/delete", "Artwork collection"):
        assert required in page
    assert service.store.frame(frame[0])["policy"] == before["policy"]


def test_enabled_autosave_preserves_the_whole_day_and_rejects_stale_changes(
    service, frame, tmp_path, monkeypatch
):
    original = saved_days(service, frame)
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    path = "/manage/frames/" + frame[0] + "/special-days/birthday/enabled"
    headers = {"Accept": "application/json"}
    data = {"csrf": csrf, "frame_revision": str(original["config_revision"]), "enabled": "no"}
    result = client.post(path, data=data, headers=headers)
    assert result.status_code == 200
    saved = service.store.frame(frame[0])
    before, after = json.loads(original["policy"]), json.loads(saved["policy"])
    before["special_days"][0]["enabled"] = False
    assert after == before
    assert result.json() == {"enabled": False, "config_revision": saved["config_revision"]}
    assert client.post(path, data=dict(data, enabled="yes"), headers=headers).status_code == 409
    # Repeating the same explicit value is harmless and does not rewrite policy.
    result = client.post(
        path, data=dict(data, frame_revision=saved["config_revision"]), headers=headers
    )
    assert (
        result.status_code == 200 and result.json()["config_revision"] == saved["config_revision"]
    )


def test_toggle_requires_owner_csrf_and_valid_existing_day(service, frame, tmp_path, monkeypatch):
    saved_days(service, frame)
    path = "/manage/frames/" + frame[0] + "/special-days/birthday/enabled"
    anonymous = TestClient(create_app(service, schedule=False))
    assert anonymous.post(path, data={"enabled": "no"}).status_code == 401
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    assert client.post(path, data={"enabled": "no", "csrf": "bad"}).status_code == 403
    assert client.post(path, data={"enabled": "bad", "csrf": csrf}).status_code == 400
    assert (
        client.post(
            path.replace("birthday", "missing"), data={"enabled": "no", "csrf": csrf}
        ).status_code
        == 404
    )
    assert json.loads(service.store.frame(frame[0])["policy"])["special_days"][0]["enabled"]


def test_event_enhancements_are_served_by_csp_permitted_external_asset(
    service, frame, tmp_path, monkeypatch
):
    from emviary.ui import ASSET_VERSION

    client, _ = sign_in(service, tmp_path, monkeypatch)
    response = client.get("/manage/events")
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "<script>" not in response.text
    script = client.get(f"/assets/{ASSET_VERSION}/ui.js")
    assert script.status_code == 200
    assert "__emviaryEventToggles" in script.text
    assert "data-event-toggle" in script.text
