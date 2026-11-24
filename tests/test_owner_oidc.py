from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from emviary import owner_oidc
from emviary.api import create_app

ORIGIN = "https://emviary.majjix.com"
ISSUER = "https://auth.majjix.com/application/o/emviary/"
AUTH_ORIGIN = "https://auth.majjix.com"


def test_owner_sso_binds_browser_and_grants_only_the_configured_subject(
    service, monkeypatch, tmp_path
):
    secret = tmp_path / "secret"
    secret.write_text("test-client-secret")
    env = {
        "ISSUER": ISSUER,
        "CLIENT_ID": "emviary",
        "CLIENT_SECRET_FILE": str(secret),
        "CALLBACK_URL": ORIGIN + owner_oidc.CALLBACK,
        "OWNER_SUBJECTS": "owner-subject",
    }
    for name, value in env.items():
        monkeypatch.setenv("EMVIARY_OIDC_" + name, value)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    public["kid"] = "test"
    nonce = ""
    subject = "stranger-subject"
    submitted_verifier = ""

    def upstream(request):
        nonlocal submitted_verifier
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": AUTH_ORIGIN + "/authorize",
                    "token_endpoint": AUTH_ORIGIN + "/token",
                    "jwks_uri": ISSUER + "jwks/",
                },
            )
        if request.url.path == "/token":
            fields = parse_qs(request.content.decode())
            submitted_verifier = fields["code_verifier"][0]
            assert fields["redirect_uri"] == [ORIGIN + owner_oidc.CALLBACK]
            now = datetime.now(UTC)
            return httpx.Response(
                200,
                json={
                    "id_token": jwt.encode(
                        {
                            "iss": ISSUER,
                            "aud": "emviary",
                            "sub": subject,
                            "nonce": nonce,
                            "iat": now,
                            "exp": now + timedelta(minutes=5),
                        },
                        key,
                        algorithm="RS256",
                        headers={"kid": "test"},
                    )
                },
            )
        assert request.url.path.endswith("/jwks/")
        return httpx.Response(200, json={"keys": [public]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        owner_oidc.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(upstream)),
    )
    app = create_app(service, schedule=False)
    owner = TestClient(app, base_url=ORIGIN, follow_redirects=False)
    other_browser = TestClient(app, base_url=ORIGIN, follow_redirects=False)
    assert "Sign in with Authentik" in owner.get("/manage/login").text
    assert "Owner password" in owner.get("/manage/login").text

    def start():
        result = owner.get("/manage/login/oidc", params={"return": "https://other.example"})
        assert result.status_code == 307
        params = parse_qs(urlsplit(result.headers["Location"]).query)
        assert params["code_challenge_method"] == ["S256"]
        return {"state": params["state"][0], "code": "code"}, params["nonce"][0]

    callback_params, nonce = start()
    assert other_browser.get(owner_oidc.CALLBACK, params=callback_params).status_code == 400
    assert owner.get(owner_oidc.CALLBACK, params=callback_params).status_code == 403
    assert submitted_verifier
    assert owner.get(owner_oidc.CALLBACK, params=callback_params).status_code == 400
    assert owner.get("/manage/session").status_code == 401

    subject = "owner-subject"
    callback_params, nonce = start()
    success = owner.get(owner_oidc.CALLBACK, params=callback_params)
    assert success.status_code == 303
    assert success.headers["Location"] == "/manage"
    assert "Max-Age=3600" in success.headers["set-cookie"]
    assert owner.get("/manage/session").status_code == 200
