import asyncio
import hashlib
import html
import json
import logging
import mimetypes
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from . import __version__
from .service import Service
from .store import stable_json

log = logging.getLogger(__name__)


def config_payload(frame):
    policy = json.loads(frame["policy"])
    return stable_json(
        {
            "config": {
                "timezone": policy["firmware_timezone"],
                "auto_rotate": True,
                "rotate_cron": policy["firmware_rotate_cron"],
                "rotation_mode": "url",
                "deep_sleep_enabled": True,
                "display_orientation": policy["panel"]["orientation"],
            }
        }
    )


def etag_for(frame, image):
    return f'"{image["body_hash"]}-c{frame["config_revision"]}"'


def etag_matches(header, value):
    # RFC conditional GET permits weak validators and a comma-separated list.
    if not header:
        return False
    return any(token.strip().removeprefix("W/") in ("*", value) for token in header.split(","))


def authenticated(request, service):
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    frame = service.store.authenticate(token.strip()) if scheme.casefold() == "bearer" else None
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
        title="eInkArtifact",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.service = service

    @app.get("/healthz")
    def health():
        with service.store.connect() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok", "version": __version__}

    @app.get("/v1/image")
    def image(request: Request):
        frame = authenticated(request, service)
        check_geometry(request, frame)
        record = service.store.active_image(frame)
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
        firmware = request.headers.get("x-firmware-version")
        if firmware:
            firmware = firmware[:80]
        client_tag = request.headers.get("if-none-match", "")[:256]
        if firmware:
            service.store.telemetry(frame["id"], battery, firmware, client_tag, tag)
        headers = {"ETag": tag, "Cache-Control": "private, no-cache"}
        if etag_matches(client_tag, tag):
            return Response(status_code=304, headers=headers)
        payload = config_payload(frame)
        if len(payload.encode()) > 1900:
            raise HTTPException(503, "Configuration exceeds the firmware header limit")
        headers["X-Config-Payload"] = payload
        return FileResponse(path, media_type="application/octet-stream", headers=headers)

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
    def index():
        escape = html.escape
        groups = {}
        for artwork in service.settings.artworks:
            groups.setdefault(artwork["scientific_name"], []).append(artwork)
        cards = []
        for name, variants in sorted(groups.items(), key=lambda pair: pair[1][0]["common_name"]):
            variants.sort(key=lambda a: (not a["approved"], a["id"]))
            artwork = variants[0]
            active = sum(a["approved"] for a in variants)
            details = []
            for item in variants:
                identifier = escape(item["id"], quote=True)
                label = item["license"].replace("-", " ")
                license_link = (
                    "/art-license/" + identifier
                    if item.get("license_file")
                    else "https://creativecommons.org/licenses/by-sa/4.0/"
                )
                status = "In rotation" if item["approved"] else "Web reference only"
                medium = "Existing AI-generated art" if item.get("generated") else "Historical art"
                details.append(
                    '<section class="variant"><a href="/art/'
                    + identifier
                    + '"><img loading="lazy" src="/art/'
                    + identifier
                    + '" alt="'
                    + escape(item["common_name"], quote=True)
                    + '"></a><p>'
                    + escape(item["source"])
                    + "<br>"
                    + status
                    + " / "
                    + medium
                    + "</p><p>"
                    + escape(item.get("credit", ""))
                    + '</p><p><a href="'
                    + escape(item["source_url"], quote=True)
                    + '">Source artwork</a> / '
                    + '<a href="'
                    + license_link
                    + '">'
                    + escape(label)
                    + "</a></p><p>"
                    + escape(item["review_status"])
                    + "</p></section>"
                )
            cards.append(
                '<article><a href="/art/'
                + escape(artwork["id"], quote=True)
                + '"><img loading="lazy" src="/art/'
                + escape(artwork["id"], quote=True)
                + '" alt="'
                + escape(artwork["common_name"], quote=True)
                + '"></a><h2>'
                + escape(artwork["common_name"])
                + "</h2><p><i>"
                + escape(name)
                + "</i><br>"
                + str(active)
                + " rotation images"
                + (
                    " / " + str(len(variants) - active) + " web references"
                    if active < len(variants)
                    else ""
                )
                + "</p><details><summary>Variants and credits</summary>"
                + "".join(details)
                + "</details></article>"
            )
        active_count = sum(a["approved"] for a in service.settings.artworks)
        species_count = len(
            {a["scientific_name"] for a in service.settings.artworks if a["approved"]}
        )
        return (
            """<!doctype html><html lang="en"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Denver bird art</title><style>
        :root{color-scheme:light}*{box-sizing:border-box}
        body{margin:0;background:#f4f0e6;color:#343c32;font-family:Georgia,serif}
        main{max-width:1080px;margin:auto;padding:52px 24px}
        .eyebrow{font:12px system-ui;letter-spacing:.16em;text-transform:uppercase;color:#69715e}
        h1{font-size:clamp(38px,7vw,70px);font-weight:400;line-height:1.1;margin:20px 0}
        .intro{max-width:680px;font-size:19px;line-height:1.6;color:#656956}
        .gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
        gap:24px;margin:42px 0}article{padding:20px;background:#faf7ef;border:1px solid #d9d5c5}
        img{width:100%;height:190px;object-fit:contain}h2{font-weight:400;font-size:19px}
        article p,article a{font-size:13px}a{color:#536750}summary{cursor:pointer}
        .variant{border-top:1px solid #d9d5c5;margin-top:18px;padding-top:14px}
        footer{border-top:1px solid #d1cbb9;padding-top:28px;font:14px/1.7 system-ui;color:#6a6d5d}
        </style><main><p><a href="/">Display</a> / <a href="/manage">Manage</a></p>
        <div class="eyebrow">Denver / natural history / e-paper</div>
        <h1>A little bird art,<br>every morning.</h1>
        <p class="intro">"""
            + f"{active_count} rotation images covering {species_count} Denver-area species. "
            + """Historical illustrations and selected existing generated art bring variety to the
        frame. Text-heavy field studies are web references only. Seasonal eligibility applies to
        each pose; local reports influence selection without claiming a backyard visit.</p>
        <div class="gallery">"""
            + "".join(cards)
            + """</div><footer>Sources include
        <a href="https://github.com/arnegiacomo/fugleramme">Fugleramme</a>,
        <a href="https://github.com/adamoberley/HABirdDashboard">HABirdDashboard</a>,
        <a href="https://github.com/Belkins/belkins-birdnet">Belkins</a>,
        <a href="https://github.com/wr/featherframe">Featherframe's historical collection</a>,
        <a href="https://github.com/veteranbv/inky-bird-frame">Inky Bird Frame</a> and the
        shared art used by <a href="https://github.com/simenf/birdframe">BirdFrame</a>.
        Each asset retains its own license: CC BY-SA 4.0, CC BY-NC-SA 4.0, MIT or public domain.
        Belkins images and compositions using them are for noncommercial use.
        Incompatible ShareAlike assets are never combined into one frame image.
        Adaptations resize, compose, label and dither unchanged masters;
        <a href="/credits.json">full provenance and credits</a>.<br>
        Regional detections: <a href="https://app.birdweather.com/">BirdWeather</a>;
        optional regional reports: <a href="https://ebird.org/">eBird, Cornell Lab</a>.
        Forecasts: <a href="https://open-meteo.com/">Open-Meteo</a>,
        <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>.
        The artwork is a dated daily outlook.</footer></main></html>"""
        )

    @app.get("/")
    def display_home():
        from .owner import page

        body = '<img style="width:100%;height:auto" src="/display.jpg" alt="Current bird artwork">'
        body += (
            '<p class="quiet"><a href="/manage">Manage</a> · '
            '<a href="/library">Artwork and credits</a></p>'
        )
        return page("Daily bird art", body)

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
