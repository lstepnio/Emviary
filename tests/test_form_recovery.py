"""Isolated session recovery and safe field-feedback regressions."""

import re

from fastapi import HTTPException
from test_owner import sign_in


def test_open_form_can_refresh_csrf_after_owner_signs_in_again(
    service, frame, tmp_path, monkeypatch
):
    client, old_csrf = sign_in(service, tmp_path, monkeypatch)
    with service.store.connect() as db:
        db.execute("DELETE FROM owner_sessions")
    expired = client.get("/manage/session")
    assert expired.status_code == 401
    assert old_csrf not in expired.text
    login = client.get("/manage/login")
    nonce = re.search(r'name="csrf" value="([^"]+)"', login.text).group(1)
    client.post(
        "/manage/login",
        data={"csrf": nonce, "password": "a-long-test-owner-password"},
        follow_redirects=False,
    )
    fresh = client.get("/manage/session")
    assert fresh.status_code == 200
    assert fresh.headers["cache-control"] == "no-store"
    assert set(fresh.json()) == {"csrf"}
    csrf = fresh.json()["csrf"]
    assert csrf != old_csrf
    # Old tokens remain invalid; fetching recovery metadata does not bypass validation.
    assert client.post("/manage/logout", data={"csrf": old_csrf}).status_code == 403
    assert (
        client.post("/manage/logout", data={"csrf": csrf}, follow_redirects=False).status_code
        == 303
    )
    assert client.get("/manage/session").status_code == 401


def test_structured_error_escapes_feedback_and_limits_field_metadata(
    service, frame, tmp_path, monkeypatch
):
    client, _ = sign_in(service, tmp_path, monkeypatch)

    @client.app.post("/manage/test-field-error")
    def fail():
        raise HTTPException(
            400,
            {"message": "<script>unsafe</script>", "fields": ["ssid", '"<img>'] + ["x"] * 30},
        )

    response = client.post("/manage/test-field-error")
    assert response.status_code == 400
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in response.text
    assert "<script>unsafe" not in response.text
    assert 'data-error-fields="[&quot;ssid&quot;' in response.text
    assert 'role="alert"' in response.text
