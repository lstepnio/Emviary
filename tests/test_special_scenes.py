import pytest
from test_owner import sign_in

from emviary.settings import SpecialDay
from emviary.special_scenes import scene_art, validate_words


@pytest.mark.parametrize("direction", ["season", "memory"])
@pytest.mark.parametrize("composition", ["scene", "dedication"])
def test_scene_draft_is_read_only(service, frame, tmp_path, monkeypatch, direction, composition):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    identifier = frame[0]
    before = service.store.frame(identifier)
    art = scene_art(direction)
    assert art["approved"] and art["event_only"]
    response = client.post(
        f"/manage/frames/{identifier}/special-day-proof",
        data={
            "csrf": csrf,
            "date": "2026-12-21",
            "label": "A day together",
            "direction": direction,
            "composition": composition,
            "heading": "Questionable directions."
            if direction == "memory"
            else "More daylight. Finally.",
            "message": "Excellent company." if direction == "memory" else "Still better with you.",
        },
    )
    assert response.status_code == 200, response.text[:300] if response.status_code != 200 else ""
    assert response.headers["content-type"] == "image/jpeg"
    assert service.store.frame(identifier) == before
    assert not service.store.active_image(before)


def test_existing_art_retained_and_words_fit(service, frame, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    page = client.get("/manage/events").text
    assert "Seasonal nature" in page and "A personal memory" in page
    assert "Existing art & original layout" in page
    assert "Preview picture" in page
    assert SpecialDay(id="old", date="2026-12-21", label="Original").direction == "existing"
    with pytest.raises(ValueError, match="too wide"):
        validate_words(
            service.settings.art_dir,
            dict(
                direction="memory",
                composition="dedication",
                label="Original",
                heading="W" * 40,
                message="",
            ),
        )
    response = client.post(f"/manage/frames/{frame[0]}/special-day-proof", data={"csrf": "invalid"})
    assert response.status_code in (400, 403)
