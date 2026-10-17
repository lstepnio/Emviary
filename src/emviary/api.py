import asyncio
import hashlib
import html
import json
import logging
import mimetypes
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.background import BackgroundTask

from . import __version__
from .branding import BIRD_ICON
from .diagnostics import parse_metrics
from .firmware_updates import FirmwareUpdates
from .offline_cache import offline_header
from .recovery_sessions import RecoverySessions, device_headers, promote_pending_token
from .service import Service
from .settings import FramePolicy
from .store import stable_json
from .trusted_network import record_frame_network

log = logging.getLogger(__name__)


def config_payload(frame):
    policy = json.loads(frame["policy"])
    config = {
        "timezone": policy["firmware_timezone"],
        "auto_rotate": True,
        "rotate_cron": policy["firmware_rotate_cron"],
        "rotation_mode": "url",
        "deep_sleep_enabled": True,
        "display_orientation": policy["panel"]["orientation"],
        "debug_log_enabled": policy.get("firmware_debug_logging", False),
    }
    if policy.get("wifi_networks") is not None:
        config["wifi_networks"] = policy["wifi_networks"]
        config["wifi_keep_existing"] = True
        config["wifi_forget_ssids"] = policy.get("wifi_forget_ssids", [])
    return stable_json({"config": config})


def etag_for(frame, image):
    return f'"{image["body_hash"]}-c{frame["config_revision"]}"'


def etag_matches(header, value):
    # RFC conditional GET permits weak validators and a comma-separated list.
    if not header:
        return False
    return any(token.strip().removeprefix("W/") in ("*", value) for token in header.split(","))


def authenticated(request, service):
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    frame = None
    if scheme.casefold() == "bearer":
        recovery = device_headers(request)
        if recovery and request.url.path in {"/v1/image", "/v1/recovery/ack"}:
            frame = RecoverySessions(service.store).authenticate(
                token.strip(), recovery["session_id"], recovery["nonce"]
            )
        if frame is None:
            frame = service.store.authenticate(token.strip())
    if not frame:
        raise HTTPException(
            401, "Invalid frame credentials", headers={"WWW-Authenticate": "Bearer"}
        )
    return frame


def check_geometry(request, frame):
    panel = json.loads(frame["policy"])["panel"]
    for header, key in (("x-display-width", "width"), ("x-display-height", "height")):
        value = request.headers.get(header)
        if value is not None and value != str(panel[key]):
            raise HTTPException(409, "Display geometry does not match the registered frame")
    orientation = request.headers.get("x-display-orientation")
    if orientation and orientation != panel["orientation"]:
        raise HTTPException(409, "Display orientation does not match the registered frame")


def create_app(service=None, schedule=True):
    service = service or Service()

    async def scheduler():
        while True:
            try:
                await asyncio.to_thread(service.prepare_due)
            except Exception as exc:
                log.warning("Scheduler cycle skipped: %s", type(exc).__name__)
            await asyncio.sleep(60)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(scheduler()) if schedule else None
        yield
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(
        title="Emviary",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.service = service
    app.state.firmware_updates = FirmwareUpdates()

    @app.middleware("http")
    async def canonical_host(request, call_next):
        # Installed frames keep their original URL until they are reprovisioned.
        if request.url.hostname == "eink.majjix.com" and not (
            request.url.path.startswith("/v1/") or request.url.path == "/healthz"
        ):
            return RedirectResponse(
                str(request.url.replace(scheme="https", netloc="emviary.majjix.com")),
                status_code=308,
            )
        return await call_next(request)

    @app.get("/favicon.svg")
    def bird_icon():
        return Response(
            BIRD_ICON,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"},
        )

    @app.get("/healthz")
    def health():
        with service.store.connect() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok", "version": __version__}

    @app.get("/v1/firmware")
    def firmware(request: Request, current: str = ""):
        frame = authenticated(request, service)
        if len(current) > 80:
            raise HTTPException(400, "Invalid firmware version")
        policy = FramePolicy.model_validate_json(frame["policy"])
        return JSONResponse(
            app.state.firmware_updates.check(
                policy,
                current,
                rollback_ready=bool(
                    service.store.device_samples(frame["id"])
                    and json.loads(service.store.device_samples(frame["id"])[-1]["metrics"]).get(
                        "ota_rollback"
                    )
                    is True
                ),
            ),
            headers={"Cache-Control": "private, no-store"},
        )

    @app.get("/v1/image")
    def image(request: Request):
        frame = authenticated(request, service)
        check_geometry(request, frame)
        record_frame_network(request, service, frame)
        direction = request.headers.get("x-image-navigation", "latest")
        if direction not in {"latest", "previous", "next"}:
            raise HTTPException(400, "Unknown image navigation direction")
        record, retain = service.select_image(
            frame, direction, request.headers.get("if-none-match", "")
        )
        if not record:
            raise HTTPException(503, "No prepared image", headers={"Retry-After": "300"})
        path = service.cache_path(record["path"])
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != record["body_hash"]
        ):
            raise HTTPException(503, "Prepared image unavailable")
        tag = etag_for(frame, record)
        battery = request.headers.get("x-battery-percentage", "")
        battery = int(battery) if battery.isdecimal() and len(battery) <= 3 else None
        if battery is not None and not 0 <= battery <= 100:
            battery = None
        try:
            voltage = float(request.headers.get("x-battery-voltage", ""))
            voltage = voltage / 1000 if 1000 <= voltage <= 6000 else None
        except ValueError:
            voltage = None

        def optional_bool(name):
            value = request.headers.get(name, "").lower()
            return {"1": True, "0": False, "true": True, "false": False}.get(value)

        charging = optional_bool("x-battery-charging")
        usb_connected = optional_bool("x-usb-connected")
        firmware = request.headers.get("x-firmware-version")
        if firmware:
            firmware = firmware[:80]
        client_tag = request.headers.get("if-none-match", "")[:256]
        background = (
            BackgroundTask(
                service.image_delivered,
                frame["id"],
                record["id"],
                battery,
                firmware,
                client_tag,
                tag,
                voltage,
                charging,
                usb_connected,
                parse_metrics(request.headers.get("x-frame-metrics")),
            )
            if firmware
            else None
        )
        payload = config_payload(frame)
        if len(payload.encode()) > 1900:
            raise HTTPException(503, "Configuration exceeds the firmware header limit")
        headers = {"ETag": tag, "Cache-Control": "private, no-cache"}
        recovery = device_headers(request)
        if recovery:
            token = request.headers.get("authorization", "").partition(" ")[2].strip()
            RecoverySessions(service.store).image_requested(frame, recovery, record, token)
            promote_pending_token(service, frame["id"], recovery["session_id"])
            headers["X-Recovery-Image-Sha256"] = record["body_hash"]
            headers["X-Recovery-Image-Id"] = str(record["id"])
            # Recovery verifies the full body, even if an ordinary ETag would retain it.
            retain, client_tag = False, ""

        if retain or etag_matches(client_tag, tag):
            headers["X-Config-Payload"] = payload
            if retain:
                headers["X-Image-Readiness"] = "retained; refreshing on server"
            return Response(status_code=304, headers=headers, background=background)
        headers["X-Config-Payload"] = payload
        if request.headers.get("x-emviary-offline-version") == "1":
            metadata = offline_header(record)
            if metadata:
                headers["X-Emviary-Offline"] = metadata
        return FileResponse(
            path, media_type="application/octet-stream", headers=headers, background=background
        )

    @app.post("/v1/recovery/ack")
    async def recovery_ack(request: Request):
        if (
            request.headers.get("content-length", "").isdigit()
            and int(request.headers["content-length"]) > 2048
        ):
            raise HTTPException(413, "Recovery acknowledgment too large")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 2048:
                raise HTTPException(413, "Recovery acknowledgment too large")
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Invalid recovery acknowledgment") from None
        if not isinstance(data, dict):
            raise HTTPException(400, "Invalid recovery acknowledgment")
        frame = authenticated(request, service)
        return JSONResponse(
            RecoverySessions(service.store).acknowledge(frame, data),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/v1/preview")
    def preview(request: Request):
        frame = authenticated(request, service)
        record = service.store.active_image(frame)
        if not record:
            raise HTTPException(503, "No prepared preview")
        path = service.cache_path(record["preview_path"])
        if not path.is_file():
            raise HTTPException(503, "Prepared preview unavailable")
        return FileResponse(
            path, media_type="image/jpeg", headers={"Cache-Control": "private, no-cache"}
        )

    @app.get("/art/{artwork_id}")
    def public_art(artwork_id: str):
        artwork = next((a for a in service.settings.artworks if a["id"] == artwork_id), None)
        if not artwork:
            raise HTTPException(404, "Unknown artwork")
        return FileResponse(
            service.settings.art_dir / artwork["asset"],
            media_type=mimetypes.guess_type(artwork["asset"])[0] or "application/octet-stream",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/art-thumbnail/{artwork_id}")
    def artwork_thumbnail(artwork_id: str, request: Request):
        from .thumbnails import thumbnail_file

        artwork = next((a for a in service.settings.artworks if a["id"] == artwork_id), None)
        if not artwork:
            raise HTTPException(404, "Unknown artwork")
        path = (service.settings.art_dir / artwork["asset"]).resolve()
        if not path.is_relative_to(service.settings.art_dir.resolve()) or not path.is_file():
            raise HTTPException(404, "Artwork unavailable")
        try:
            stat = path.stat()
            body, tag = thumbnail_file(
                str(path),
                stat.st_mtime_ns,
                stat.st_size,
                service.settings.data_dir / "cache" / "thumbnails",
            )
        except (OSError, ValueError):
            raise HTTPException(503, "Artwork thumbnail unavailable") from None
        headers = {
            "Cache-Control": "public, max-age=3600",
            "ETag": tag,
            "X-Content-Type-Options": "nosniff",
        }
        if etag_matches(request.headers.get("if-none-match", ""), tag):
            return Response(status_code=304, headers=headers)
        return FileResponse(body, media_type="image/jpeg", headers=headers)

    @app.get("/credits.json")
    def credits():
        return service.settings.catalog

    @app.get("/art-license/{artwork_id}")
    def artwork_license(artwork_id: str):
        artwork = next((a for a in service.settings.artworks if a["id"] == artwork_id), None)
        if not artwork or not artwork.get("license_file"):
            raise HTTPException(404, "License notice unavailable")
        path = (service.settings.art_dir / artwork["license_file"]).resolve()
        if not path.is_relative_to(service.settings.art_dir / "licenses") or not path.is_file():
            raise HTTPException(404, "License notice unavailable")
        return FileResponse(path, media_type="text/plain")

    @app.get("/library", response_class=HTMLResponse)
    def index(
        q: str = "",
        sort: str = "name",
        kind: str = "",
        status: str = "",
        style: str = "",
        p: int = 1,
    ):
        from urllib.parse import urlencode

        from .ui import page

        escape = html.escape
        counts = service.store.bird_counts()
        artworks = service.settings.artworks
        kinds = sorted({a.get("kind", "cutout") for a in artworks})
        styles = sorted({a.get("style", "natural-history") for a in artworks})
        sort = sort if sort in {"name", "most", "least"} else "name"
        kind = kind if kind in kinds else ""
        style = style if style in styles else ""
        status = status if status in {"rotation", "reference", "pending"} else ""
        q = q.strip()[:200]

        def artwork_status(artwork):
            return (
                "rotation"
                if artwork["approved"]
                else "reference"
                if artwork.get("kind") == "field_study"
                else "pending"
            )

        groups = {}
        for artwork in artworks:
            searchable = " ".join(
                str(artwork.get(key, ""))
                for key in ("common_name", "scientific_name", "source", "credit")
            )
            if q.casefold() not in searchable.casefold():
                continue
            if kind and artwork.get("kind", "cutout") != kind:
                continue
            if style and artwork.get("style", "natural-history") != style:
                continue
            if status and artwork_status(artwork) != status:
                continue
            groups.setdefault(artwork["scientific_name"], []).append(artwork)
        ordered = sorted(
            groups.items(),
            key=lambda pair: (
                -counts.get(pair[0], 0)
                if sort == "most"
                else counts.get(pair[0], 0)
                if sort == "least"
                else 0,
                pair[1][0]["common_name"].casefold(),
                pair[0],
            ),
        )
        total_pages = max(1, (len(ordered) + 23) // 24)
        p = min(max(1, p), total_pages)

        def select(name, label, options, selected):
            return (
                "<label>"
                + label
                + '<select name="'
                + name
                + '">'
                + "".join(
                    '<option value="'
                    + escape(value, quote=True)
                    + '"'
                    + (" selected" if value == selected else "")
                    + ">"
                    + escape(text)
                    + "</option>"
                    for value, text in options
                )
                + "</select></label>"
            )

        active_count = sum(a["approved"] for a in artworks)
        species_count = len({a["scientific_name"] for a in artworks if a["approved"]})
        body = (
            '<section id="artwork-library" data-library-path="/library" '
            f'data-first-page="{p}" data-last-page="{p}" data-total-pages="{total_pages}">'
            '<header class="page-header"><p class="eyebrow">The collection</p>'
            '<h1>Artwork library</h1><p class="intro">Explore the bird illustrations '
            "from the frame.</p></header>"
            '<p class="quiet">'
            + str(species_count)
            + " species · "
            + str(active_count)
            + " rotation images · "
            + str(len(artworks))
            + " total artworks</p>"
            '<form class="toolbar library-filters" method="get" action="/library">'
            '<label>Search<input type="search" name="q" value="'
            + escape(q, quote=True)
            + '" placeholder="Find a bird"></label>'
            + select(
                "sort",
                "Sort",
                [("name", "Name A to Z"), ("most", "Most rendered"), ("least", "Least rendered")],
                sort,
            )
            + select(
                "status",
                "Availability",
                [
                    ("", "All artwork"),
                    ("rotation", "In rotation"),
                    ("reference", "Web reference only"),
                    ("pending", "Review pending"),
                ],
                status,
            )
            + select(
                "kind",
                "Format",
                [("", "All formats")]
                + [(value, value.replace("_", " ").title()) for value in kinds],
                kind,
            )
            + select(
                "style",
                "Style",
                [("", "All styles")]
                + [(value, value.replace("-", " ").title()) for value in styles],
                style,
            )
            + '<button type="submit">Apply filters</button>'
            '<a class="button secondary" href="/library">Reset</a></form>'
            '<p class="quiet">' + str(len(ordered)) + " species match. Render counts count "
            "successful compositions containing a species, once per composition; "
            "they are not page views or confirmed physical displays.</p>"
        )
        cards = []
        for name, variants in ordered[(p - 1) * 24 : p * 24]:
            variants.sort(key=lambda a: (not a["approved"], a["id"]))
            artwork = variants[0]
            images = []
            for number, item in enumerate(variants, start=1):
                identifier = escape(item["id"], quote=True)
                images.append(
                    '<a href="/art/' + identifier + '" target="_blank" rel="noopener">'
                    '<img class="artwork-thumb" loading="lazy" src="/art-thumbnail/'
                    + identifier
                    + '" alt="'
                    + escape(item["common_name"], quote=True)
                    + ", illustration "
                    + str(number)
                    + '"></a>'
                )
            cards.append(
                '<article class="card library-card artwork-card" data-artwork-id="'
                + escape(artwork["id"], quote=True)
                + '"><div class="artwork-media">'
                '<a href="/art/'
                + escape(artwork["id"], quote=True)
                + '" target="_blank" rel="noopener"><img class="artwork-thumb" '
                'loading="lazy" src="/art-thumbnail/'
                + escape(artwork["id"], quote=True)
                + '" alt="'
                + escape(artwork["common_name"], quote=True)
                + '"></a></div><div class="artwork-heading"><h2>'
                + escape(artwork["common_name"])
                + '</h2></div><p class="artwork-meta">'
                + "Species renders: "
                + str(counts.get(name, 0))
                + "</p>"
                + (
                    '<details class="artwork-options"><summary>'
                    + str(len(variants))
                    + ' illustrations</summary><div class="variant-grid">'
                    + "".join(images)
                    + "</div></details>"
                    if len(variants) > 1
                    else ""
                )
                + "</article>"
            )
        body += (
            '<div class="card-grid artwork-grid">' + "".join(cards) + "</div>"
            if cards
            else '<section class="empty-state"><h2>No artwork matches</h2>'
            "<p>Try a different bird name or broaden the filters.</p>"
            '<a class="button secondary" href="/library">Browse all artwork</a></section>'
        )
        if total_pages > 1:
            parameters = {"q": q, "sort": sort, "kind": kind, "status": status, "style": style}
            body += (
                '<nav class="toolbar pagination" aria-label="Library pages" '
                "data-artwork-pagination>"
            )
            for number, label in ((p - 1, "Previous"), (p + 1, "Next")):
                if 1 <= number <= total_pages:
                    body += (
                        '<a class="button secondary" '
                        + ("data-artwork-next " if label == "Next" else "")
                        + 'href="/library?'
                        + escape(urlencode({**parameters, "p": number}), quote=True)
                        + '">'
                        + label
                        + "</a>"
                    )
            body += (
                '<span class="quiet">Page ' + str(p) + " of " + str(total_pages) + "</span></nav>"
            )
        body += '<div class="library-help" hidden></div></section>'
        return page(
            "Artwork library",
            body,
            active="artwork",
            public=True,
            description="Explore the birds and artwork from Emviary.",
        )

    from .public_gallery import gallery_markup
    from .public_gallery import install_routes as install_public_gallery

    install_public_gallery(app, service)

    @app.get("/")
    def display_home():
        from .ui import page

        record = None
        identifier = service.settings.config.public_frame_id
        if identifier:
            try:
                record = service.delivered_image(service.store.frame(identifier))
            except ValueError:
                pass
        available = record and service.cache_path(record["preview_path"]).is_file()
        body = '<header class="page-header"><p class="eyebrow">On the frame</p>'
        body += "<h1>A little nature, every day, for Emily.</h1></header>"
        if available:
            body += (
                '<figure class="frame-preview"><img src="/display.jpg" '
                'width="800" height="480" alt="Last cloud-confirmed frame artwork">'
                '<figcaption class="quiet">Last cloud-confirmed picture. During an outage '
                "the frame may rotate cached art.</figcaption>"
                "</figure>"
            )
        else:
            body += (
                '<section class="empty-state"><h2>The first artwork is on its way.</h2>'
                "<p>The frame's artwork will appear here after its first delivery.</p></section>"
            )
        body += gallery_markup(service)
        body += (
            '<section class="public-library-invite"><div><h2>Meet the collection.</h2>'
            '<p class="quiet">Birds and Colorado wildlife, curated for the frame.</p></div>'
            '<a class="button secondary" href="/library">Explore the artwork library</a>'
            "</section>"
        )
        return page(
            "Emviary",
            body,
            active="frame",
            public=True,
            description="See current, upcoming and past nature compositions from Emviary.",
        )

    @app.get("/display.jpg")
    def public_display():
        identifier = service.settings.config.public_frame_id
        if not identifier:
            raise HTTPException(404, "No public display")
        try:
            frame = service.store.frame(identifier)
        except ValueError:
            raise HTTPException(404, "No public display") from None
        record = service.delivered_image(frame)
        if not record:
            raise HTTPException(404, "The frame has not fetched its first image")
        return FileResponse(
            service.cache_path(record["preview_path"]),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-cache"},
        )

    from .owner import attach_owner

    attach_owner(app, service)
    return app
