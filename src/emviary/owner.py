"""Small owner UI. Display and content decisions stay in the backend."""

import hashlib
import hmac
import html
import json
import os
import secrets
import time
from datetime import UTC, date, datetime, timedelta
from email import policy as email_policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import config_payload
from .battery import battery_summary, install_battery_routes
from .event_art import MAX_UPLOAD, import_presets
from .service import preparation_lock
from .settings import FramePolicy, SpecialDay, cron_for
from .store import token_hash

COOKIE = "emviary_owner"


def secret_directory():
    return Path(os.getenv("EMVIARY_SECRET_DIR", "/run/secrets"))


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


def page(title, body, **kwargs):
    from .ui import page as render_page

    keys = {
        "Manage your frame": "login",
        "Image history": "images",
        "Artwork rotation": "artwork",
        "Occasion artwork": "event-art",
        "Special-day artwork": "event-art",
        "Battery history": "battery",
        "Battery and charging": "battery",
        "Battery and device health": "battery",
    }
    kwargs.setdefault("active", keys.get(title, "settings"))
    return render_page(title, body, **kwargs)


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

    from .ui import ASSET_VERSION, CSS, JAVASCRIPT

    @app.get("/assets/{version}/ui.{extension}")
    def presentation_asset(version: str, extension: str):
        if version != ASSET_VERSION or extension not in ("css", "js"):
            raise HTTPException(404, "Asset unavailable")
        return Response(
            CSS if extension == "css" else JAVASCRIPT,
            media_type="text/css" if extension == "css" else "text/javascript",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
            },
        )

    destinations = {
        "/manage",
        "/manage/appearance",
        "/manage/events",
        "/manage/settings",
        "/manage/recovery",
        "/manage/images",
        "/manage/artwork",
        "/manage/event-art",
        "/manage/battery",
    }

    def safe_return(value):
        parts = urlsplit(value or "/manage")
        if parts.scheme or parts.netloc or parts.path not in destinations:
            return "/manage"
        return parts.path + ("?" + parts.query[:1024] if parts.query else "")

    def sign_in_redirect(request):
        target = safe_return(
            request.url.path + ("?" + request.url.query if request.url.query else "")
        )
        return RedirectResponse("/manage/login?" + urlencode({"return": target}), status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def management_error(request: Request, exc: HTTPException):
        if request.url.path.startswith("/manage"):
            if (
                exc.status_code == 401
                and request.method == "GET"
                and request.url.path in destinations
                and "text/html" in request.headers.get("accept", "")
            ):
                return sign_in_redirect(request)
            response = page(
                "Management request unavailable",
                '<p class="notice error" data-request-error role="alert">'
                + escape(exc.detail)
                + '</p><div class="actions"><a class="button secondary" '
                'href="/manage">Return to overview</a>'
                + (
                    '<a class="button" href="/manage/login">Sign in</a>'
                    if exc.status_code == 401
                    else ""
                )
                + "</div>",
                active="login" if exc.status_code == 401 else "settings",
            )
            response.status_code = exc.status_code
            return response
        if "text/html" in request.headers.get("accept", "") and not request.url.path.startswith(
            "/v1/"
        ):
            from .ui import page as public_page

            response = public_page(
                "Page unavailable",
                "<section><p>"
                + escape(exc.detail)
                + '</p><a class="button secondary" href="/">Return to the frame</a></section>',
                public=True,
                active="frame",
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

    install_battery_routes(app, service, require, escape, page)

    async def checked_form(request):
        value = require(request)
        data = await form(request, service.settings.config.public_base_url)
        if not hmac.compare_digest(data.get("csrf", ""), value["csrf"]):
            raise HTTPException(403, "Invalid form token")
        return data

    def redirect(request=None):
        target = "/manage"
        if request:
            ref = urlsplit(request.headers.get("referer", ""))
            allowed = {
                "/manage",
                "/manage/appearance",
                "/manage/events",
                "/manage/settings",
                "/manage/recovery",
            }
            if ref.path in allowed and (ref.scheme + "://" + ref.netloc) == str(
                service.settings.config.public_base_url
            ).rstrip("/"):
                query = parse_qs(ref.query)
                target = (
                    ref.path
                    + "?"
                    + urlencode(
                        {
                            "saved": "1",
                            **({"frame": query["frame"][0]} if query.get("frame") else {}),
                        }
                    )
                )
        return RedirectResponse(target, status_code=303)

    @app.get("/manage/login")
    def login_form(request: Request):
        nonce = secrets.token_urlsafe(24)
        response = page(
            "Manage your frame",
            '<form method="post" action="/manage/login">'
            + hidden(nonce)
            + '<input type="hidden" name="return" value="'
            + escape(safe_return(request.query_params.get("return")))
            + '">'
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
            "emviary_login",
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
        nonce = request.cookies.get("emviary_login", "")
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
                '<p class="notice error" role="alert">Incorrect password.</p>'
                '<a class="button" href="/manage/login?'
                + escape(urlencode({"return": safe_return(data.get("return"))}))
                + '">Try again</a>',
                active="login",
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
        response = RedirectResponse(safe_return(data.get("return")), status_code=303)
        response.set_cookie(
            COOKIE,
            token,
            secure=True,
            httponly=True,
            samesite="strict",
            max_age=28800,
            path="/manage",
        )
        response.delete_cookie("emviary_login", path="/manage")
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

    @app.get("/manage/appearance")
    @app.get("/manage/events")
    @app.get("/manage/settings")
    @app.get("/manage/recovery")
    @app.get("/manage")
    def management(request: Request):
        auth = session(request)
        if not auth:
            return sign_in_redirect(request)
        csrf = auth["csrf"]
        view = request.url.path.rsplit("/", 1)[-1]
        titles = {
            "manage": "Your frames",
            "appearance": "Display settings",
            "events": "Special days",
            "settings": "Connections & account",
            "recovery": "Frame recovery",
        }
        body = ""
        if view == "settings":
            body += (
                '<p class="quiet"><a href="http://emviary.local" target="_blank" '
                'rel="noopener">Open local frame controls</a> · <a '
                'href="http://photoframe.local" target="_blank" '
                'rel="noopener">Fallback address</a> · Available on its Wi-Fi '
                "while awake.</p>"
            )
        if request.query_params.get("saved"):
            body += (
                '<p class="notice success" role="status">Changes saved. Frame '
                "changes apply on its next online wake.</p>"
            )
        frames = service.store.frames()
        chosen = request.query_params.get("frame")
        if chosen and not any(f["id"] == chosen for f in frames):
            raise HTTPException(404, "Unknown frame")
        if view in ("appearance", "events", "settings") and len(frames) > 1:
            body += (
                '<form class="toolbar" method="get"><label>Frame<select name="frame">'
                + "".join(
                    "<option "
                    + ("selected " if f["id"] == chosen else "")
                    + 'value="'
                    + escape(f["id"])
                    + '">'
                    + escape(f["id"])
                    + "</option>"
                    for f in frames
                )
                + "</select></label><button>Switch frame</button></form>"
            )
        selected_frames = (
            frames
            if view in ("manage", "recovery")
            else [f for f in frames if f["id"] == (chosen or frames[0]["id"])]
            if frames
            else []
        )
        statuses = {row["id"]: row for row in service.status()}
        for frame in selected_frames:
            policy = FramePolicy.model_validate_json(frame["policy"]).model_dump()
            status = statuses[frame["id"]]
            identifier = escape(frame["id"])
            if view == "manage":
                delivered = service.delivered_image(frame)
                ready = service.store.active_image(frame)
                battery = battery_summary(service, frame["id"])
                body += (
                    '<section class="card"><div class="section-heading"><h2>'
                    + identifier
                    + '</h2></div><div class="frame-status">'
                )
                for label, value in (
                    ("Daily wake", policy["wake_local_time"] + " · Denver"),
                    (
                        "Battery",
                        str(status["battery"]) + "%"
                        if status["battery"] is not None
                        else "Not reported",
                    ),
                    (
                        "Last contact",
                        datetime.fromisoformat(status["last_contact"])
                        .astimezone(ZoneInfo("America/Denver"))
                        .strftime("%b %d, %I:%M %p")
                        if status["last_contact"]
                        else "Waiting for first wake",
                    ),
                ):
                    body += (
                        "<span>" + escape(label) + ": <strong>" + escape(value) + "</strong></span>"
                    )
                body += '</div><div class="current-next"><div><h3>On the frame</h3>'
                body += (
                    (
                        '<img class="preview" alt="Last artwork delivered to this frame" '
                        'src="/manage/frames/'
                    )
                    + identifier
                    + '/display">'
                    if delivered
                    else (
                        '<p class="empty-state">Waiting for the frame to fetch its first '
                        "picture.</p>"
                    )
                )
                body += "</div><div><h3>Ready for next refresh</h3>"
                body += (
                    '<img class="preview" alt="Prepared next artwork" src="/manage/frames/'
                    + identifier
                    + '/preview">'
                    if ready
                    else '<p class="empty-state">No picture prepared yet.</p>'
                )
                body += (
                    '</div></div><p class="quiet">Prepared artwork waits for the next '
                    "wake or next-image button press. This view follows image delivery; "
                    "it cannot confirm the physical panel.</p>"
                )
                if battery["alert"]:
                    body += '<p class="notice" role="alert">' + escape(battery["alert"]) + "</p>"
                body += (
                    '<div class="toolbar">'
                    + "".join(
                        '<a class="button secondary" href="/manage/'
                        + path
                        + "?frame="
                        + identifier
                        + '">'
                        + label
                        + "</a>"
                        for path, label in (
                            ("appearance", "Display settings"),
                            ("events", "Special days"),
                            ("images", "Image history"),
                            ("battery", "Battery & device health"),
                            ("settings", "Wi-Fi networks"),
                        )
                    )
                    + "</div>"
                )
            if view == "appearance":
                body += '<section class="card"><h2>Composition & display</h2>'
                body += (
                    '<form method="post" action="/manage/frames/'
                    + identifier
                    + '/settings">'
                    + hidden(csrf)
                    + '<div class="grid">'
                )
                body += field(
                    "wake",
                    "Daily wake (Denver time)",
                    policy["wake_local_time"],
                    "time",
                    "required",
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
                    + "</select></label></div>"
                )
                body += (
                    "<details><summary>Advanced color processing</summary><p "
                    'class="quiet">Change these only when tuning the physical panel. '
                    "Stucki is the current recommended starting point.</p><div "
                    'class="grid">'
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
                    + "</select></label></div></details>"
                )
                body += (
                    '<details><summary>Firmware updates</summary><p class="quiet">'
                    "Checked each time the frame wakes online. Automatic accepts newer published "
                    "Emviary firmware, including preview releases. Manual requires a "
                    "chosen version; "
                    "disabled keeps the installed firmware.</p>"
                    '<p><a href="https://github.com/lstepnio/Emviary-firmware/releases">'
                    "Firmware releases</a></p>"
                    '<label>Update preference<br><select name="firmware_updates">'
                )
                for value, label in (
                    ("automatic", "Automatic"),
                    ("manual", "Manual"),
                    ("disabled", "Disabled"),
                ):
                    selected = "selected" if policy["firmware_updates"] == value else ""
                    body += f'<option value="{value}" {selected}>{label}</option>'
                body += "</select></label>"
                body += field(
                    "firmware_pinned_version",
                    "Optional release version (for example v0.4.0)",
                    policy["firmware_pinned_version"] or "",
                )
                body += (
                    '<p class="quiet">A chosen version limits updates to that release. '
                    "Older versions are never installed automatically.</p></details>"
                )
                body += "<fieldset><legend>Artwork details</legend>"
                body += checkbox(
                    "location_name", "Show location name", policy["show_location_name"]
                )
                body += checkbox(
                    "labels", "Common bird names", policy["show_species_name"]
                ) + checkbox("weather", "Show weather", policy["weather_cues"])
                body += "<div data-weather-options>"
                body += checkbox(
                    "forecast_temperatures",
                    "High / low temperatures (°F)",
                    policy.get("show_forecast_temperatures", True),
                )
                body += checkbox("weather_icon", "Weather icon", policy["show_weather_icon"])
                body += checkbox(
                    "weather_condition",
                    "Condition text (sunny, etc.)",
                    policy["show_weather_condition"],
                )
                body += "</div>"
                body += checkbox("season", "Seasonal details", policy["seasonal_themes"])
                body += "</fieldset>"
                body += (
                    "<details><summary>Birds to include</summary>"
                    '<input type="hidden" name="species_controls" value="1">'
                    '<div class="actions"><button class="secondary" type="button" '
                    'data-species-choice="all">Select all birds</button>'
                    '<button class="secondary" type="button" '
                    'data-species-choice="none">Clear bird selection</button></div>'
                )
                species = sorted(
                    {a["scientific_name"] for a in service.settings.artworks if a["approved"]}
                )
                for index, name in enumerate(species):
                    artwork = next(
                        a for a in service.settings.artworks if a["scientific_name"] == name
                    )
                    selected = not policy["allowed_species"] or name in policy["allowed_species"]
                    body += checkbox("species_" + str(index), artwork["common_name"], selected)
                body += (
                    '</details><div class="sticky-actions"><button>Save display '
                    'settings</button><span class="quiet">Applies on the next online '
                    "wake.</span></div></form>"
                )
                body += "</section>"
            if view == "settings":
                body += (
                    '<section class="card" id="wifi-networks" aria-labelledby="wifi-heading">'
                    '<h2 id="wifi-heading">Saved Wi-Fi networks</h2><p class="quiet">'
                    "Stage up to five 2.4 GHz networks before gifting. Changes reach the frame "
                    "on its next online artwork fetch. These networks take priority and are added "
                    "to existing device networks, preserving its staging connection. The frame "
                    "holds five networks in total. Removal applies only to networks saved here. "
                    "Passwords are stored privately and never shown.</p>"
                )
                if policy["wifi_networks"] is None:
                    body += (
                        '<p class="quiet">The frame currently manages its own Wi-Fi. Its existing '
                        "networks are kept when adding a gift-location network here.</p>"
                    )
                for network in policy["wifi_networks"] or []:
                    body += (
                        '<form method="post" action="/manage/frames/'
                        + identifier
                        + '/wifi">'
                        + hidden(csrf)
                        + '<input type="hidden" name="ssid" value="'
                        + escape(network["ssid"])
                        + '"><strong>'
                        + escape(network["ssid"])
                        + "</strong>"
                        + field(
                            "password",
                            "New password (blank keeps saved password)",
                            "",
                            "password",
                            'autocomplete="new-password"',
                        )
                        + checkbox("open", "Open network, no password", not network["password"])
                        + '<p><button name="action" value="save">Update network</button> '
                        + '<button name="action" value="remove">Remove network</button></p></form>'
                    )
                body += (
                    '<form method="post" action="/manage/frames/'
                    + identifier
                    + '/wifi">'
                    + hidden(csrf)
                    + field(
                        "ssid", "Network name (SSID)", "", "text", 'required autocomplete="off"'
                    )
                    + field(
                        "password",
                        "Network password",
                        "",
                        "password",
                        'autocomplete="new-password"',
                    )
                    + checkbox("open", "Open network, no password", False)
                    + '<p><button name="action" value="save">Add network</button></p></form>'
                    + "</section>"
                )
            if view == "manage":
                body += (
                    '<form method="post" action="/manage/frames/'
                    + identifier
                    + '/prepare">'
                    + hidden(csrf)
                    + "<p><button>Prepare a fresh composition</button></p></form>"
                )
                body += "</section>"
            if view == "events":
                body += '<section class="card"><h2>Occasions & seasons</h2><p class="quiet">'
                body += (
                    "Your chosen occasion art and greeting replace the usual layout "
                    "on the matching Denver date. The first matching enabled entry wins. "
                    "Annual February 29 entries appear only in leap years.</p>"
                )
                body += (
                    '<p class="notice">1. Add special-day art. 2. Review and approve '
                    "it. 3. Choose it below and enable the event.</p><p><a "
                    'class="button secondary" href="/manage/event-art">Manage '
                    "special-day art</a></p><details><summary>Add holiday or season "
                    "collections</summary>"
                    '<form method="post" action="/manage/frames/'
                    + identifier
                    + '/special-days/import">'
                    + hidden(csrf)
                    + '<label>Add a collection<br><select name="group">'
                    '<option value="holidays">US holidays and celebrations</option>'
                    '<option value="seasons">Meteorological seasons</option></select></label>'
                    + field(
                        "year",
                        "Calendar year",
                        datetime.now().year,
                        "number",
                        'min="2020" max="2100" required',
                    )
                    + '<p class="quiet">Existing entries are kept. '
                    "Fixed holidays and seasons repeat yearly. "
                    "Movable holidays apply to the chosen year. Seasons start March 1, June 1, "
                    "September 1 and December 1 (meteorological seasons). Edit dates and turn "
                    "yearly repeat off for a chosen year's local equinox or solstice. "
                    "New entries start disabled. Review dates and choose artwork, then enable "
                    "the events you want below.</p>"
                    "<button>Add collection</button></form></details>"
                )
                today = datetime.now(ZoneInfo("America/Denver")).date()

                def occasion_date(event):
                    value = date.fromisoformat(event["date"])
                    if event["annual"]:
                        for year in range(today.year, today.year + 9):
                            try:
                                value = value.replace(year=year)
                            except ValueError:
                                continue
                            if value >= today:
                                break
                    return value

                events = sorted(
                    policy["special_days"],
                    key=lambda e: (not e["enabled"], occasion_date(e) < today, occasion_date(e)),
                )
                for event in [None, *events]:
                    day = event or {
                        "id": "",
                        "date": "",
                        "label": "",
                        "message": "",
                        "annual": True,
                        "enabled": True,
                        "theme": "celebration",
                        "artwork_id": None,
                    }
                    body += (
                        '<details class="event-editor" id="event-'
                        + escape(day["id"] or "new")
                        + '"><summary>'
                        + escape(day["label"] if event else "Add a special day")
                        + ' <span class="quiet">'
                        + (
                            escape(occasion_date(day).strftime("%b %-d, %Y"))
                            if event
                            else "New event"
                        )
                        + ((" · Enabled" if day["enabled"] else " · Disabled") if event else "")
                        + "</span></summary>"
                    )
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
                    body += '</select></label><label>Featured artwork<br><select name="artwork_id">'
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
                    for art in service.event_art.entries():
                        if art["approved"]:
                            body += (
                                '<option value="'
                                + escape(art["id"])
                                + '" '
                                + ("selected" if day["artwork_id"] == art["id"] else "")
                                + ">"
                                + escape("Occasion art / " + art["common_name"])
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
                            '<form method="post" action="/manage/frames/'
                            + identifier
                            + "/special-days/"
                            + escape(day["id"])
                            + '/preview">'
                            + hidden(csrf)
                            + '<button class="secondary">Preview this day &amp; '
                            "queue on frame</button>"
                            + '<p class="muted">Uses today’s weather. Available on the next '
                            "refresh or right-button press; the calendar stays "
                            "unchanged.</p></form>"
                        )
                        body += (
                            '<form method="post" action="/manage/frames/'
                            + identifier
                            + "/special-days/"
                            + escape(day["id"])
                            + '/delete">'
                            + hidden(csrf)
                            + '<p><button class="danger">Remove this day</button></p></form>'
                        )
                    body += "</details>"
                body += "</section>"
            if view == "recovery":
                body += (
                    '<a class="quiet" href="/manage/frames/'
                    + identifier
                    + '/provision">Download private device configuration</a> · '
                    + '<a href="/manage/frames/'
                    + identifier
                    + '/provision?import_file=true">Download recovery import file</a> · '
                    + '<a href="#recovery">Recovery instructions</a>'
                )
        if view == "recovery":
            body += (
                '<section id="recovery"><h2>Frame recovery and Wi-Fi setup</h2>'
                "<details><summary>Wake or restart an unresponsive frame</summary>"
                "<p>Connect USB power and briefly press the green wake button. "
                "Sleeping is normal: the picture should remain visible, while local controls "
                "are unavailable until the frame wakes. On its Wi-Fi, open "
                '<a href="http://emviary.local">emviary.local</a>, or '
                '<a href="http://photoframe.local">photoframe.local</a>. '
                "If neither resolves, use the frame’s IP address from your router. "
                "Avoid guest-network isolation when using local controls.</p>"
                "<p>An ordinary reboot keeps saved settings. On firmware v0.5.0 or later, "
                "the left white button requests the previous image and the right white "
                "button requests the next image. Neither clears the panel. "
                "These buttons do not factory-reset "
                "Emviary firmware.</p></details>"
                "<details><summary>Reconnect after a factory reset</summary>"
                "<p>A factory reset from local Settings erases saved Wi-Fi, the cloud token, "
                "and device settings, but leaves the installed firmware. Cloud artwork and "
                "management settings remain on the server. Keep USB connected during recovery.</p>"
                "<ol><li>While signed in here, download the <strong>recovery import file</strong> "
                "for the existing frame below. Save it before switching Wi-Fi.</li>"
                "<li>After reset, join the frame’s temporary open hotspot "
                "<strong>PhotoFrame - XXXXX</strong> (five device-specific characters, "
                "also shown on the setup screen). It has no Wi-Fi password. Choose "
                "“stay connected” if your phone reports no internet. The current firmware "
                "still uses this hotspot name even if a dialog says Emviary.</li>"
                '<li>Open <a href="http://192.168.4.1/provision">http://192.168.4.1/provision</a> '
                "if setup does not appear automatically. Choose your home’s 2.4 GHz Wi-Fi "
                "and enter its password. Use automatic IP / DHCP for a new location. "
                "The frame tests the connection and restarts after a successful setup.</li>"
                "<li>Reconnect your phone or computer to the home Wi-Fi. Wake the frame "
                "if needed, open emviary.local (or its router IP), and open "
                "<strong>Settings → Maintenance → Config Backup → Import Config</strong>. "
                "Select the recovery import file and confirm Import. This restores the "
                "cloud connection and wake schedule without replacing the Wi-Fi "
                "you just set up.</li>"
                "<li>Request a refresh with the right white button or local image controls. "
                "Confirm the picture returns and “Last contact” above advances. "
                "Cloud-managed Wi-Fi and display preferences arrive on the next online fetch. "
                "The factory reset also removes any local device password; set it again "
                "in local advanced network settings if you previously used one.</li></ol>"
                "<p>The recovery file contains the frame’s private access token and grants "
                "access to its image service. Keep it private. Use the existing frame’s "
                "file, rather than adding a new frame entry.</p></details>"
                "<details><summary>No setup hotspot, or no saved network is available</summary>"
                "<p>A frame with saved credentials keeps trying those networks; a normal "
                "reboot does not turn it into a setup hotspot. Restore a saved network, "
                "or temporarily create a 2.4 GHz phone/router hotspot with that saved "
                "SSID and password. Then wake it, open local Settings, and add the new "
                "network or deliberately factory-reset it using the procedure above.</p>"
                "<p>If you cannot recreate any saved network or reach local controls, "
                "contact the maintainer for USB recovery. Replacing firmware with stock "
                "firmware requires reinstalling Emviary first; a configuration import "
                "alone does not restore our firmware features.</p></details></section>"
            )
        config = service.settings.config
        if view == "settings":
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
                body += '<label>Bird-selection area<select name="bird_area">'
                for value, label in (
                    ("local", "Near the weather location"),
                    ("colorado", "All Colorado"),
                ):
                    selected = " selected" if site.bird_area == value else ""
                    body += f'<option value="{value}"{selected}>{label}</option>'
                body += "</select></label>"
                body += field(
                    "radius",
                    "Local bird radius (km; ignored for All Colorado)",
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
                + (
                    '<label>Frame to share<select name="frame"><option value="">Hide '
                    "the public image</option>"
                )
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
            body += "</select></label><button>Save public display</button></form></section>"
            configured = (secret_directory() / "ebird-api-key").is_file()
            body += (
                '<section><h2>eBird access</h2><p class="quiet">Key '
                + ("configured" if configured else "missing")
                + (
                    '. Existing keys are never shown.</p><form method="post" '
                    'action="/manage/ebird-key">'
                )
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
        if view == "manage":
            body += (
                (
                    '<details class="card"><summary>Add another frame</summary><form '
                    'method="post" action="/manage/add-frame">'
                )
                + hidden(csrf)
                + field(
                    "id", "Frame name", "", "text", 'required pattern="[a-z0-9][a-z0-9-]{0,47}"'
                )
                + '<label>Locality <select name="site">'
                + "".join("<option>" + escape(s.id) + "</option>" for s in config.sites)
                + "</select></label><button>Add frame</button></form></details>"
            )
        if view == "settings":
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
        if not frames and view != "settings":
            body += (
                '<p class="empty-state">Add your first frame from the overview to '
                "start curating its display.</p>"
            )
        return page(titles[view], body, active="overview" if view == "manage" else view)

    @app.get("/manage/images")
    def image_gallery(
        request: Request, frame: str | None = None, offset: int = 0, removed: bool = False
    ):
        from urllib.parse import urlencode

        auth = require(request)
        offset = max(0, offset)
        with service.store.connect() as db:
            records = db.execute(
                "SELECT * FROM images WHERE hidden=?"
                + (" AND frame_id=?" if frame else "")
                + " ORDER BY id DESC LIMIT 25 OFFSET ?",
                (int(removed), frame, offset) if frame else (int(removed), offset),
            ).fetchall()
        body = (
            '<header class="page-header"><h1>Your images</h1><p class="page-description">'
            "Revisit saved compositions. Removing an image takes it out of navigation; "
            "you can restore it until normal history cleanup expires its files.</p></header>"
            '<form class="toolbar" method="get" action="/manage/images">'
            '<label>Frame<select name="frame"><option value="">All frames</option>'
        )
        frames = service.store.frames()
        delivered = {f["id"]: service.delivered_image(f) for f in frames}
        for item in frames:
            body += (
                '<option value="'
                + escape(item["id"])
                + '"'
                + (" selected" if frame == item["id"] else "")
                + ">"
                + escape(item["id"])
                + "</option>"
            )
        body += (
            '</select></label><label>Collection<select name="removed">'
            '<option value="false"'
            + (" selected" if not removed else "")
            + ">Saved images</option>"
            '<option value="true"' + (" selected" if removed else "") + ">Removed images</option>"
            '</select></label><button>Apply filters</button></form><div class="card-grid">'
        )
        notices = {
            "removed": "Image removed from navigation. You can restore it from Removed images.",
            "restored": "Image restored to navigation.",
        }
        if request.query_params.get("result") in notices:
            body = (
                '<p class="notice success" role="status">'
                + notices[request.query_params["result"]]
                + "</p>"
                + body
            )
        for record in records[:24]:
            current = delivered.get(record["frame_id"])
            current = current and current["id"] == record["id"]
            plan = json.loads(record["manifest"])
            birds = ", ".join(a["common_name"] for a in plan.get("artworks", [plan["artwork"]]))
            body += (
                '<article class="card library-card"><img class="preview" loading="lazy" '
                'src="/manage/images/'
                + str(record["id"])
                + "/preview"
                + ("?removed=true" if removed else "")
                + '" alt="'
                + escape(birds)
                + '">'
                "<h2>"
                + escape(birds)
                + '</h2><p class="quiet">'
                + escape(record["frame_id"])
                + " · "
                + escape(record["local_date"])
                + " · Version "
                + str(record["revision"])
                + "</p>"
            )
            if current:
                body += (
                    '<p class="pill">Last delivered to the frame</p><p class="quiet">'
                    "Advance the frame before removing this image.</p>"
                )
            else:
                body += (
                    '<form method="post" action="/manage/images/'
                    + str(record["id"])
                    + ("/restore" if removed else "/remove")
                    + '">'
                    + hidden(auth["csrf"])
                    + '<input type="hidden" name="return" value="'
                    + escape(request.url.path + "?" + request.url.query)
                    + '">'
                    + '<button class="secondary">'
                    + ("Restore to history" if removed else "Remove from history")
                    + "</button></form>"
                )
            body += "</article>"
        body += "</div>"
        if not records:
            body += (
                '<section class="empty-state"><h2>'
                + ("No removed images" if removed else "No saved images yet")
                + "</h2><p>"
                + (
                    "Removed images appear here while their files are retained."
                    if removed
                    else "Prepared artwork will appear here, ready to revisit on the frame."
                )
                + "</p></section>"
            )
        parameters = {"removed": str(removed).lower(), **({"frame": frame} if frame else {})}
        body += '<nav class="toolbar" aria-label="Image history pages">'
        if offset:
            body += (
                '<a class="button secondary" href="/manage/images?'
                + escape(urlencode({**parameters, "offset": max(0, offset - 24)}))
                + '">Newer images</a>'
            )
        if len(records) > 24:
            body += (
                '<a class="button secondary" href="/manage/images?'
                + escape(urlencode({**parameters, "offset": offset + 24}))
                + '">Older images</a>'
            )
        body += "</nav>"
        return page("Your images", body, active="images")

    @app.get("/manage/images/{image_id}/review")
    def queued_review(image_id: int, request: Request):
        require(request)
        with service.store.connect() as db:
            image = db.execute(
                "SELECT * FROM images WHERE id=? AND hidden=0", (image_id,)
            ).fetchone()
        if not image:
            raise HTTPException(404, "This preview is no longer available")
        frame = service.store.frame(image["frame_id"])
        delivered = service.delivered_image(frame)
        if frame["active_image_id"] == image_id:
            message = (
                "Artwork prepared and queued. It is available on the next wake "
                "or next-image button press."
            )
        elif delivered and delivered["id"] == image_id:
            message = (
                "This artwork was last delivered to the frame. Another image may be ready next."
            )
        else:
            message = "This is a saved preview. The next-image queue has moved on."
        body = (
            '<section class="preview-result"><p class="notice success" role="status">'
            + escape(message)
            + "</p>"
            f'<img class="preview" width="800" height="480" '
            f'src="/manage/images/{image_id}/preview" alt="Special-day '
            f'artwork">'
            '<p class="quiet">The calendar is unchanged. This preview does not '
            "confirm a physical panel update.</p>"
            '<div class="actions"><a class="button" href="/manage">View frame '
            "&amp; next artwork</a>"
            '<a class="button secondary" href="/manage/events?frame='
            + escape(image["frame_id"])
            + '">Back to special days</a></div></section>'
        )
        return page("Special-day preview", body, active="events")

    @app.get("/manage/images/{image_id}/preview")
    def history_preview(image_id: int, request: Request, removed: bool = False):
        require(request)
        with service.store.connect() as db:
            record = db.execute(
                "SELECT * FROM images WHERE id=? AND hidden=?", (image_id, int(removed))
            ).fetchone()
        if not record or not service.cache_path(record["preview_path"]).is_file():
            raise HTTPException(404, "Image unavailable")
        return FileResponse(
            service.cache_path(record["preview_path"]),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    def history_return(data, result):
        target = safe_return(data.get("return"))
        parts = urlsplit(target)
        if parts.path != "/manage/images":
            parts = urlsplit("/manage/images")
        values = parse_qs(parts.query)
        params = {k: values[k][-1] for k in ("frame", "removed", "offset") if k in values}
        return "/manage/images?" + urlencode({**params, "result": result})

    @app.post("/manage/images/{image_id}/remove")
    async def remove_image(image_id: int, request: Request):
        data = await checked_form(request)
        with preparation_lock(service.settings.data_dir):
            with service.store.connect() as db:
                record = db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
                if not record:
                    raise HTTPException(404, "Unknown image")
                frame = service.store.frame(record["frame_id"])
                displayed = service.delivered_image(frame)
                if displayed and displayed["id"] == image_id:
                    raise HTTPException(
                        409, "Advance the frame before removing its displayed image"
                    )
                db.execute("UPDATE images SET hidden=1 WHERE id=?", (image_id,))
            if frame["active_image_id"] == image_id:
                service.store.request_refill(frame["id"], image_id)
        return RedirectResponse(
            history_return(data, "removed"),
            status_code=303,
            background=BackgroundTask(service.refill_pending),
        )

    @app.post("/manage/images/{image_id}/restore")
    async def restore_image(image_id: int, request: Request):
        data = await checked_form(request)
        with preparation_lock(service.settings.data_dir):
            with service.store.connect() as db:
                record = db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
                if not record:
                    raise HTTPException(404, "Unknown image")
                if not all(
                    service.cache_path(record[key]).is_file() for key in ("path", "preview_path")
                ):
                    raise HTTPException(409, "This image has expired from storage")
                db.execute("UPDATE images SET hidden=0 WHERE id=?", (image_id,))
        return RedirectResponse(history_return(data, "restored"), status_code=303)

    @app.get("/manage/artwork")
    def artwork_management(
        request: Request, q: str = "", status: str = "", sort: str = "name", p: int = 1
    ):
        from urllib.parse import urlencode

        auth = require(request)
        excluded = service.store.excluded_artworks()
        counts = service.store.bird_counts()
        q = q.strip()[:200]
        status = status if status in {"rotation", "excluded", "reference"} else ""
        sort = sort if sort in {"name", "most", "least"} else "name"
        works = [
            a
            for a in service.settings.artworks
            if q.casefold()
            in " ".join(
                str(a.get(k, "")) for k in ("common_name", "scientific_name", "credit", "id")
            ).casefold()
            and (
                not status
                or (status == "excluded" and a["id"] in excluded)
                or (status == "rotation" and a["approved"] and a["id"] not in excluded)
                or (status == "reference" and not a["approved"])
            )
        ]
        works.sort(
            key=lambda a: (
                -counts.get(a["scientific_name"], 0)
                if sort == "most"
                else counts.get(a["scientific_name"], 0)
                if sort == "least"
                else 0,
                a["common_name"],
                a["id"],
            )
        )
        pages = max(1, (len(works) + 23) // 24)
        p = min(max(p, 1), pages)
        body = (
            '<header class="page-header"><h1>Artwork library</h1>'
            '<p class="page-description">Choose which illustrations can appear in future '
            "compositions. Exclusions leave the artwork already on the frame "
            "unchanged.</p></header>"
            '<form class="toolbar" method="get" action="/manage/artwork"><label>Search'
            '<input type="search" name="q" value="'
            + escape(q)
            + '" placeholder="Bird, scientific name or artist"></label>'
        )
        for name, label, options, selected in (
            (
                "status",
                "Availability",
                [
                    ("", "All artwork"),
                    ("rotation", "In rotation"),
                    ("excluded", "Excluded"),
                    ("reference", "References and review"),
                ],
                status,
            ),
            (
                "sort",
                "Sort",
                [("name", "Name A to Z"), ("most", "Most rendered"), ("least", "Least rendered")],
                sort,
            ),
        ):
            body += "<label>" + label + '<select name="' + name + '">'
            for value, text in options:
                body += (
                    '<option value="'
                    + value
                    + '"'
                    + (" selected" if selected == value else "")
                    + ">"
                    + text
                    + "</option>"
                )
            body += "</select></label>"
        body += (
            '<button>Apply filters</button><a class="button secondary" '
            'href="/manage/artwork">Reset</a></form>'
            '<p class="quiet">' + str(len(works)) + " artworks match. Species render counts "
            "include successful compositions, including images later removed from history.</p>"
            '<div class="card-grid">'
        )
        for art in works[(p - 1) * 24 : p * 24]:
            excluded_art = art["id"] in excluded
            label = (
                "Excluded"
                if excluded_art
                else "In rotation"
                if art["approved"]
                else "Reference or review pending"
            )
            body += (
                '<article class="card library-card"><img class="artwork-thumb" '
                'loading="lazy" src="/art-thumbnail/'
                + escape(art["id"])
                + '" alt="'
                + escape(art["common_name"])
                + '"><h2>'
                + escape(art["common_name"])
                + '</h2><p class="quiet"><i>'
                + escape(art["scientific_name"])
                + '</i></p><p class="pill">'
                + label
                + "</p><p>"
                + str(counts.get(art["scientific_name"], 0))
                + " species renders</p><details><summary>Artwork details and credit</summary><p>"
                + escape(art.get("credit", ""))
                + '</p><p class="quiet">'
                + escape(art["id"])
                + '</p><a href="'
                + escape(art["source_url"])
                + '">Source artwork</a></details>'
            )
            if art["approved"]:
                body += (
                    '<form method="post" action="/manage/artwork/'
                    + escape(art["id"])
                    + '">'
                    + hidden(auth["csrf"])
                    + '<input type="hidden" name="exclude" value="'
                    + ("0" if excluded_art else "1")
                    + '"><button class="secondary">'
                    + ("Restore to rotation" if excluded_art else "Exclude from rotation")
                    + "</button></form>"
                )
            body += "</article>"
        body += "</div>"
        if not works:
            body += (
                '<section class="empty-state"><h2>No artwork matches</h2>'
                "<p>Try another search or reset your filters.</p></section>"
            )
        if pages > 1:
            body += '<nav class="toolbar" aria-label="Artwork pages">'
            for number, label in ((p - 1, "Previous"), (p + 1, "Next")):
                if 1 <= number <= pages:
                    body += (
                        '<a class="button secondary" href="/manage/artwork?'
                        + escape(urlencode({"q": q, "status": status, "sort": sort, "p": number}))
                        + '">'
                        + label
                        + "</a>"
                    )
            body += '<span class="quiet">Page ' + str(p) + " of " + str(pages) + "</span></nav>"
        body += '<p><a href="/library">Browse full artwork provenance and licenses</a></p>'
        return page("Artwork library", body, active="artwork")

    @app.post("/manage/artwork/{artwork_id}")
    async def artwork_rotation(artwork_id: str, request: Request):
        data = await checked_form(request)
        if not any(a["id"] == artwork_id for a in service.settings.artworks):
            raise HTTPException(404, "Unknown artwork")
        with preparation_lock(service.settings.data_dir):
            with service.store.connect() as db:
                if data.get("exclude") == "1":
                    db.execute("INSERT OR IGNORE INTO excluded_artworks VALUES(?)", (artwork_id,))
                else:
                    db.execute("DELETE FROM excluded_artworks WHERE id=?", (artwork_id,))
            if data.get("exclude") == "1":
                for frame in service.store.frames():
                    image = service.store.active_image(frame)
                    if image:
                        plan = json.loads(image["manifest"])
                        if any(
                            a["id"] == artwork_id for a in plan.get("artworks", [plan["artwork"]])
                        ):
                            service.store.request_refill(frame["id"], image["id"])
        return RedirectResponse(
            "/manage/artwork", status_code=303, background=BackgroundTask(service.refill_pending)
        )

    @app.get("/manage/frames/{identifier}/display")
    def delivered_preview(identifier: str, request: Request):
        require(request)
        record = service.delivered_image(service.store.frame(identifier))
        if not record:
            raise HTTPException(404, "No image delivered yet")
        return FileResponse(
            service.cache_path(record["preview_path"]),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

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
                firmware_updates=data.get("firmware_updates", policy["firmware_updates"]),
                firmware_pinned_version=(
                    data.get("firmware_pinned_version", policy["firmware_pinned_version"]) or None
                ),
                processing_preset=data["preset"],
                dither_algorithm=data["dither"],
                show_species_name=data.get("labels") == "on",
                show_location_name=data.get("location_name", data.get("location_date")) == "on",
                weather_cues=data.get("weather") == "on",
                show_weather_icon=data.get("weather_icon") == "on",
                show_weather_condition=data.get("weather_condition") == "on",
                show_forecast_temperatures=data.get("forecast_temperatures") == "on",
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
        except (ValueError, KeyError) as error:
            message = (
                "Choose at least one bird to include."
                if str(error) == "Choose at least one species"
                else "Check the daily wake time, bird count and processing settings. "
                "Nothing was saved."
            )
            raise HTTPException(400, message) from None
        service.store.set_policy(identifier, validated)
        return redirect(request)

    @app.post("/manage/frames/{identifier}/wifi")
    async def save_wifi(identifier: str, request: Request):
        data = await checked_form(request)
        policy = FramePolicy.model_validate_json(
            service.store.frame(identifier)["policy"]
        ).model_dump()
        networks = policy["wifi_networks"] or []
        forgotten = policy["wifi_forget_ssids"]
        ssid = data.get("ssid", "")
        existing = next((n for n in networks if n["ssid"] == ssid), None)
        try:
            if data.get("action") == "remove":
                if existing is None:
                    raise ValueError("Network is not cloud managed")
                networks.remove(existing)
                if ssid not in forgotten:
                    forgotten.append(ssid)
            elif data.get("action") == "save":
                password = data.get("password", "")
                if data.get("open") == "on":
                    password = ""
                elif not password:
                    if existing is None or not existing["password"]:
                        raise ValueError("Enter a password or choose open network")
                    password = existing["password"]
                network = {"ssid": ssid, "password": password}
                if existing is not None:
                    networks[networks.index(existing)] = network
                else:
                    networks.append(network)
                forgotten = [name for name in forgotten if name != ssid]
            else:
                raise ValueError("Unknown Wi-Fi action")
            policy["wifi_networks"] = networks
            policy["wifi_forget_ssids"] = forgotten
            validated = FramePolicy.model_validate(policy)
            payload = config_payload({"policy": validated.model_dump_json()})
            if len(payload.encode()) > 1900:
                raise ValueError("Network settings exceed the frame configuration limit")
        except ValueError:
            raise HTTPException(
                400,
                "Invalid Wi-Fi settings. Use up to 5 unique networks, SSID up to 32 UTF-8 "
                "bytes, and a password of 8 to 63 ASCII characters (or 64 hex digits). "
                "Choose open explicitly for a network without a password.",
            ) from None
        service.store.set_policy(identifier, validated)
        return redirect(request)

    @app.get("/manage/event-art")
    def event_art_collection(request: Request):
        csrf = require(request)["csrf"]
        body = (
            '<header class="page-header"><h1>Special-day art</h1><p class="page-description">'
            "Make holidays, seasons and personal occasions your own. These images stay "
            "out of everyday bird rotation.</p></header>"
            '<section><h2>Add an illustration</h2><form method="post" '
            'action="/manage/event-art/upload" '
            'enctype="multipart/form-data">'
            + hidden(csrf)
            + '<div class="fields">'
            + field("title", "Artwork title", "", extra='maxlength="80" required')
            + field("attribution", "Creator or source", "", extra='maxlength="300" required')
            + '</div><label>Image<input type="file" name="image" '
            'accept="image/png,image/jpeg,image/webp" required></label><p class="quiet">'
            "PNG, JPEG or WebP, up to 10 MB. Images are saved as still PNG files. "
            "Review the illustration before approving it for a special day.</p>"
            "<button>Upload for review</button></form></section>"
        )
        entries = service.event_art.entries()
        if not entries:
            body += (
                '<section class="empty-state"><h2>Your special-day collection starts here.</h2>'
                "<p>Upload an illustration, approve it, then choose it on a special day.</p>"
                '<a class="button secondary" href="/manage/events">Plan a special day</a></section>'
            )
        else:
            body += '<div class="card-grid">'
            for art in entries:
                body += (
                    '<article class="card library-card"><img class="artwork-thumb" loading="lazy" '
                    'src="/manage/event-art/'
                    + escape(art["id"])
                    + '/image" alt="'
                    + escape(art["common_name"])
                    + '"><h2>'
                    + escape(art["common_name"])
                    + "</h2><p>"
                    + escape(art["source"])
                    + '</p><p class="pill">'
                    + ("Approved for special days" if art["approved"] else "Awaiting review")
                    + '</p><form method="post" action="/manage/event-art/'
                    + escape(art["id"])
                    + '">'
                    + hidden(csrf)
                    + '<div class="actions"><button class="secondary" name="action" value="'
                    + ("unapprove" if art["approved"] else "approve")
                    + '">'
                    + ("Return to review" if art["approved"] else "Approve for special days")
                    + "</button>"
                    "</div><details><summary>Remove artwork</summary>"
                    "<p>Removal deletes the uploaded artwork. Choose another image on any "
                    'special days using it first.</p><button class="danger" '
                    'name="action" value="remove">'
                    "Permanently remove artwork</button></details></form></article>"
                )
            body += "</div>"
        return page("Special-day art", body, active="event-art")

    @app.get("/manage/event-art/{artwork_id}/image")
    def event_art_image(artwork_id: str, request: Request):
        require(request)
        entry = next((a for a in service.event_art.entries() if a["id"] == artwork_id), None)
        if not entry:
            raise HTTPException(404, "Unknown occasion art")
        return FileResponse(
            service.event_art.path(entry),
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/manage/event-art/upload")
    async def upload_event_art(request: Request):
        session_value = require(request)
        if request.headers.get("origin") not in (None, service.settings.config.public_base_url):
            raise HTTPException(403, "Untrusted form origin")
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith("multipart/form-data;") or len(content_type) > 300:
            raise HTTPException(415, "Use the artwork upload form")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_UPLOAD + 16384:
                raise HTTPException(413, "Upload is too large")
        message = BytesParser(policy=email_policy.default).parsebytes(
            ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode()
            + bytes(raw)
        )
        if not message.is_multipart():
            raise HTTPException(400, "Invalid upload")
        data = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name not in {"csrf", "title", "attribution", "image"} or name in data:
                raise HTTPException(400, "Invalid upload fields")
            payload = part.get_payload(decode=True) or b""
            if name == "image":
                data[name] = payload
            else:
                if len(payload) > 1200:
                    raise HTTPException(400, "Upload field is too long")
                try:
                    data[name] = payload.decode("utf-8")
                except UnicodeDecodeError:
                    raise HTTPException(400, "Use UTF-8 text") from None
        if not hmac.compare_digest(data.get("csrf", ""), session_value["csrf"]):
            raise HTTPException(403, "Invalid form token")
        try:
            with preparation_lock(service.settings.data_dir):
                service.event_art.upload(
                    data.get("image", b""), data.get("title", ""), data.get("attribution", "")
                )
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        except RuntimeError:
            raise HTTPException(409, "Preparation is busy; try again shortly") from None
        return RedirectResponse("/manage/event-art", status_code=303)

    @app.post("/manage/event-art/{artwork_id}")
    async def review_event_art(artwork_id: str, request: Request):
        data = await checked_form(request)
        try:
            with preparation_lock(service.settings.data_dir):
                if data.get("action") in {"remove", "unapprove"}:
                    # Require detaching first so a saved event never silently loses its artwork.
                    if any(
                        any(
                            d.artwork_id == artwork_id
                            for d in FramePolicy.model_validate_json(f["policy"]).special_days
                        )
                        for f in service.store.frames()
                    ):
                        raise ValueError("Choose another artwork on its special days first")
                if data.get("action") == "remove":
                    service.event_art.remove(artwork_id)
                elif data.get("action") in {"approve", "unapprove"}:
                    service.event_art.review(artwork_id, data["action"] == "approve")
                else:
                    raise ValueError("Unknown artwork action")
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        except RuntimeError:
            raise HTTPException(409, "Preparation is busy; try again shortly") from None
        return RedirectResponse("/manage/event-art", status_code=303)

    @app.post("/manage/frames/{identifier}/special-days/import")
    async def import_special_days(identifier: str, request: Request):
        data = await checked_form(request)
        policy = FramePolicy.model_validate_json(
            service.store.frame(identifier)["policy"]
        ).model_dump()
        try:
            policy["special_days"] = import_presets(
                policy["special_days"], data.get("group"), int(data.get("year", ""))
            )
            service.store.set_policy(identifier, FramePolicy.model_validate(policy))
        except ValueError as error:
            raise HTTPException(400, "Invalid collection: " + str(error)) from None
        return redirect(request)

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
                art = next(
                    (a for a in service.event_art.entries() if a["id"] == day.artwork_id), art
                )
                if (
                    not art
                    or not art["approved"]
                    or (
                        not art.get("event_only")
                        and (
                            art.get("depicted_birds", 1) != 1
                            or int(day.date[5:7]) not in art["months"]
                        )
                    )
                ):
                    raise ValueError(
                        "Choose approved occasion art, eligible bird art, or seasonal selection"
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
        return redirect(request)

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
        return redirect(request)

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

    @app.post("/manage/frames/{identifier}/special-days/{day_id}/preview")
    async def queue_special_day_preview(identifier: str, day_id: str, request: Request):
        import asyncio

        await checked_form(request)
        try:
            image = await asyncio.to_thread(service.prepare_special_day, identifier, day_id)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        except RuntimeError:
            raise HTTPException(409, "Preparation is busy; try again shortly") from None
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(f"/manage/images/{image['id']}/review", status_code=303)
        return Response(
            service.cache_path(image["preview_path"]).read_bytes(),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

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
                bird_area=data.get("bird_area", site.get("bird_area", "local")),
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
        return redirect(request)

    @app.post("/manage/public")
    async def public_settings(request: Request):
        data = await checked_form(request)
        identifier = data.get("frame") or None
        if identifier:
            service.store.frame(identifier)
        config = service.settings.config.model_dump()
        config["public_frame_id"] = identifier
        service.save_configuration(config)
        return redirect(request)

    @app.post("/manage/ebird-key")
    async def ebird_key(request: Request):
        data = await checked_form(request)
        key = data.get("key", "").strip()
        if not 16 <= len(key) <= 256 or not all(32 < ord(c) < 127 for c in key):
            raise HTTPException(400, "Invalid key format")
        write_private(secret_directory() / "ebird-api-key", key + "\n")
        return redirect(request)

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
        return redirect(request)

    @app.get("/manage/frames/{identifier}/provision")
    def provision(identifier: str, request: Request, import_file: bool = False):
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
        payload = config
        if import_file:
            # Preserve the Wi-Fi used to recover, including device-only credentials.
            config = {k: v for k, v in config.items() if not k.startswith("wifi_")}
            payload = {"config": config}
        filename = identifier + ("-recovery" if import_file else "") + ".json"
        return Response(
            json.dumps(payload, indent=2),
            media_type="application/json",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @app.post("/manage/frames/{identifier}/prepare")
    async def prepare(identifier: str, request: Request):
        import asyncio

        await checked_form(request)
        try:
            await asyncio.to_thread(service.prepare, identifier, force=True)
        except RuntimeError:
            raise HTTPException(
                409,
                "Artwork preparation is busy. The last good image is retained; try again shortly.",
            ) from None
        except (ValueError, OSError):
            raise HTTPException(
                503,
                "Artwork could not be prepared. The last good image is retained; try "
                "again shortly.",
            ) from None
        return redirect(request)
