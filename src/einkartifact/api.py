import asyncio
import hashlib
import html
import json
import logging
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
            media_type="image/webp",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/credits.json")
    def credits():
        return service.settings.catalog

    @app.get("/", response_class=HTMLResponse)
    def index():
        cards, names = [], set()
        for artwork in service.settings.artworks:
            if artwork["scientific_name"] in names:
                continue
            names.add(artwork["scientific_name"])
            cards.append(
                '<article><img loading="lazy" src="/art/'
                + html.escape(artwork["id"], quote=True)
                + '" alt="Curated illustration of '
                + html.escape(artwork["common_name"], quote=True)
                + '"><h2>'
                + html.escape(artwork["common_name"])
                + "</h2><p><i>"
                + html.escape(artwork["scientific_name"])
                + '</i></p><a href="'
                + html.escape(artwork["source_url"], quote=True)
                + '">Original plate</a></article>'
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
        .intro{max-width:660px;font-size:19px;line-height:1.6;color:#656956}
        .gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
        gap:24px;margin:42px 0}article{padding:20px;background:#faf7ef;border:1px solid #d9d5c5}
        img{width:100%;height:190px;object-fit:contain}h2{font-weight:400;font-size:19px}
        article p,article a{font-size:13px}a{color:#536750}footer{border-top:1px solid #d1cbb9;
        padding-top:28px;font:14px/1.7 system-ui;color:#6a6d5d}
        </style><main><div class="eyebrow">Denver / natural history / e-paper</div>
        <h1>A little bird art,<br>every morning.</h1>
        <p class="intro">Curated natural-history illustrations, selected for birds around Denver.
        A fresh composition each night brings a quiet hint of the season and the day's outlook.</p>
        <div class="gallery">"""
            + "".join(cards)
            + """</div>
        <footer>Artwork curated and restored by
        <a href="https://github.com/arnegiacomo/fugleramme">Fugleramme contributors</a>.
        Classic cutouts and our adapted compositions:
        <a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>.
        Adaptations include resizing, seasonal/weather composition, labels, and panel dithering.
        Original plate sources are linked above; <a href="/credits.json">full credits</a>.<br>
        Regional detections from <a href="https://app.birdweather.com/">BirdWeather</a>;
        these do not establish visits to an individual garden. Forecasts:
        <a href="https://open-meteo.com/">Open-Meteo</a>,
        <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>.
        The artwork is a daily outlook, not a live weather report.</footer></main></html>"""
        )

    return app
