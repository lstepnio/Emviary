"""Optional OIDC login for the existing Emviary owner session."""

import base64
import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from .store import token_hash

CALLBACK = "/manage/login/oidc/callback"
COOKIE = "emviary_oidc"
TRANSACTION_SECONDS = 300
NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class OwnerOIDC:
    issuer: str
    client_id: str
    secret_file: Path
    callback: str
    subjects: frozenset[str]

    @classmethod
    def load(cls):
        names = ("ISSUER", "CLIENT_ID", "CLIENT_SECRET_FILE", "CALLBACK_URL", "OWNER_SUBJECTS")
        values = [os.getenv("EMVIARY_OIDC_" + name, "").strip() for name in names]
        if not any(values):
            return None
        issuer, client_id, secret_file, callback, subjects = values
        try:
            if not all(values):
                raise ValueError
            _origin(issuer)
            _origin(callback)
            if urlsplit(callback).path != CALLBACK or not _subjects(subjects):
                raise ValueError
        except ValueError:
            LOGGER.error("Invalid Emviary OIDC settings. Use the owner password to sign in.")
            return None
        return cls(issuer, client_id, Path(secret_file), callback, _subjects(subjects))


def _subjects(value):
    return frozenset(subject.strip() for subject in value.split(",") if subject.strip())


def _origin(value):
    url = urlsplit(value)
    if url.scheme != "https" or not url.hostname or url.username or url.query or url.fragment:
        raise ValueError("OIDC requires an HTTPS URL without credentials or parameters")
    return (url.scheme, url.hostname, url.port or 443)


async def _metadata(config, browser):
    response = await browser.get(config.issuer.rstrip("/") + "/.well-known/openid-configuration")
    response.raise_for_status()
    data = response.json()
    if data["issuer"] != config.issuer:
        raise ValueError("OIDC issuer mismatch")
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if _origin(data[field]) != _origin(config.issuer):
            raise ValueError("OIDC endpoint origin mismatch")
    return data


async def _subject(config, transaction, code):
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as browser:
        metadata = await _metadata(config, browser)
        response = await browser.post(
            metadata["token_endpoint"],
            auth=(config.client_id, config.secret_file.read_text().strip()),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.callback,
                "code_verifier": transaction["verifier"],
            },
        )
        response.raise_for_status()
        id_token = response.json()["id_token"]
        header = jwt.get_unverified_header(id_token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise ValueError("Unsupported signing key")
        response = await browser.get(metadata["jwks_uri"])
        response.raise_for_status()
        keys = [key for key in response.json()["keys"] if key.get("kid") == header["kid"]]
        if len(keys) != 1:
            raise ValueError("OIDC signing key unavailable")
        claims = jwt.decode(
            id_token,
            jwt.PyJWK.from_dict(keys[0], algorithm="RS256").key,
            algorithms=["RS256"],
            audience=config.client_id,
            issuer=config.issuer,
            options={"require": ["iss", "aud", "exp", "iat", "sub", "nonce"]},
        )
        if claims.get("azp", config.client_id) != config.client_id or (
            isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and "azp" not in claims
        ):
            raise ValueError("OIDC authorized party mismatch")
        if not isinstance(claims["nonce"], str) or not hmac.compare_digest(
            claims["nonce"], transaction["nonce"]
        ):
            raise ValueError("OIDC nonce mismatch")
        return claims["sub"]


def attach_oidc(app, store, safe_return, issue_session):
    config = OwnerOIDC.load()
    if config is None:
        return ""

    @app.get("/manage/login/oidc")
    async def oidc_start(request: Request):
        if request.url.hostname != urlsplit(config.callback).hostname:
            raise HTTPException(400, "Open the configured Emviary sign-in hostname.")
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=False) as browser:
                metadata = await _metadata(config, browser)
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            raise HTTPException(503, "OIDC is unavailable. Use the owner password.") from None

        state, browser_id, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        target = safe_return(request.query_params.get("return"))
        now = datetime.now(UTC)
        with store.connect() as db:
            db.execute(
                "DELETE FROM owner_oidc_transactions WHERE expires_at<=?", (now.isoformat(),)
            )
            db.execute(
                "INSERT INTO owner_oidc_transactions VALUES(?,?,?,?,?,?)",
                (
                    token_hash(state),
                    token_hash(browser_id),
                    nonce,
                    verifier,
                    target,
                    (now + timedelta(seconds=TRANSACTION_SECONDS)).isoformat(),
                ),
            )
        query = urlencode(
            {
                "response_type": "code",
                "client_id": config.client_id,
                "redirect_uri": config.callback,
                "scope": "openid",
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge.rstrip(b"=").decode(),
                "code_challenge_method": "S256",
            }
        )
        response = RedirectResponse(
            metadata["authorization_endpoint"] + "?" + query, headers=NO_STORE
        )
        response.set_cookie(
            COOKIE,
            browser_id,
            secure=True,
            httponly=True,
            samesite="lax",
            max_age=TRANSACTION_SECONDS,
            path=CALLBACK,
        )
        return response

    @app.get(CALLBACK)
    async def oidc_callback(request: Request):
        if request.url.hostname != urlsplit(config.callback).hostname:
            raise HTTPException(400, "Open the configured Emviary sign-in hostname.")
        state, code = request.query_params.get("state", ""), request.query_params.get("code", "")
        browser_id = request.cookies.get(COOKIE, "")
        if not state or not browser_id or len(state) > 128 or not code or len(code) > 2048:
            raise HTTPException(400, "Invalid or expired OIDC sign-in.")
        with store.connect() as db:
            row = db.execute(
                "DELETE FROM owner_oidc_transactions "
                "WHERE state_hash=? AND browser_hash=? AND expires_at>? RETURNING *",
                (token_hash(state), token_hash(browser_id), datetime.now(UTC).isoformat()),
            ).fetchone()
        if row is None:
            raise HTTPException(400, "Invalid or expired OIDC sign-in.")
        try:
            subject = await _subject(config, row, code)
        except (httpx.HTTPError, jwt.PyJWTError, KeyError, OSError, TypeError, ValueError):
            raise HTTPException(403, "OIDC sign-in failed. Use the owner password.") from None
        if subject not in config.subjects:
            raise HTTPException(403, "This account has no Emviary owner access.")
        response = issue_session(safe_return(row["return_url"]), hours=1)
        response.headers.update(NO_STORE)
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="lax", path=CALLBACK)
        return response

    return config.callback.removesuffix("/callback")
