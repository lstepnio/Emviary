"""Small owner UI. Display and content decisions stay in the backend."""

import hashlib
import hmac
import html
import json
import os
import re
import secrets
import time
from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta
from email import policy as email_policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import ValidationError
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import config_payload
from .battery import battery_summary, install_battery_routes
from .diagnostics import management_alerts_section, saved_networks_section
from .event_art import MAX_UPLOAD, import_presets, next_special_day_date, special_day_conflicts
from .service import preparation_lock
from .settings import FramePolicy, SpecialDay, cron_for
from .store import RevisionConflict, token_hash
from .trusted_network import network_session, source_public_ip
from .ui import local_time

COOKIE = "emviary_owner"
PAGE_CONTEXT = ContextVar("owner_page_context", default=None)


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
        "Artwork rotation": "artwork",
        "Occasion artwork": "event-art",
        "Special-day artwork": "event-art",
        "Battery history": "battery",
        "Battery and charging": "battery",
        "Battery and device health": "battery",
    }
    kwargs.setdefault("active", keys.get(title, "settings"))
    context = PAGE_CONTEXT.get()
    if context and kwargs["active"] != "login":
        kwargs.setdefault("frame", context["frame"])

        def versioned_form(match):
            opening, identifier = match.group(0), html.unescape(match.group(1))
            revision = context["revisions"].get(identifier)
            return opening + (
                f'<input type="hidden" name="frame_revision" value="{revision}">'
                if revision is not None
                else ""
            )

        body = re.sub(r'<form\b[^>]*action="/manage/frames/([^/"?]+)/[^>]*>', versioned_form, body)
        body = re.sub(
            r'<form\b[^>]*action="/manage/(?:sites/[^/"?]+|public)"[^>]*>',
            lambda m: (
                m.group(0)
                + '<input type="hidden" name="configuration_revision" value="'
                + context["configuration_revision"]
                + '">'
            ),
            body,
        )
    return render_page(title, body, **kwargs)


def hidden(csrf):
    return '<input type="hidden" name="csrf" value="' + escape(csrf) + '">'


def expected_revision(data):
    """Legacy API clients may omit a revision; rendered owner forms supply one."""
    raw = data.get("frame_revision")
    if raw is None:
        return None
    try:
        revision = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(
            400, "This form has an invalid version. Reload and try again."
        ) from None
    if not 0 <= revision <= 2**63 - 1:
        raise HTTPException(400, "This form has an invalid version. Reload and try again.")
    return revision


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

    @app.middleware("http")
    async def owner_context(request, call_next):
        if not request.url.path.startswith("/manage"):
            return await call_next(request)
        frames = service.store.frames()
        chosen = request.query_params.get("frame")
        chosen = chosen if any(f["id"] == chosen for f in frames) else None
        if not chosen and len(frames) == 1:
            chosen = frames[0]["id"]
        token = PAGE_CONTEXT.set(
            {
                "frame": chosen,
                "revisions": {f["id"]: f["config_revision"] for f in frames},
                "configuration_revision": service.settings_revision(),
            }
        )
        try:
            return await call_next(request)
        finally:
            PAGE_CONTEXT.reset(token)

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
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": exc.detail}
            fields = detail.get("fields", [])
            if not isinstance(fields, list):
                fields = []
            response = page(
                "Management request unavailable",
                '<p class="notice error" data-request-error role="alert" data-error-fields="'
                + escape(json.dumps([str(name)[:80] for name in fields[:20]]))
                + '">'
                + escape(detail.get("message", "This change could not be saved."))
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

    @app.exception_handler(RevisionConflict)
    async def conflicting_edit(request: Request, exc: RevisionConflict):
        return await management_error(
            request,
            HTTPException(
                409,
                "Saved settings changed in another tab or request. Your entries are still here. "
                "Open the current settings in another tab to compare, then reload before saving.",
            ),
        )

    def session(request):
        with service.store.connect() as db:
            row = db.execute(
                "SELECT * FROM owner_sessions WHERE token_hash=? AND expires_at>?",
                (token_hash(request.cookies.get(COOKIE, "")), datetime.now(UTC).isoformat()),
            ).fetchone()
        return dict(row) if row else network_session(request, service)

    def require(request):
        value = session(request)
        if not value:
            raise HTTPException(401, "Your session has expired. Sign in to continue.")
        return value

    @app.get("/manage/session")
    def current_session(request: Request):
        # A refreshed CSRF token lets an open form recover after signing in in another tab.
        # Authentication remains mandatory and tokens never enter URLs or browser storage.
        value = require(request)
        return JSONResponse({"csrf": value["csrf"]}, headers={"Cache-Control": "no-store"})

    install_battery_routes(app, service, require, escape, page)
    from .usb_recovery import install_routes as install_usb_routes

    install_usb_routes(app, require)

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
        peer = source_public_ip(request) or request.client.host
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
        if request.query_params.get("queued") and view == "appearance":
            body += (
                '<p class="notice success" role="status">Settings saved and '
                "preview queued for the next online artwork fetch. Delivery and "
                "physical-panel refresh are not yet confirmed.</p>"
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
        if len(frames) > 1:
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
            [f for f in frames if not chosen or f["id"] == chosen]
            if view in ("manage", "recovery")
            else [f for f in frames if f["id"] == (chosen or frames[0]["id"])]
            if frames
            else []
        )
        statuses = {row["id"]: row for row in service.status()}
        for frame in selected_frames:
            policy = FramePolicy.model_validate_json(frame["policy"]).model_dump()
            status = statuses[frame["id"]]
            body += management_alerts_section(service, frame, escape)
            identifier = escape(frame["id"])
            site_timezone = service.settings.config.site(frame["site_id"]).timezone
            timezone_label = site_timezone.rsplit("/", 1)[-1].replace("_", " ")
            if view == "manage":
                delivered = service.delivered_image(frame)
                ready = service.store.slot_image(frame["id"], "navigation")
                daily = service.store.slot_image(frame["id"], "scheduled")
                battery = battery_summary(service, frame["id"])
                body += (
                    '<section class="card"><div class="section-heading"><h2>'
                    + identifier
                    + '</h2></div><div class="frame-status">'
                )
                for label, value in (
                    ("Saved daily wake", policy["wake_local_time"] + " · " + timezone_label),
                    (
                        "Battery",
                        str(status["battery"]) + "%"
                        if status["battery"] is not None
                        else "Not reported",
                    ),
                    (
                        "Last contact",
                        datetime.fromisoformat(status["last_contact"])
                        .astimezone(ZoneInfo(site_timezone))
                        .strftime("%b %d, %I:%M %p")
                        if status["last_contact"]
                        else "Waiting for first wake",
                    ),
                ):
                    body += (
                        "<span>" + escape(label) + ": <strong>" + escape(value) + "</strong></span>"
                    )
                body += (
                    '</div><div class="current-next refresh-slots">'
                    '<div class="delivered-slot"><h3>Last delivered</h3>'
                )
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

                def readiness(image):
                    if not image:
                        return "Waiting for server preparation."
                    plan = json.loads(image["manifest"])
                    forecast = plan["inputs"].get("open_meteo", {})
                    stamp = forecast.get("fetched_at")
                    state = (
                        "Ready"
                        if service.image_usable(image, frame)
                        else "Waiting for fresh preparation"
                    )
                    detail = (
                        "Forecast updated "
                        + datetime.fromisoformat(stamp)
                        .astimezone(
                            ZoneInfo(service.settings.config.site(frame["site_id"]).timezone)
                        )
                        .strftime("%b %d, %I:%M %p")
                        if stamp
                        else "Weather omitted"
                        if policy["weather_cues"]
                        else "Weather off"
                    )
                    return state + " · " + image["local_date"] + " · " + detail

                body += (
                    '<p class="quiet">The website follows artwork delivery. Device health '
                    "shows the frame’s reported refresh result.</p>"
                )
                body += '</div><div class="prepared-slot"><h3>Daily refresh</h3>'
                body += (
                    '<img class="preview" alt="Prepared daily artwork" src="/manage/frames/'
                    + identifier
                    + '/prepared/scheduled">'
                    if daily
                    else '<p class="empty-state">Preparing near the next daily wake.</p>'
                )
                body += '<p class="quiet">' + escape(readiness(daily)) + "</p>"
                body += '</div><div class="prepared-slot"><h3>Next button</h3>'
                body += (
                    '<img class="preview" alt="Prepared next artwork" src="/manage/frames/'
                    + identifier
                    + '/preview">'
                    if ready
                    else '<p class="empty-state">No picture prepared yet.</p>'
                )
                body += (
                    '<p class="quiet">' + escape(readiness(ready)) + "</p>"
                    '</div></div><p class="quiet">Daily refreshes get a separately prepared '
                    "forecast. The next button uses a ready image; older images keep their "
                    "original weather when browsing history. If preparation is delayed, the "
                    "frame keeps its current picture. This view follows delivery and cannot "
                    "confirm the physical panel.</p>"
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
                    + '/settings" data-appearance-preview>'
                    + hidden(csrf)
                    + '<p class="quiet">Preview unsaved settings first. Saving changes '
                    "the cloud configuration; prepared artwork can still use the "
                    "previous settings. Save and queue a preview to make this exact "
                    "image available at the next online fetch.</p>"
                    + '<input type="hidden" name="preview_token" value="">'
                    + '<div class="grid">'
                )
                body += field(
                    "wake",
                    "Daily wake (" + timezone_label + " time)",
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
                    "Checked each time the frame wakes online. Automatic accepts eligible "
                    "published "
                    "Emviary firmware within the selected channel and rollout delay. "
                    "Manual requires a "
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
                body += '<label>Release channel<br><select name="firmware_channel">'
                for value, label in (
                    ("all", "All releases, including previews"),
                    ("stable", "Stable releases only"),
                ):
                    selected = "selected" if policy["firmware_channel"] == value else ""
                    body += f'<option value="{value}" {selected}>{label}</option>'
                body += "</select></label>"
                body += field(
                    "firmware_rollout_days",
                    "Wait days after publication (0 to 30)",
                    str(policy["firmware_rollout_days"]),
                    kind="number",
                )
                body += field(
                    "firmware_blocked_versions",
                    "Blocked releases (comma separated)",
                    ", ".join(policy["firmware_blocked_versions"]),
                )
                body += field(
                    "firmware_pinned_version",
                    "Optional release version (for example v0.4.0)",
                    policy["firmware_pinned_version"] or "",
                )
                body += (
                    '<p class="quiet">A chosen version limits updates to that release. '
                    "Older versions are never installed automatically.</p>"
                )
                body += checkbox(
                    "firmware_debug_logging",
                    "Enable device debug logging",
                    policy.get("firmware_debug_logging", False),
                )
                body += (
                    '<p class="quiet">Off by default. Enable only while troubleshooting, '
                    "then turn it off again to reduce device activity and flash writes. "
                    "Battery and refresh status remain available while debug logging is off. "
                    "Applies on the next online artwork fetch.</p></details>"
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
                body += field(
                    "weather_max_age",
                    "Forecast freshness (minutes)",
                    str(policy["weather_max_age_minutes"]),
                    "number",
                    'min="15" max="1440"',
                )
                body += '<p class="quiet">Default: 120 minutes. Forecasts refresh on the '
                body += "server while your frame sleeps.</p>"
                body += "</div>"
                body += checkbox("season", "Seasonal details", policy["seasonal_themes"])
                body += "</fieldset>"
                body += (
                    '<section data-appearance-preview-result tabindex="-1" '
                    "hidden><h3>Unsaved preview</h3>"
                    '<img class="preview" data-appearance-preview-image alt="Draft '
                    'artwork with your unsaved display settings" width="800" '
                    'height="480">'
                    '<p class="quiet">This preview has not been saved or delivered. '
                    "Panel colors may differ. Preview is available for up to 30 minutes; "
                    "a server restart or newer previews may expire it sooner.</p></section>"
                    '<div class="sticky-actions"><button type="submit" name="action" '
                    'value="preview" '
                    'data-preview-appearance formaction="/manage/frames/'
                    + identifier
                    + '/appearance-preview">Preview changes</button>'
                    '<button type="submit" name="action" value="queue" '
                    "data-queue-appearance disabled>Save and queue preview</button>"
                    '<button class="secondary" type="submit">Save settings '
                    "only</button></div></form>"
                )
                body += "</section>"
            if view == "settings":
                body += (
                    '<section class="card"><h2>Management access</h2>'
                    '<form method="post" action="/manage/frames/'
                    + identifier
                    + '/management-access">'
                    + hidden(csrf)
                    + checkbox(
                        "management_trusted_wan",
                        "Allow password-free management from this frame’s internet connection",
                        policy.get("management_trusted_wan", False),
                    )
                    + '<p class="quiet">This trusts everyone sharing the public IP, including '
                    "guests. Uses a frame connection authenticated within the last 48 hours. "
                    "Access is checked on every request; another network still needs the "
                    "owner password. If the frame has not contacted this service since this "
                    "feature was enabled, wait for its next wake or refresh it.</p>"
                    "<button>Save management access</button></form></section>"
                )
                body += (
                    '<section class="card" id="wifi-networks" aria-labelledby="wifi-heading">'
                    '<h2 id="wifi-heading">Saved Wi-Fi networks</h2><p class="quiet">'
                    "Stage up to five 2.4 GHz networks before gifting. Changes reach the frame "
                    "on its next online artwork fetch. These networks take priority and are added "
                    "to existing device networks, preserving its staging connection. The frame "
                    "holds five networks in total. Removal applies only to networks saved here. "
                    "Passwords are stored privately and never shown.</p>"
                )
                body += saved_networks_section(service.store, frame["id"], policy, escape)
                body += (
                    '<h3>Cloud-managed networks</h3><p class="quiet">These profiles are sent '
                    "on each artwork fetch. Compare with the reported list above to confirm "
                    "they reached the frame. Device-only profiles can be edited on "
                    '<a href="http://emviary.local">emviary.local</a> while awake.</p>'
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
                    "on the matching local date. Higher priority wins; ties use saved order. "
                    "Annual February 29 entries appear only in leap years.</p>"
                )
                body += (
                    '<p class="notice">Add or open a special day below, choose its date '
                    "and greeting, then save it with Enabled turned on. Seasonal bird art "
                    "is selected automatically unless you choose featured artwork. "
                    "Upload your own illustration in the Artwork collection below, "
                    "then choose it for a day. Uploaded art is ready to use immediately.</p>"
                    + event_art_panel(request, csrf, frame["id"])
                    + "<details><summary>Add holiday or season collections</summary>"
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
                    return next_special_day_date(event, today)

                conflicts = special_day_conflicts(policy["special_days"], today)
                if conflicts:
                    body += '<div class="notice"><strong>Overlapping special days</strong>'
                    body += "<p>Higher priority wins. Equal priorities use saved list order. "
                    body += "Upcoming overlaps over the next five years:</p><ul>"
                    for when, matches in conflicts:
                        body += "<li>" + escape(when.strftime("%b %-d, %Y")) + ": "
                        body += escape(matches[0]["label"]) + " will display instead of "
                        body += escape(", ".join(e["label"] for e in matches[1:])) + ".</li>"
                    body += "</ul></div>"

                events = sorted(
                    policy["special_days"],
                    key=lambda e: (not e["enabled"], occasion_date(e) < today, occasion_date(e)),
                )
                enabled_count = sum(event["enabled"] for event in events)
                body += '<p class="quiet">' + str(len(events)) + " special days: "
                body += str(enabled_count) + " enabled, " + str(len(events) - enabled_count)
                body += " disabled. Open a heading to edit that day.</p>"
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
                        + (" · Priority " + str(day.get("priority", 0)) if event else "")
                        + "</span></summary>"
                    )
                    body += (
                        "<h3>"
                        + escape(day["label"] if event else "Add a special day")
                        + '</h3><form method="post" data-event-editor action="/manage/frames/'
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
                            + art.get("style", "Illustration").replace("-", " ").title()
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
                        body += (
                            '<option value="'
                            + escape(art["id"])
                            + '" '
                            + ("selected" if day["artwork_id"] == art["id"] else "")
                            + ">"
                            + escape("Special-day art / " + art["common_name"])
                            + "</option>"
                        )
                    body += "</select></label></div>"
                    rule = day.get("recurrence") or {}
                    body += '<label>Date rule<br><select name="date_rule">'
                    for value, label in (
                        ("fixed", "Use the date above"),
                        ("nth_weekday", "Weekday each year"),
                    ):
                        body += '<option value="' + value + '"'
                        body += " selected" if value == rule.get("kind", "fixed") else ""
                        body += ">" + label + "</option>"
                    body += "</select></label><details><summary>Weekday date and priority</summary>"
                    body += "<p>For a weekday each year, choose the month, weekday and occurrence. "
                    body += "The date above stays saved as the original date.</p>"
                    for name, label, choices, selected in (
                        (
                            "rule_month",
                            "Month",
                            [(i, date(2000, i, 1).strftime("%B")) for i in range(1, 13)],
                            rule.get("month", 1),
                        ),
                        (
                            "rule_weekday",
                            "Weekday",
                            list(
                                enumerate(
                                    (
                                        "Monday",
                                        "Tuesday",
                                        "Wednesday",
                                        "Thursday",
                                        "Friday",
                                        "Saturday",
                                        "Sunday",
                                    )
                                )
                            ),
                            rule.get("weekday", 0),
                        ),
                        (
                            "rule_ordinal",
                            "Occurrence",
                            [
                                (1, "First"),
                                (2, "Second"),
                                (3, "Third"),
                                (4, "Fourth"),
                                (-1, "Last"),
                            ],
                            rule.get("ordinal", 1),
                        ),
                    ):
                        body += "<label>" + label + '<br><select name="' + name + '">'
                        for value, text in choices:
                            body += '<option value="' + str(value) + '"'
                            body += " selected" if value == selected else ""
                            body += ">" + text + "</option>"
                        body += "</select></label>"
                    body += field(
                        "priority",
                        "Priority (higher wins)",
                        day.get("priority", 0),
                        "number",
                        'min="0" max="100"',
                    )
                    body += "</details>"
                    body += checkbox("annual", "Repeat the fixed date every year", day["annual"])
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
                            + '<button class="secondary">Queue saved day on frame</button>'
                            + '<p class="muted">Uses the saved event and today’s weather. '
                            "Save changes above first. Available on the next "
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
                            + "<details><summary>Remove this day</summary><p>"
                            "This removes the event and its greeting from the calendar. "
                            "Its artwork stays in the library. To pause it, turn off Enabled "
                            'and save instead.</p><button class="danger">Remove this day</button>'
                            "</details></form>"
                        )
                    body += "</details>"
                body += "</section>"
            if view == "recovery":
                from .usb_recovery import panel as usb_recovery_panel

                body += usb_recovery_panel(frame["id"])
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
            body += '<section class="card"><h2>Backup health</h2>'
            verified = []
            for candidate in service.settings.backup_dir.iterdir():
                marker = candidate / "COMPLETE"
                if candidate.is_dir() and marker.is_file():
                    try:
                        result = json.loads(marker.read_text())
                        if result.get("restore_rehearsal") == "passed":
                            verified.append(result["created_at"])
                    except (ValueError, KeyError, OSError):
                        pass
            body += (
                "<p>Latest verified backup: "
                + escape(local_time(max(verified)))
                + ". Every new backup passes an isolated offline restore rehearsal.</p>"
                if verified
                else '<p class="notice">No backup with a verified restore rehearsal yet.</p>'
            )
            try:
                independent = json.loads(
                    (service.settings.data_dir / "offhost-backup.json").read_text()
                )
                body += (
                    "<p>Independent copy verified: "
                    + escape(local_time(independent["created_at"]))
                    + ".</p>"
                )
            except (OSError, ValueError, KeyError):
                body += '<p class="notice">No independent backup copy has been confirmed.</p>'
            body += (
                '<p class="quiet">Older backups remain available. '
                "They predate automatic integrity manifests.</p></section>"
            )
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
                "Hold LEFT for five seconds for a local diagnostic snapshot on v0.8.3 or later. "
                "Green returns to artwork. These buttons do not factory-reset "
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
                'use <a href="#usb-recovery">Restore firmware over USB</a> above. '
                "Replacing firmware with stock "
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
            if auth.get("network_access"):
                body += (
                    "<section><h2>Owner password</h2><p>Network access is checked on each request. "
                    "Changing the owner password requires a password sign-in.</p>"
                    '<a class="button secondary" href="/manage/login?return=%2Fmanage%2Fsettings">'
                    "Sign in with owner password</a></section>"
                )
            else:
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
        return page(
            titles[view],
            body,
            active="overview" if view == "manage" else view,
            frame=chosen or (selected_frames[0]["id"] if len(selected_frames) == 1 else None),
        )

    @app.get("/manage/images")
    def retired_image_gallery(request: Request, frame: str = ""):
        require(request)
        if frame:
            service.store.frame(frame)
        return RedirectResponse(
            "/manage" + ("?" + urlencode({"frame": frame}) if frame else ""), status_code=303
        )

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
        special_day = json.loads(image["manifest"]).get("special_day") or {}
        event_anchor = "#event-" + special_day["id"] if special_day.get("id") else ""
        if delivered and delivered["id"] == image_id:
            message = (
                "This artwork was last delivered to the frame. Another image may be ready next."
            )
        elif frame["active_image_id"] == image_id:
            message = (
                "Artwork prepared and queued. It is available on the next online wake "
                "or next-image button press."
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
            '<div class="actions"><a class="button" href="/manage?frame='
            + escape(image["frame_id"])
            + '">View frame '
            "&amp; next artwork</a>"
            '<a class="button secondary" href="/manage/events?frame='
            + escape(image["frame_id"])
            + escape(event_anchor)
            + '">Back to special days</a></div></section>'
        )
        return page("Special-day preview", body, active="events")

    @app.get("/manage/images/{image_id}/preview")
    def queued_image_preview(image_id: int, request: Request):
        require(request)
        with service.store.connect() as db:
            record = db.execute(
                "SELECT * FROM images WHERE id=? AND hidden=0", (image_id,)
            ).fetchone()
        if not record or not service.cache_path(record["preview_path"]).is_file():
            raise HTTPException(404, "Image unavailable")
        return FileResponse(
            service.cache_path(record["preview_path"]),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/manage/artwork")
    def artwork_management(
        request: Request,
        q: str = "",
        status: str = "",
        sort: str = "name",
        p: int = 1,
        style: str = "",
        pose: str = "",
        season: str = "",
    ):
        from urllib.parse import urlencode

        auth = require(request)
        excluded = service.store.excluded_artworks()
        counts = service.store.bird_counts()
        catalog = service.settings.source_catalog["artworks"]
        styles = sorted({a.get("style", "") for a in catalog} - {""})
        poses = sorted({a.get("pose", "") for a in catalog} - {""})
        style = style if style in styles else ""
        pose = pose if pose in poses + ["missing"] else ""
        seasons = {
            "winter": {12, 1, 2},
            "spring": {3, 4, 5},
            "summer": {6, 7, 8},
            "autumn": {9, 10, 11},
        }
        season = season if season in seasons else ""
        q = q.strip()[:200]
        status = status if status in {"rotation", "excluded", "reference", "deleted"} else ""
        sort = sort if sort in {"name", "most", "least"} else "name"
        works = [
            a
            for a in (
                service.deleted_artwork_entries()
                if status == "deleted"
                else service.settings.artworks
            )
            if q.casefold()
            in " ".join(
                str(a.get(k, "")) for k in ("common_name", "scientific_name", "credit", "id")
            ).casefold()
            and (not style or a.get("style") == style)
            and (not pose or (not a.get("pose") if pose == "missing" else a.get("pose") == pose))
            and (not season or bool(set(a.get("months", [])) & seasons[season]))
            and (
                not status
                or status == "deleted"
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
        frame_context = request.query_params.get("frame", "")
        if frame_context:
            service.store.frame(frame_context)
        context = {
            "frame": frame_context,
            "q": q,
            "status": status,
            "sort": sort,
            "p": p,
            "style": style,
            "pose": pose,
            "season": season,
        }
        return_url = "/manage/artwork?" + urlencode({k: v for k, v in context.items() if v != ""})
        if str(p) != request.query_params.get("p", "1"):
            return RedirectResponse(return_url, status_code=303)
        body = (
            '<header class="page-header"><h1>Artwork library</h1>'
            '<p class="page-description">Choose which illustrations can appear in future '
            "compositions. Exclusions leave the artwork already on the frame "
            "unchanged.</p></header>"
            f'<section id="artwork-library" aria-label="Artwork choices" '
            f'data-first-page="{p}" data-last-page="{p}" data-total-pages="{pages}">'
            ""
            '<p data-library-feedback role="status" aria-live="polite"></p>'
            '<form class="toolbar" method="get" action="/manage/artwork"><label>Search'
            '<input type="search" name="q" value="'
            + escape(q)
            + '" placeholder="Find a bird"></label>'
        )
        for name, label, options, selected in (
            (
                "status",
                "Availability",
                [
                    ("", "All artwork"),
                    ("rotation", "In rotation"),
                    ("excluded", "Excluded"),
                    ("reference", "Reference artwork"),
                    ("deleted", "Deleted artwork"),
                ],
                status,
            ),
            (
                "sort",
                "Sort",
                [("name", "Name A to Z"), ("most", "Most rendered"), ("least", "Least rendered")],
                sort,
            ),
            ("style", "Style", [("", "All styles")] + [(v, v) for v in styles], style),
            (
                "pose",
                "Pose",
                [("", "All poses")] + [(v, v) for v in poses] + [("missing", "Pose not recorded")],
                pose,
            ),
            (
                "season",
                "Season eligibility",
                [("", "All seasons")] + [(v, v.title()) for v in seasons],
                season,
            ),
        ):
            if name == "style":
                body += (
                    '<details class="collection-filter-options"'
                    + (" open" if any((style, pose, season)) else "")
                    + '><summary>More filters</summary><div class="fields">'
                )
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
            if name == "season":
                body += "</div></details>"
        if frame_context:
            body += '<input type="hidden" name="frame" value="' + escape(frame_context) + '">'
        body += (
            '<button>Apply filters</button><a class="button secondary" '
            'href="/manage/artwork'
            + ("?" + escape(urlencode({"frame": frame_context})) if frame_context else "")
            + '">Reset</a></form>'
            '<p class="quiet">'
            + str(len(works))
            + " artworks match · Shared library. Counts cover all variants of each bird.</p>"
        )
        unused = sum(not a["approved"] or a["id"] in excluded for a in service.settings.artworks)
        cleanup = ""
        if unused:
            cleanup += (
                "<details><summary>Manage all artwork outside rotation</summary>"
                "<p>This affects every excluded or reference artwork in the library, "
                "including artwork outside these filters and this page.</p>"
                '<form method="post" action="/manage/artwork/bulk-delete">'
                + hidden(auth["csrf"])
                + '<input type="hidden" name="return" value="'
                + escape(return_url)
                + '">'
                + '<button class="danger">Delete all '
                + str(unused)
                + " artworks outside rotation</button></form></details>"
            )
        if status != "deleted":
            body += (
                '<form id="artwork-bulk" method="post" data-library-action '
                'data-library-message="Selected artworks updated." '
                'action="/manage/artwork/bulk">'
                + hidden(auth["csrf"])
                + '<input type="hidden" name="return" value="'
                + escape(return_url)
                + '">'
                + '<p class="quiet">Select to edit in bulk.</p>'
                + '<button type="button" class="secondary" data-select-page '
                "hidden>Select all on this page</button> "
                '<span data-selection-count role="status" aria-live="polite">'
                '0 artworks selected</span><div class="actions" data-selection-actions>'
                + '<button name="action" value="include" class="secondary">'
                "Include selected in rotation</button> "
                + '<button name="action" value="exclude" class="secondary">'
                "Exclude selected from rotation</button> "
                + '<button name="action" value="delete" class="danger">'
                "Delete selected artworks</button></div></form>"
            )
        body += '<div class="card-grid artwork-grid">'
        for art in works[(p - 1) * 24 : p * 24]:
            art_id, name = escape(art["id"]), escape(art["common_name"])
            excluded_art = art["id"] in excluded
            label = (
                "Deleted"
                if status == "deleted"
                else "Excluded"
                if excluded_art
                else "In rotation"
                if art["approved"]
                else "Reference"
            )
            thumbnail = (
                "/manage/artwork/" + art_id + "/thumbnail"
                if status == "deleted"
                else "/art-thumbnail/" + art_id
            )
            body += (
                '<article class="card library-card artwork-card" data-artwork-id="'
                + art_id
                + '"><div class="artwork-media"><a href="/manage/artwork/'
                + art_id
                + '/image" target="_blank" rel="noopener" aria-label="Open full '
                + name
                + ' illustration"><img class="artwork-thumb" loading="lazy" src="'
                + thumbnail
                + '" alt="'
                + name
                + '"></a></div>'
                '<div class="artwork-heading"><h2>'
                + name
                + '</h2><span class="pill'
                + (" warning" if excluded_art else "")
                + '">'
                + label
                + "</span></div>"
                '<p class="artwork-meta">'
                + str(counts.get(art["scientific_name"], 0))
                + " compositions</p>"
            )
            body += '<div class="artwork-actions">'
            if status != "deleted":
                body += (
                    '<label class="artwork-select"><input type="checkbox" form="artwork-bulk" '
                    'name="selected_'
                    + art_id
                    + '" value="1" aria-label="Select '
                    + name
                    + ' artwork">Select</label>'
                )
            if art["approved"] and status != "deleted":
                body += (
                    '<form method="post" data-library-action action="/manage/artwork/'
                    + art_id
                    + '">'
                    + hidden(auth["csrf"])
                    + '<input type="hidden" name="return" value="'
                    + escape(return_url)
                    + '">'
                    '<input type="hidden" name="exclude" value="'
                    + ("0" if excluded_art else "1")
                    + '"><button class="secondary compact-action">'
                    + ("Restore to rotation" if excluded_art else "Exclude from rotation")
                    + "</button></form>"
                )
            if status == "deleted":
                body += (
                    '<form method="post" data-library-action '
                    'data-library-message=" restored to the library." '
                    'action="/manage/artwork/'
                    + art_id
                    + '/restore">'
                    + hidden(auth["csrf"])
                    + '<input type="hidden" name="return" value="'
                    + escape(return_url)
                    + '">'
                    '<button class="secondary compact-action">Restore artwork</button></form>'
                )
            body += "</div>"
            if status != "deleted":
                body += (
                    '<details class="artwork-remove-options"><summary>Remove artwork</summary>'
                    '<form class="artwork-remove" method="post" data-library-action '
                    'data-library-message=" deleted from the library." '
                    'action="/manage/artwork/'
                    + art_id
                    + '/delete">'
                    + hidden(auth["csrf"])
                    + '<input type="hidden" name="return" value="'
                    + escape(return_url)
                    + '">'
                    '<p class="quiet">Removed artwork stays available in Deleted artwork.</p>'
                    '<button class="danger compact-action">Delete artwork</button></form></details>'
                )
            body += "</article>"
        body += "</div>"
        if not works:
            body += (
                '<section class="empty-state"><h2>No artwork matches</h2>'
                "<p>Try another search or reset your filters.</p></section>"
            )
        if pages > 1:
            body += '<nav class="toolbar" aria-label="Artwork pages" data-artwork-pagination>'
            for number, label in ((p - 1, "Previous"), (p + 1, "Next")):
                if 1 <= number <= pages:
                    body += (
                        '<a class="button secondary" '
                        + ("data-artwork-next " if label == "Next" else "")
                        + 'href="/manage/artwork?'
                        + escape(
                            urlencode(
                                {k: v for k, v in {**context, "p": number}.items() if v != ""}
                            )
                        )
                        + '">'
                        + label
                        + "</a>"
                    )
            body += '<span class="quiet">Page ' + str(p) + " of " + str(pages) + "</span></nav>"
        body += (
            '<details class="library-help"><summary>Collection help & cleanup</summary>'
            "<p>Delete moves artwork to Deleted artwork, where it can be restored. "
            "The current frame image and rendered history are preserved.</p>"
            "<p>Season filters use catalog month eligibility.</p>" + cleanup + "</details>"
            ""
        )
        body += "</section>"
        return page("Artwork library", body, active="artwork")

    def artwork_return(data):
        parts = urlsplit(safe_return(data.get("return")))
        target = "/manage/artwork"
        if parts.path == target:
            values = parse_qs(parts.query)
            params = {
                k: values[k][-1]
                for k in ("q", "status", "sort", "p", "style", "pose", "season", "frame")
                if k in values
            }
            if "p" in params:
                try:
                    params["p"] = str(max(1, int(params["p"])))
                except ValueError:
                    params["p"] = "1"
            target += "?" + urlencode(params) if params else ""
        return target

    def set_rotation(identifiers, exclude):
        with preparation_lock(service.settings.data_dir):
            active = {a["id"]: a for a in service.settings.artworks}
            if not identifiers <= active.keys():
                raise HTTPException(404, "Unknown artwork")
            if not exclude and any(not active[key]["approved"] for key in identifiers):
                raise HTTPException(
                    409, "Reference artwork must be approved in the catalog before rotation"
                )
            excluded = service.store.excluded_artworks()
            if exclude and not any(
                a["approved"] and a["id"] not in excluded | identifiers
                for a in service.settings.artworks
            ):
                raise HTTPException(409, "Keep at least one artwork in rotation")
            with service.store.connect() as db:
                db.executemany(
                    "INSERT OR IGNORE INTO excluded_artworks VALUES(?)"
                    if exclude
                    else "DELETE FROM excluded_artworks WHERE id=?",
                    [(key,) for key in identifiers],
                )
            if exclude:
                for frame in service.store.frames():
                    image = service.store.active_image(frame)
                    if image:
                        plan = json.loads(image["manifest"])
                        if any(
                            a["id"] in identifiers for a in plan.get("artworks", [plan["artwork"]])
                        ):
                            service.store.request_refill(frame["id"], image["id"])

    @app.post("/manage/artwork/bulk")
    async def bulk_artwork_action(request: Request):
        data = await checked_form(request)
        identifiers = {
            key.removeprefix("selected_")
            for key, value in data.items()
            if key.startswith("selected_") and value == "1"
        }
        if not identifiers or len(identifiers) > 500:
            raise HTTPException(400, "Select between 1 and 500 artworks")
        action = data.get("action")
        if action == "delete":
            try:
                service.delete_artworks(identifiers)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None
        elif action in {"include", "exclude"}:
            set_rotation(identifiers, action == "exclude")
        else:
            raise HTTPException(400, "Unknown artwork action")
        return RedirectResponse(
            artwork_return(data), status_code=303, background=BackgroundTask(service.refill_pending)
        )

    @app.post("/manage/artwork/bulk-delete")
    async def delete_unused_artworks(request: Request):
        data = await checked_form(request)
        excluded = service.store.excluded_artworks()
        identifiers = [
            a["id"] for a in service.settings.artworks if not a["approved"] or a["id"] in excluded
        ]
        try:
            service.delete_artworks(identifiers)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return RedirectResponse(
            artwork_return(data), status_code=303, background=BackgroundTask(service.refill_pending)
        )

    @app.post("/manage/artwork/{artwork_id}/delete")
    async def delete_library_artwork(artwork_id: str, request: Request):
        data = await checked_form(request)
        try:
            service.delete_artworks([artwork_id])
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return RedirectResponse(
            artwork_return(data), status_code=303, background=BackgroundTask(service.refill_pending)
        )

    @app.post("/manage/artwork/{artwork_id}/restore")
    async def restore_library_artwork(artwork_id: str, request: Request):
        data = await checked_form(request)
        try:
            service.restore_artwork(artwork_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None
        return RedirectResponse(artwork_return(data), status_code=303)

    @app.get("/manage/artwork/{artwork_id}/thumbnail")
    def deleted_library_thumbnail(artwork_id: str, request: Request):
        require(request)
        from .thumbnails import thumbnail_file

        artwork = next(
            (a for a in service.deleted_artwork_entries() if a["id"] == artwork_id), None
        )
        if artwork is None:
            raise HTTPException(404, "Deleted artwork unavailable")
        path = service.settings.art_dir / artwork["asset"]
        stat = path.stat()
        target, _ = thumbnail_file(
            str(path),
            stat.st_mtime_ns,
            stat.st_size,
            service.settings.data_dir / "cache" / "thumbnails",
        )
        return FileResponse(target, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/manage/artwork/{artwork_id}/image")
    def owner_artwork_image(artwork_id: str, request: Request):
        require(request)
        artwork = next(
            (a for a in service.settings.source_catalog["artworks"] if a["id"] == artwork_id), None
        )
        if not artwork:
            raise HTTPException(404, "Artwork unavailable")
        path = (service.settings.art_dir / artwork["asset"]).resolve()
        if not path.is_relative_to(service.settings.art_dir) or not path.is_file():
            raise HTTPException(404, "Artwork unavailable")
        return FileResponse(path, headers={"Cache-Control": "private, no-cache"})

    @app.post("/manage/artwork/{artwork_id}")
    async def artwork_rotation(artwork_id: str, request: Request):
        data = await checked_form(request)
        set_rotation({artwork_id}, data.get("exclude") == "1")
        return RedirectResponse(
            artwork_return(data), status_code=303, background=BackgroundTask(service.refill_pending)
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

    @app.get("/manage/frames/{identifier}/prepared/{purpose}")
    def prepared_preview(identifier: str, purpose: str, request: Request):
        require(request)
        service.store.frame(identifier)
        if purpose not in {"scheduled", "navigation"}:
            raise HTTPException(404, "Unknown prepared image")
        record = service.store.slot_image(identifier, purpose)
        if not record:
            raise HTTPException(404, "No prepared preview")
        return FileResponse(
            service.cache_path(record["preview_path"]),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    def appearance_policy(identifier, data):
        policy = FramePolicy.model_validate_json(
            service.store.frame(identifier)["policy"]
        ).model_dump()
        try:
            policy.update(
                wake_local_time=data["wake"],
                firmware_rotate_cron=cron_for(data["wake"]),
                max_birds=int(data["max_birds"]),
                firmware_updates=data.get("firmware_updates", policy["firmware_updates"]),
                firmware_debug_logging=data.get("firmware_debug_logging") == "on",
                firmware_channel=data.get("firmware_channel", policy["firmware_channel"]),
                firmware_rollout_days=int(
                    data.get("firmware_rollout_days", policy["firmware_rollout_days"])
                ),
                firmware_blocked_versions=(
                    [v.strip() for v in data["firmware_blocked_versions"].split(",") if v.strip()]
                    if "firmware_blocked_versions" in data
                    else policy["firmware_blocked_versions"]
                ),
                firmware_pinned_version=(
                    data.get("firmware_pinned_version", policy["firmware_pinned_version"]) or None
                ),
                processing_preset=data["preset"],
                dither_algorithm=data["dither"],
                show_species_name=data.get("labels") == "on",
                show_location_name=data.get("location_name", data.get("location_date")) == "on",
                weather_cues=data.get("weather") == "on",
                weather_max_age_minutes=int(
                    data.get("weather_max_age", policy["weather_max_age_minutes"])
                ),
                show_weather_icon=data.get("weather_icon") == "on",
                show_weather_condition=data.get("weather_condition") == "on",
                show_forecast_temperatures=data.get("forecast_temperatures") == "on",
                show_dated_weather_text=data.get("forecast_text") == "on",
                seasonal_themes=data.get("season") == "on",
            )
            validated = FramePolicy.model_validate(policy)
        except (ValueError, KeyError) as error:
            message = (
                "Check the daily wake time, bird count and processing settings. Nothing was saved."
            )
            names = {
                "wake_local_time": "wake",
                "max_birds": "max_birds",
                "processing_preset": "preset",
                "dither_algorithm": "dither",
                "weather_max_age_minutes": "weather_max_age",
            }
            fields = (
                [names.get(str(e["loc"][0]), str(e["loc"][0])) for e in error.errors() if e["loc"]]
                if isinstance(error, ValidationError)
                else []
            )
            raise HTTPException(400, {"message": message, "fields": fields}) from None
        return validated

    @app.post("/manage/frames/{identifier}/management-access")
    async def management_access(identifier: str, request: Request):
        data = await checked_form(request)
        policy = FramePolicy.model_validate_json(service.store.frame(identifier)["policy"])
        policy = policy.model_copy(
            update={"management_trusted_wan": data.get("management_trusted_wan") == "on"}
        )
        service.store.set_policy(identifier, policy, expected_revision=expected_revision(data))
        return RedirectResponse(
            "/manage/settings?" + urlencode({"frame": identifier, "saved": "1"}), status_code=303
        )

    @app.post("/manage/frames/{identifier}/appearance-preview")
    async def draft_appearance_preview(identifier: str, request: Request):
        data = await checked_form(request)
        try:
            validated = appearance_policy(identifier, data)
            frame = service.store.frame(identifier)
            revision = expected_revision(data)
            if revision is not None and revision != frame["config_revision"]:
                raise ValueError("Saved settings changed. Reload before previewing.")
            token = await run_in_threadpool(service.preview_appearance, identifier, validated)
        except HTTPException as error:
            detail = (
                error.detail if isinstance(error.detail, dict) else {"message": str(error.detail)}
            )
            return JSONResponse(
                {
                    "message": detail["message"],
                    "field_errors": {name: detail["message"] for name in detail.get("fields", [])},
                },
                status_code=error.status_code,
            )
        except ValueError as error:
            return JSONResponse({"message": str(error), "field_errors": {}}, status_code=409)
        except RuntimeError:
            return JSONResponse(
                {"message": "Preparation is busy. Try preview again shortly.", "field_errors": {}},
                status_code=409,
            )
        except Exception:
            return JSONResponse(
                {
                    "message": (
                        "Preview could not be prepared. Your settings are still here; try again."
                    ),
                    "field_errors": {},
                },
                status_code=503,
            )
        preview_url = f"/manage/frames/{identifier}/appearance-preview/{token}"
        if "text/html" in request.headers.get("accept", ""):
            body = (
                '<section><h2>Unsaved preview</h2><img class="preview" src="'
                + escape(preview_url)
                + '" alt="Draft artwork with your unsaved settings">'
                "<p>This artwork has not been saved or delivered. Panel colors may differ.</p>"
                '<form method="post" action="/manage/frames/' + escape(identifier) + '/settings">'
            )
            body += "".join(
                '<input type="hidden" name="' + escape(key) + '" value="' + escape(value) + '">'
                for key, value in data.items()
                if key not in {"action", "preview_token", "frame_revision"}
            )
            body += (
                '<input type="hidden" name="preview_token" value="' + escape(token) + '">'
                '<div class="actions"><button name="action" value="queue">'
                'Save and queue preview</button><a class="button secondary" href="'
                + escape("/manage/appearance?" + urlencode({"frame": identifier}))
                + '">Return to settings</a></div></form></section>'
            )
            return page("Appearance preview", body, active="appearance", frame=identifier)
        return JSONResponse({"token": token, "preview_url": preview_url})

    @app.get("/manage/frames/{identifier}/appearance-preview/{token}")
    def draft_appearance_image(identifier: str, token: str, request: Request):
        require(request)
        try:
            draft = service.appearance_preview(identifier, token)
        except ValueError as error:
            raise HTTPException(404, str(error)) from None
        return Response(
            draft["preview"], media_type="image/jpeg", headers={"Cache-Control": "no-store"}
        )

    @app.post("/manage/frames/{identifier}/settings")
    async def frame_settings(identifier: str, request: Request):
        data = await checked_form(request)
        validated = appearance_policy(identifier, data)
        try:
            if data.get("action") == "queue":
                await run_in_threadpool(
                    service.queue_appearance_preview,
                    identifier,
                    data.get("preview_token", ""),
                    validated,
                )
                return RedirectResponse(
                    "/manage/appearance?" + urlencode({"frame": identifier, "queued": "1"}),
                    status_code=303,
                )
            expected = expected_revision(data)
            service.store.set_policy(identifier, validated, expected_revision=expected)
        except RevisionConflict:
            raise
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        except RuntimeError:
            raise HTTPException(
                409, "Preparation is busy. Your settings were not changed; try again shortly."
            ) from None
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
        service.store.set_policy(identifier, validated, expected_revision=expected_revision(data))
        return redirect(request)

    def event_art_panel(request, csrf, frame):
        body = (
            '<details id="special-day-art" class="special-day-art">'
            "<summary>Artwork collection</summary>"
            '<p class="quiet">These illustrations are used only on the special days '
            "you assign them to. "
            "They stay out of everyday bird rotation.</p>"
        )
        notices = {
            "uploaded": (
                "Artwork added and ready to use. Choose it under Featured artwork on a day above."
            ),
            "remove": "Uploaded artwork removed.",
        }
        if request.query_params.get("result") in notices:
            body += (
                '<p class="notice success" role="status">'
                + notices[request.query_params["result"]]
                + "</p>"
            )
        body += (
            '<h3>Add artwork</h3><form method="post" action="/manage/event-art/upload" '
            'enctype="multipart/form-data">'
            + hidden(csrf)
            + '<input type="hidden" name="frame" value="'
            + escape(frame)
            + '">'
            + field("title", "Artwork title", "", extra='maxlength="80" required')
            + '<label>Image<input type="file" name="image" '
            'accept="image/png,image/jpeg,image/webp" required></label><p class="quiet">'
            "PNG, JPEG or WebP, up to 10 MB. Images are saved as still PNG files and are "
            "ready to use immediately.</p><button>Add artwork</button></form>"
        )
        entries = service.event_art.entries()
        if not entries:
            body += (
                '<p class="empty-state">No special-day artwork yet. Add an illustration above.</p>'
            )
        else:
            body += '<div class="card-grid artwork-grid">'
            for art in entries:
                art_id, title = escape(art["id"]), escape(art["common_name"])
                uses = [
                    (f["id"], d)
                    for f in service.store.frames()
                    for d in FramePolicy.model_validate_json(f["policy"]).special_days
                    if d.artwork_id == art["id"]
                ]
                body += (
                    '<article class="card library-card artwork-card"><div class="artwork-media">'
                    '<a href="/manage/event-art/' + art_id + '/image" target="_blank" '
                    'rel="noopener" aria-label="Open full ' + title + ' illustration">'
                    '<img class="artwork-thumb" loading="lazy" src="/manage/event-art/'
                    + art_id
                    + '/thumbnail" alt="'
                    + title
                    + '"></a></div><h3>'
                    + title
                    + "</h3>"
                )
                if uses:
                    body += '<p class="quiet">Assigned to:</p><ul>'
                    for frame_id, day in uses:
                        body += (
                            '<li><a href="/manage/events?'
                            + escape(urlencode({"frame": frame_id, "focus": "event-" + day.id}))
                            + "#event-"
                            + escape(day.id)
                            + '">'
                            + escape(day.label)
                            + "</a></li>"
                        )
                    body += (
                        '</ul><p class="quiet">Choose another artwork for these days '
                        "before removing it.</p>"
                    )
                else:
                    body += '<p class="quiet">Not assigned to a special day.</p>'
                body += (
                    '<form method="post" action="/manage/event-art/'
                    + art_id
                    + '">'
                    + hidden(csrf)
                    + '<input type="hidden" name="frame" value="'
                    + escape(frame)
                    + '">'
                    '<button class="danger compact-action" name="action" value="remove"'
                    + (" disabled" if uses else "")
                    + ">Remove artwork</button></form></article>"
                )
            body += "</div>"
        return body + "</details>"

    @app.get("/manage/event-art")
    def retired_event_art_collection(request: Request, frame: str = ""):
        require(request)
        params = {"focus": "special-day-art"}
        if frame:
            service.store.frame(frame)
            params["frame"] = frame
        return RedirectResponse(
            "/manage/events?" + urlencode(params) + "#special-day-art", status_code=303
        )

    def event_art_return(data, result):
        params = {"result": result, "focus": "special-day-art"}
        if any(f["id"] == data.get("frame") for f in service.store.frames()):
            params["frame"] = data["frame"]
        return "/manage/events?" + urlencode(params) + "#special-day-art"

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

    @app.get("/manage/event-art/{artwork_id}/thumbnail")
    def event_art_thumbnail(artwork_id: str, request: Request):
        from .thumbnails import thumbnail_file

        require(request)
        entry = next((a for a in service.event_art.entries() if a["id"] == artwork_id), None)
        if not entry:
            raise HTTPException(404, "Unknown special-day art")
        try:
            source = service.event_art.path(entry)
            stat = source.stat()
            path, tag = thumbnail_file(
                source,
                stat.st_mtime_ns,
                stat.st_size,
                service.settings.data_dir / "cache" / "thumbnails",
            )
        except (OSError, ValueError):
            raise HTTPException(503, "Artwork thumbnail unavailable") from None
        headers = {"Cache-Control": "private, no-cache", "ETag": tag}
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers=headers)
        return FileResponse(path, media_type="image/jpeg", headers=headers)

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
            if name not in {"csrf", "title", "attribution", "image", "frame"} or name in data:
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
                    data.get("image", b""),
                    data.get("title", ""),
                    data.get("attribution") or "Owner upload",
                )
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        except RuntimeError:
            raise HTTPException(409, "Preparation is busy; try again shortly") from None
        return RedirectResponse(event_art_return(data, "uploaded"), status_code=303)

    @app.post("/manage/event-art/{artwork_id}")
    async def remove_event_art(artwork_id: str, request: Request):
        data = await checked_form(request)
        try:
            with preparation_lock(service.settings.data_dir):
                if data.get("action") == "remove":
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
                else:
                    raise ValueError("Unknown artwork action")
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        except RuntimeError:
            raise HTTPException(409, "Preparation is busy; try again shortly") from None
        return RedirectResponse(event_art_return(data, data["action"]), status_code=303)

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
            service.store.set_policy(
                identifier,
                FramePolicy.model_validate(policy),
                expected_revision=expected_revision(data),
            )
        except ValueError as error:
            raise HTTPException(400, "Invalid collection: " + str(error)) from None
        return RedirectResponse(
            "/manage/events?" + urlencode({"frame": identifier, "saved": "1"}), status_code=303
        )

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
            previous = next((d for d in policy["special_days"] if d["id"] == day_id), {})
            recurrence = previous.get("recurrence")
            if "date_rule" in data:
                if data["date_rule"] not in {"fixed", "nth_weekday"}:
                    raise HTTPException(
                        400,
                        {
                            "message": "Choose a fixed date or a weekday each year.",
                            "fields": ["date_rule"],
                        },
                    )
                recurrence = (
                    {
                        "kind": "nth_weekday",
                        "month": int(data.get("rule_month", "1")),
                        "weekday": int(data.get("rule_weekday", "0")),
                        "ordinal": int(data.get("rule_ordinal", "1")),
                    }
                    if data["date_rule"] == "nth_weekday"
                    else None
                )
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
                    "recurrence": recurrence,
                    "priority": int(data.get("priority", previous.get("priority", 0))),
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
                            or (day.recurrence.month if day.recurrence else int(day.date[5:7]))
                            not in art["months"]
                        )
                    )
                ):
                    raise HTTPException(
                        400,
                        {
                            "message": "Choose special-day art, bird art "
                            "eligible for this "
                            "month, or seasonal selection. Your other changes are still here.",
                            "fields": ["artwork_id"],
                        },
                    )
            if data.get("id"):
                policy["special_days"] = [
                    day.model_dump() if d["id"] == day_id else d for d in policy["special_days"]
                ]
            else:
                policy["special_days"].append(day.model_dump())
            validated = FramePolicy.model_validate(policy)
        except ValidationError as error:
            names = []
            messages = []
            recurrence_fields = {
                "month": "rule_month",
                "weekday": "rule_weekday",
                "ordinal": "rule_ordinal",
                "kind": "date_rule",
            }
            for item in error.errors(include_url=False):
                name = str(item["loc"][-1]) if item["loc"] else "date"
                names.append(recurrence_fields.get(name, name))
                messages.append(item["msg"].removeprefix("Value error, "))
            raise HTTPException(
                400,
                {
                    "message": "Check this special day: " + "; ".join(dict.fromkeys(messages)),
                    "fields": names,
                },
            ) from None
        except (ValueError, KeyError) as error:
            names = ["priority"] if "priority" in data and not data["priority"].isdigit() else []
            raise HTTPException(
                400, {"message": "Invalid special day: " + str(error), "fields": names}
            ) from None
        service.store.set_policy(identifier, validated, expected_revision=expected_revision(data))
        return RedirectResponse(
            "/manage/events?"
            + urlencode({"frame": identifier, "saved": "1", "focus": "event-" + day_id})
            + "#event-"
            + day_id,
            status_code=303,
        )

    @app.post("/manage/frames/{identifier}/special-days/{day_id}/delete")
    async def delete_special_day(identifier: str, day_id: str, request: Request):
        data = await checked_form(request)
        policy = FramePolicy.model_validate_json(
            service.store.frame(identifier)["policy"]
        ).model_dump()
        if not any(d["id"] == day_id for d in policy["special_days"]):
            raise HTTPException(404, "Unknown special day")
        policy["special_days"] = [d for d in policy["special_days"] if d["id"] != day_id]
        service.store.set_policy(
            identifier,
            FramePolicy.model_validate(policy),
            expected_revision=expected_revision(data),
        )
        return RedirectResponse(
            "/manage/events?" + urlencode({"frame": identifier, "saved": "1"}), status_code=303
        )

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
            service.save_configuration(config, expected_revision=data.get("configuration_revision"))
        except RevisionConflict:
            raise
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
        service.save_configuration(config, expected_revision=data.get("configuration_revision"))
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
        if require(request).get("network_access"):
            raise HTTPException(403, "Sign in with the owner password before changing credentials")
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
