"""Small owner UI. Display and content decisions stay in the backend."""

import hashlib
import hmac
import html
import json
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from .api import config_payload
from .settings import FramePolicy, SpecialDay, cron_for
from .store import token_hash

COOKIE = "eink_owner"


def secret_directory():
    return Path(os.getenv("EINK_SECRET_DIR", "/run/secrets"))


def write_private(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8))
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(value)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def set_password(password):
    if not 16 <= len(password) <= 256:
        raise ValueError("Use an owner password of 16 to 256 characters")
    salt = secrets.token_hex(16)
    value = {
        "salt": salt,
        "hash": hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 300000).hex(),
    }
    write_private(secret_directory() / "owner-auth.json", json.dumps(value))


def password_matches(password):
    try:
        value = json.loads((secret_directory() / "owner-auth.json").read_text())
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(value["salt"]), 300000
        ).hex()
        return hmac.compare_digest(digest, value["hash"])
    except (OSError, ValueError, KeyError):
        return False


def escape(value):
    return html.escape(str(value), quote=True)


def page(title, body):
    return HTMLResponse(
        """<!doctype html><html lang="en"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>"""
        + escape(title)
        + """</title>
    <style>body{margin:0;background:#f4f0e6;color:#343c32;font:16px/1.6 Georgia,serif}
    main{max-width:920px;margin:auto;padding:35px 22px}h1,h2{font-weight:400}
    a{color:#536750}section{border-top:1px solid #d1cbb9;padding:20px 0;margin-top:20px}
    label{display:block;margin:10px 0}input,select,button{font:15px system-ui;padding:8px;
    border:1px solid #c7c5b8;border-radius:3px;background:#fffdf7}button{cursor:pointer}
    input[type=checkbox]{margin-right:10px}.grid{display:grid;grid-template-columns:repeat(auto-fit,
    minmax(210px,1fr));gap:10px 25px}.preview{width:100%;max-width:800px;border:1px solid #d1cbb9}
    .quiet{font:13px/1.5 system-ui;color:#6a6d5d}.error{color:#8c2d23}</style>
    <main><a class="quiet" href="/">Display</a><h1>"""
        + escape(title)
        + "</h1>"
        + body
        + "</main></html>",
        headers={
            "Cache-Control": "no-store",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; img-src 'self'; "
            "style-src 'self' 'unsafe-inline'; script-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'",
        },
    )


def hidden(csrf):
    return '<input type="hidden" name="csrf" value="' + escape(csrf) + '">'


def field(name, label, value, kind="text", extra=""):
    return (
        f'<label>{escape(label)}<br><input type="{kind}" name="{name}" '
        f'value="{escape(value)}" {extra}></label>'
    )


def checkbox(name, label, checked):
    selected = "checked" if checked else ""
    return (
        f'<label><input type="checkbox" name="{name}" value="on" {selected}>{escape(label)}</label>'
    )


async def form(request, base_url):
    origin = request.headers.get("origin")
    if origin and origin != base_url:
        raise HTTPException(403, "Untrusted form origin")
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Use the management form")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise HTTPException(413, "Form is too large")
    return {
        key: values[-1] for key, values in parse_qs(body.decode(), keep_blank_values=True).items()
    }


def attach_owner(app, service):
    failures = {}

    @app.exception_handler(HTTPException)
    async def management_error(request: Request, exc: HTTPException):
        if request.url.path.startswith("/manage"):
            response = page(
                "Management request unavailable",
                "<p>" + escape(exc.detail) + '</p><a href="/manage">Return to management</a>',
            )
            response.status_code = exc.status_code
            return response
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )

    def session(request):
        with service.store.connect() as db:
            row = db.execute(
                "SELECT * FROM owner_sessions WHERE token_hash=? AND expires_at>?",
                (token_hash(request.cookies.get(COOKIE, "")), datetime.now(UTC).isoformat()),
            ).fetchone()
        return dict(row) if row else None

    def require(request):
        value = session(request)
        if not value:
            raise HTTPException(401, "Sign in through /manage/login")
        return value

    async def checked_form(request):
        value = require(request)
        data = await form(request, service.settings.config.public_base_url)
        if not hmac.compare_digest(data.get("csrf", ""), value["csrf"]):
            raise HTTPException(403, "Invalid form token")
        return data

    def redirect():
        return RedirectResponse("/manage", status_code=303)

    @app.get("/manage/login")
    def login_form():
        nonce = secrets.token_urlsafe(24)
        response = page(
            "Manage your frame",
            '<form method="post" action="/manage/login">'
            + hidden(nonce)
            + field(
                "password",
                "Owner password",
                "",
                "password",
                'required maxlength="256" autocomplete="current-password"',
            )
            + "<button>Sign in</button></form>",
        )
        response.set_cookie(
            "eink_login",
            nonce,
            secure=True,
            httponly=True,
            samesite="strict",
            max_age=600,
            path="/manage",
        )
        return response

    @app.post("/manage/login")
    async def login(request: Request):
        data = await form(request, service.settings.config.public_base_url)
        nonce = request.cookies.get("eink_login", "")
        if not nonce or not hmac.compare_digest(nonce, data.get("csrf", "")):
            raise HTTPException(403, "Invalid sign-in form")
        peer = request.headers.get("x-forwarded-for", request.client.host).split(",")[-1].strip()
        now = time.monotonic()
        recent = [t for t in failures.get(peer, []) if t > now - 900]
        if len(recent) >= 5:
            raise HTTPException(429, "Try signing in again in 15 minutes")
        if not password_matches(data.get("password", "")[:256]):
            if len(failures) > 2048:
                failures.clear()
            failures[peer] = recent + [now]
            return page(
                "Sign-in failed",
                '<p>Incorrect password.</p><a href="/manage/login">Try again</a>',
            )
        failures.pop(peer, None)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        with service.store.connect() as db:
            db.execute(
                "DELETE FROM owner_sessions WHERE expires_at<?", (datetime.now(UTC).isoformat(),)
            )
            db.execute(
                "INSERT INTO owner_sessions VALUES(?,?,?)",
                (token_hash(token), csrf, (datetime.now(UTC) + timedelta(hours=8)).isoformat()),
            )
        response = redirect()
        response.set_cookie(
            COOKIE,
            token,
            secure=True,
            httponly=True,
            samesite="strict",
            max_age=28800,
            path="/manage",
        )
        response.delete_cookie("eink_login", path="/manage")
        return response

    @app.post("/manage/logout")
    async def logout(request: Request):
        await checked_form(request)
        with service.store.connect() as db:
            db.execute(
                "DELETE FROM owner_sessions WHERE token_hash=?",
                (token_hash(request.cookies.get(COOKIE, "")),),
            )
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(COOKIE, path="/manage")
        return response

    @app.get("/manage")
    def management(request: Request):
        auth = session(request)
        if not auth:
            return RedirectResponse("/manage/login", status_code=303)
        csrf = auth["csrf"]
        body = (
            '<p class="quiet">Changes apply on the next wake. '
            + '<a href="http://photoframe.local" target="_blank" rel="noopener noreferrer">'
            + "Open local frame controls</a> (on the frame’s Wi-Fi, while awake).</p>"
        )
        statuses = {row["id"]: row for row in service.status()}
        for frame in service.store.frames():
            policy = FramePolicy.model_validate_json(frame["policy"]).model_dump()
            status = statuses[frame["id"]]
            identifier = escape(frame["id"])
            body += (
                "<section><h2>"
                + identifier
                + '</h2><img class="preview" src="/manage/frames/'
                + identifier
                + '/preview">'
            )
            body += (
                '<p class="quiet">Prepared preview. Last contact: '
                + escape(status["last_contact"] or "Not yet")
                + ". Battery: "
                + escape(status["battery"] if status["battery"] is not None else "Unknown")
                + "%.</p>"
            )
            body += (
                '<form method="post" action="/manage/frames/'
                + identifier
                + '/settings">'
                + hidden(csrf)
                + '<div class="grid">'
            )
            body += field(
                "wake", "Daily wake (Denver time)", policy["wake_local_time"], "time", "required"
            )
            body += (
                '<label>Maximum birds<br><select name="max_birds">'
                + "".join(
                    (
                        f'<option value="{n}" '
                        f"{'selected' if n == policy['max_birds'] else ''}>{n}</option>"
                    )
                    for n in (1, 2, 3)
                )
                + "</select></label>"
            )
            body += (
                '<label>Panel color treatment<br><select name="preset">'
                + "".join(
                    "<option "
                    + ("selected " if n == policy["processing_preset"] else "")
                    + ">"
                    + n
                    + "</option>"
                    for n in ("balanced", "dynamic", "vivid", "soft")
                )
                + "</select></label>"
            )
            body += (
                '<label>Dithering<br><select name="dither">'
                + "".join(
                    "<option "
                    + ("selected " if n == policy["dither_algorithm"] else "")
                    + ">"
                    + n
                    + "</option>"
                    for n in ("stucki", "floyd-steinberg", "burkes", "sierra")
                )
                + "</select></label></div>"
            )
            body += checkbox("labels", "Species labels", policy["show_species_name"]) + checkbox(
                "weather", "Subtle daily weather", policy["weather_cues"]
            )
            body += checkbox(
                "forecast_text", "Dated forecast text", policy["show_dated_weather_text"]
            ) + checkbox("season", "Seasonal details", policy["seasonal_themes"])
            body += (
                "<details><summary>Birds to include</summary>"
                '<input type="hidden" name="species_controls" value="1">'
            )
            species = sorted(
                {a["scientific_name"] for a in service.settings.artworks if a["approved"]}
            )
            for index, name in enumerate(species):
                artwork = next(a for a in service.settings.artworks if a["scientific_name"] == name)
                selected = not policy["allowed_species"] or name in policy["allowed_species"]
                body += checkbox("species_" + str(index), artwork["common_name"], selected)
            body += "</details><p><button>Save frame settings</button></p></form>"
            body += (
                '<form method="post" action="/manage/frames/'
                + identifier
                + '/prepare">'
                + hidden(csrf)
                + "<p><button>Prepare a fresh composition</button></p></form>"
            )
            body += '<details><summary>Special days</summary><p class="quiet">'
            body += (
                "A single bird, occasion artwork and your greeting replace the usual layout "
                "on the matching Denver date. The first matching enabled entry wins. "
                "Annual February 29 entries appear only in leap years.</p>"
            )
            for event in [*policy["special_days"], None]:
                day = event or {
                    "id": "",
                    "date": "",
                    "label": "",
                    "message": "",
                    "annual": True,
                    "enabled": True,
                    "theme": "birthday",
                    "artwork_id": None,
                }
                body += (
                    "<h3>"
                    + escape(day["label"] if event else "Add a special day")
                    + '</h3><form method="post" action="/manage/frames/'
                    + identifier
                    + '/special-days">'
                    + hidden(csrf)
                    + '<input type="hidden" name="id" value="'
                    + escape(day["id"])
                    + '">'
                    + '<div class="grid">'
                )
                body += field("date", "Date", day["date"], "date", "required")
                body += field(
                    "label", "Occasion / heading", day["label"], extra='maxlength="40" required'
                )
                body += field(
                    "message", "Greeting (optional)", day["message"], extra='maxlength="80"'
                )
                body += '<label>Artwork theme<br><select name="theme">'
                for value, label in (
                    ("birthday", "Birthday"),
                    ("anniversary", "Anniversary"),
                    ("celebration", "Celebration"),
                    ("remembrance", "Remembrance"),
                ):
                    body += (
                        '<option value="'
                        + value
                        + '" '
                        + ("selected" if day["theme"] == value else "")
                        + ">"
                        + label
                        + "</option>"
                    )
                body += '</select></label><label>Featured bird art<br><select name="artwork_id">'
                body += '<option value="">Choose from the seasonal library</option>'
                counters = {}
                for art in sorted(
                    service.settings.artworks, key=lambda a: (a["common_name"], a["id"])
                ):
                    if not art["approved"] or art.get("depicted_birds", 1) != 1:
                        continue
                    counters[art["common_name"]] = counters.get(art["common_name"], 0) + 1
                    label = (
                        art["common_name"]
                        + " / "
                        + art["source"].split(" /")[0]
                        + " / variant "
                        + str(counters[art["common_name"]])
                    )
                    body += (
                        '<option value="'
                        + escape(art["id"])
                        + '" '
                        + ("selected" if day["artwork_id"] == art["id"] else "")
                        + ">"
                        + escape(label)
                        + "</option>"
                    )
                body += "</select></label></div>"
                body += checkbox("annual", "Repeat every year", day["annual"])
                body += checkbox("enabled", "Enabled", day["enabled"])
                body += (
                    "<button>"
                    + ("Save changes" if event else "Add special day")
                    + "</button></form>"
                )
                if event:
                    body += (
                        '<p><a href="/manage/frames/'
                        + identifier
                        + "/special-days/"
                        + escape(day["id"])
                        + '/preview" target="_blank" rel="noopener">'
                        + "Preview this day</a></p>"
                    )
                    body += (
                        '<form method="post" action="/manage/frames/'
                        + identifier
                        + "/special-days/"
                        + escape(day["id"])
                        + '/delete">'
                        + hidden(csrf)
                        + "<p><button>Remove this day</button></p></form>"
                    )
            body += "</details>"
            body += (
                '<a class="quiet" href="/manage/frames/'
                + identifier
                + '/provision">Download private device configuration</a>'
            )
        config = service.settings.config
        for site in config.sites:
            body += (
                "<section><h2>Locality: "
                + escape(site.id)
                + '</h2><form method="post" action="/manage/sites/'
                + escape(site.id)
                + '">'
                + hidden(csrf)
                + '<div class="grid">'
            )
            body += field(
                "latitude",
                "Latitude",
                site.weather_location.latitude,
                "number",
                'step="any" min="-85" max="85" required',
            )
            body += field(
                "longitude",
                "Longitude",
                site.weather_location.longitude,
                "number",
                'step="any" min="-180" max="180" required',
            )
            body += field(
                "radius",
                "Shared bird locality (km)",
                site.locality_radius_km,
                "number",
                'min="1" max="50" required',
            )
            body += field(
                "prepare",
                "Nightly preparation (Denver time)",
                site.prepare_local_time,
                "time",
                "required",
            )
            body += field(
                "hours",
                "BirdWeather lookback (hours)",
                site.bird_lookback_hours,
                "number",
                'min="1" max="168" required',
            )
            body += field(
                "days",
                "eBird lookback (days)",
                site.providers.ebird.lookback_days,
                "number",
                'min="1" max="30" required',
            )
            body += (
                "</div>"
                + checkbox(
                    "birdweather",
                    "BirdWeather station detections",
                    site.providers.birdweather.enabled,
                )
                + checkbox("ebird", "eBird regional reports", site.providers.ebird.enabled)
                + checkbox("weather", "Open-Meteo forecast", site.providers.open_meteo.enabled)
                + "<button>Save locality and sources</button></form></section>"
            )
        body += (
            '<section><h2>Public display</h2><form method="post" action="/manage/public">'
            + hidden(csrf)
            + '<select name="frame"><option value="">Hide the public image</option>'
        )
        for frame in service.store.frames():
            body += (
                '<option value="'
                + escape(frame["id"])
                + '" '
                + ("selected" if frame["id"] == config.public_frame_id else "")
                + ">"
                + escape(frame["id"])
                + "</option>"
            )
        body += "</select> <button>Save public display</button></form></section>"
        configured = (secret_directory() / "ebird-api-key").is_file()
        body += (
            '<section><h2>eBird access</h2><p class="quiet">Key '
            + ("configured" if configured else "missing")
            + '. Existing keys are never shown.</p><form method="post" action="/manage/ebird-key">'
            + hidden(csrf)
            + field(
                "key",
                "Replace API key",
                "",
                "password",
                'required maxlength="256" autocomplete="off"',
            )
            + "<button>Save key</button></form></section>"
        )
        body += (
            '<section><h2>Add a frame</h2><form method="post" action="/manage/add-frame">'
            + hidden(csrf)
            + field("id", "Frame name", "", "text", 'required pattern="[a-z0-9][a-z0-9-]{0,47}"')
            + '<label>Locality <select name="site">'
            + "".join("<option>" + escape(s.id) + "</option>" for s in config.sites)
            + "</select></label><button>Add frame</button></form></section>"
        )
        body += (
            '<section><h2>Owner password</h2><form method="post" action="/manage/password">'
            + hidden(csrf)
            + field(
                "password",
                "New password (at least 16 characters)",
                "",
                "password",
                'required minlength="16" maxlength="256" autocomplete="new-password"',
            )
            + "<button>Change password and sign out</button></form></section>"
        )
        body += (
            '<form method="post" action="/manage/logout">'
            + hidden(csrf)
            + "<button>Sign out</button></form>"
        )
        return page("Frame management", body)

    @app.get("/manage/frames/{identifier}/preview")
    def preview(identifier: str, request: Request):
        require(request)
        record = service.store.active_image(service.store.frame(identifier))
        if not record:
            raise HTTPException(404, "No prepared preview")
        return FileResponse(
            service.cache_path(record["preview_path"]),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/manage/frames/{identifier}/settings")
    async def frame_settings(identifier: str, request: Request):
        data = await checked_form(request)
        policy = FramePolicy.model_validate_json(
            service.store.frame(identifier)["policy"]
        ).model_dump()
        try:
            policy.update(
                wake_local_time=data["wake"],
                firmware_rotate_cron=cron_for(data["wake"]),
                max_birds=int(data["max_birds"]),
                processing_preset=data["preset"],
                dither_algorithm=data["dither"],
                show_species_name=data.get("labels") == "on",
                weather_cues=data.get("weather") == "on",
                show_dated_weather_text=data.get("forecast_text") == "on",
                seasonal_themes=data.get("season") == "on",
            )
            if data.get("species_controls"):
                species = sorted(
                    {a["scientific_name"] for a in service.settings.artworks if a["approved"]}
                )
                selected = [
                    name
                    for index, name in enumerate(species)
                    if data.get("species_" + str(index)) == "on"
                ]
                if not selected:
                    raise ValueError("Choose at least one species")
                policy["allowed_species"] = selected
            validated = FramePolicy.model_validate(policy)
        except (ValueError, KeyError):
            raise HTTPException(400, "Invalid frame settings") from None
        service.store.set_policy(identifier, validated)
        return redirect()

    @app.post("/manage/frames/{identifier}/special-days")
    async def save_special_day(identifier: str, request: Request):
        data = await checked_form(request)
        policy = FramePolicy.model_validate_json(
            service.store.frame(identifier)["policy"]
        ).model_dump()
        try:
            day_id = data.get("id") or secrets.token_hex(6)
            if data.get("id") and not any(d["id"] == day_id for d in policy["special_days"]):
                raise ValueError("Unknown special day")
            day = SpecialDay.model_validate(
                {
                    "id": day_id,
                    "date": data["date"],
                    "label": data["label"].strip(),
                    "message": data.get("message", "").strip(),
                    "annual": data.get("annual") == "on",
                    "enabled": data.get("enabled") == "on",
                    "theme": data["theme"],
                    "artwork_id": data.get("artwork_id") or None,
                }
            )
            if day.artwork_id:
                art = next(
                    (a for a in service.settings.artworks if a["id"] == day.artwork_id), None
                )
                if (
                    not art
                    or not art["approved"]
                    or art.get("depicted_birds", 1) != 1
                    or int(day.date[5:7]) not in art["months"]
                ):
                    raise ValueError(
                        "Choose bird art eligible in that month, or seasonal selection"
                    )
            if data.get("id"):
                policy["special_days"] = [
                    day.model_dump() if d["id"] == day_id else d for d in policy["special_days"]
                ]
            else:
                policy["special_days"].append(day.model_dump())
            validated = FramePolicy.model_validate(policy)
        except (ValueError, KeyError) as error:
            raise HTTPException(400, "Invalid special day: " + str(error)) from None
        service.store.set_policy(identifier, validated)
        return redirect()

    @app.post("/manage/frames/{identifier}/special-days/{day_id}/delete")
    async def delete_special_day(identifier: str, day_id: str, request: Request):
        await checked_form(request)
        policy = FramePolicy.model_validate_json(
            service.store.frame(identifier)["policy"]
        ).model_dump()
        if not any(d["id"] == day_id for d in policy["special_days"]):
            raise HTTPException(404, "Unknown special day")
        policy["special_days"] = [d for d in policy["special_days"] if d["id"] != day_id]
        service.store.set_policy(identifier, FramePolicy.model_validate(policy))
        return redirect()

    @app.get("/manage/frames/{identifier}/special-days/{day_id}/preview")
    def special_day_preview(identifier: str, day_id: str, request: Request):
        require(request)
        try:
            image = service.preview_special_day(identifier, day_id)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        except RuntimeError:
            raise HTTPException(409, "Preparation is busy; try the preview again shortly") from None
        return Response(image, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/manage/sites/{identifier}")
    async def site_settings(identifier: str, request: Request):
        data = await checked_form(request)
        config = service.settings.config.model_dump()
        site = next((s for s in config["sites"] if s["id"] == identifier), None)
        if site is None:
            raise HTTPException(404, "Unknown locality")
        try:
            site.update(
                weather_location={
                    "latitude": float(data["latitude"]),
                    "longitude": float(data["longitude"]),
                },
                locality_radius_km=int(data["radius"]),
                prepare_local_time=data["prepare"],
                bird_lookback_hours=int(data["hours"]),
            )
            for name, field_name in (
                ("birdweather", "birdweather"),
                ("ebird", "ebird"),
                ("open_meteo", "weather"),
            ):
                site["providers"][name]["enabled"] = data.get(field_name) == "on"
            site["providers"]["ebird"]["lookback_days"] = int(data["days"])
            service.save_configuration(config)
        except (ValueError, KeyError, RuntimeError):
            raise HTTPException(
                400, "Invalid locality settings or preparation in progress"
            ) from None
        return redirect()

    @app.post("/manage/public")
    async def public_settings(request: Request):
        data = await checked_form(request)
        identifier = data.get("frame") or None
        if identifier:
            service.store.frame(identifier)
        config = service.settings.config.model_dump()
        config["public_frame_id"] = identifier
        service.save_configuration(config)
        return redirect()

    @app.post("/manage/ebird-key")
    async def ebird_key(request: Request):
        data = await checked_form(request)
        key = data.get("key", "").strip()
        if not 16 <= len(key) <= 256 or not all(32 < ord(c) < 127 for c in key):
            raise HTTPException(400, "Invalid key format")
        write_private(secret_directory() / "ebird-api-key", key + "\n")
        return redirect()

    @app.post("/manage/password")
    async def password(request: Request):
        data = await checked_form(request)
        try:
            set_password(data.get("password", ""))
        except ValueError:
            raise HTTPException(400, "Use a password of at least 16 characters") from None
        with service.store.connect() as db:
            db.execute("DELETE FROM owner_sessions")
        response = RedirectResponse("/manage/login", status_code=303)
        response.delete_cookie(COOKIE, path="/manage")
        return response

    @app.post("/manage/add-frame")
    async def add_frame(request: Request):
        import re

        data = await checked_form(request)
        identifier = data.get("id", "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", identifier):
            raise HTTPException(400, "Invalid frame name")
        policy = service.settings.config.frame_defaults.model_copy(deep=True)
        policy.site_id = data.get("site", "")
        service.settings.config.site(policy.site_id)
        try:
            token = service.store.add_frame(identifier, policy)
        except Exception:
            raise HTTPException(409, "Frame could not be added; choose a unique name") from None
        write_private(
            service.settings.data_dir / "provisioning" / (identifier + ".token"), token + "\n"
        )
        return redirect()

    @app.get("/manage/frames/{identifier}/provision")
    def provision(identifier: str, request: Request):
        require(request)
        frame = service.store.frame(identifier)
        path = service.settings.data_dir / "provisioning" / (identifier + ".token")
        try:
            token = path.read_text().strip()
        except OSError:
            raise HTTPException(409, "Reprovision this frame through the owner CLI") from None
        identity = service.store.authenticate(token)
        if not identity or identity["id"] != identifier:
            raise HTTPException(409, "Current token file is unavailable")
        config = json.loads(config_payload(frame))["config"]
        config.update(
            image_url=service.settings.config.public_base_url + "/v1/image", access_token=token
        )
        return Response(
            json.dumps(config, indent=2),
            media_type="application/json",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{identifier}.json"',
            },
        )

    @app.post("/manage/frames/{identifier}/prepare")
    async def prepare(identifier: str, request: Request):
        import asyncio

        await checked_form(request)
        try:
            await asyncio.to_thread(service.prepare, identifier, force=True)
        except (RuntimeError, ValueError, OSError):
            return page(
                "Preparation unavailable",
                "<p>The last good image is retained.</p><a href='/manage'>Return</a>",
            )
        return redirect()
