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


def page(title, body):
    return HTMLResponse(
        """<!doctype html><html lang="en"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>"""
        + escape(title + " · Emviary" if title != "Emviary" else title)
        + """</title>
    <style>body{margin:0;background:#f4f0e6;color:#343c32;font:16px/1.6 Georgia,serif}
    main{max-width:920px;margin:auto;padding:35px 22px}h1,h2{font-weight:400}
    a{color:#536750}section{border-top:1px solid #d1cbb9;padding:20px 0;margin-top:20px}
    label{display:block;margin:10px 0}input,select,button{font:15px system-ui;padding:8px;
    border:1px solid #c7c5b8;border-radius:3px;background:#fffdf7}button{cursor:pointer}
    input[type=checkbox]{margin-right:10px}.grid{display:grid;grid-template-columns:repeat(auto-fit,
    minmax(210px,1fr));gap:10px 25px}.preview{width:100%;max-width:800px;border:1px solid #d1cbb9}
    .quiet{font:13px/1.5 system-ui;color:#6a6d5d}.error{color:#8c2d23}</style>
    <main><a class="quiet" href="/">Emviary · Display</a><h1>"""
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

    @app.get("/manage")
    def management(request: Request):
        auth = session(request)
        if not auth:
            return RedirectResponse("/manage/login", status_code=303)
        csrf = auth["csrf"]
        body = (
            '<p class="quiet">Changes apply on the next wake. '
            + '<a href="http://emviary.local" target="_blank" rel="noopener noreferrer">'
            + "Open local frame controls</a> · "
            + '<a href="http://photoframe.local" target="_blank" '
            + 'rel="noopener noreferrer">Legacy fallback</a>'
            + " (on the frame’s Wi-Fi, while awake).</p>"
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
            body += (
                '<details><summary>Firmware updates</summary><p class="quiet">'
                "Checked each time the frame wakes online. Automatic accepts newer published "
                "Emviary firmware, including preview releases. Manual requires a chosen version; "
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
                '<details><summary>Saved Wi-Fi networks</summary><p class="quiet">'
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
                    + field("password", "New password (blank keeps saved password)", "", "password")
                    + checkbox("open", "Open network, no password", not network["password"])
                    + '<p><button name="action" value="save">Update network</button> '
                    + '<button name="action" value="remove">Remove network</button></p></form>'
                )
            body += (
                '<form method="post" action="/manage/frames/'
                + identifier
                + '/wifi">'
                + hidden(csrf)
                + field("ssid", "Network name (SSID)", "", "text", "required")
                + field("password", "Network password", "", "password")
                + checkbox("open", "Open network, no password", False)
                + '<p><button name="action" value="save">Add network</button></p></form>'
                + "</details>"
            )
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
                + '/provision">Download private device configuration</a> · '
                + '<a href="/manage/frames/'
                + identifier
                + '/provision?import_file=true">Download recovery import file</a> · '
                + '<a href="#recovery">Recovery instructions</a>'
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
            "<p>An ordinary reboot keeps saved settings. The left button requests a new "
            "image; the right button is disabled. These buttons do not factory-reset "
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
            "cloud connection and wake schedule without replacing the Wi-Fi you just set up.</li>"
            "<li>Request a refresh with the left button or local image controls. "
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
                firmware_updates=data.get("firmware_updates", policy["firmware_updates"]),
                firmware_pinned_version=(
                    data.get("firmware_pinned_version", policy["firmware_pinned_version"]) or None
                ),
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
        except (RuntimeError, ValueError, OSError):
            return page(
                "Preparation unavailable",
                "<p>The last good image is retained.</p><a href='/manage'>Return</a>",
            )
        return redirect()
