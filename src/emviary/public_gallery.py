"""Read-only composition previews for the configured public frame only."""

from html import escape

from fastapi import HTTPException
from fastapi.responses import FileResponse


def public_records(service):
    identifier = service.settings.config.public_frame_id
    if not identifier:
        return None, {}, []
    try:
        frame = service.store.frame(identifier)
    except ValueError:
        return None, {}, []
    current = service.delivered_image(frame)
    upcoming = {
        "Daily refresh": service.store.slot_image(identifier, "scheduled"),
        "Next button": service.store.active_image(frame),
    }
    past = service.store.past_compositions(identifier, current["id"], 10) if current else []
    return current, upcoming, past


def gallery_markup(service):
    current, upcoming, past = public_records(service)

    def usable(record):
        return (
            record
            and not record.get("hidden")
            and service.cache_path(record["preview_path"]).is_file()
        )

    def card(record, label):
        return (
            '<figure><a href="/display/images/' + str(record["id"]) + '.jpg">'
            '<img class="preview" loading="lazy" width="800" height="480" '
            'alt="'
            + escape(label, quote=True)
            + '" src="/display/images/'
            + str(record["id"])
            + '.jpg"></a><figcaption>'
            + escape(label)
            + "</figcaption></figure>"
        )

    body = ""
    ready = [(label, image) for label, image in upcoming.items() if usable(image)]
    if ready:
        body += '<section class="public-compositions"><h2>Coming up</h2>'
        body += (
            '<p class="quiet">Prepared previews. The daily picture can change '
            "as the forecast updates.</p>"
        )
        body += (
            '<div class="current-next">'
            + "".join(card(image, label) for label, image in ready)
            + "</div></section>"
        )
    history = [image for image in past if usable(image)]
    if history:
        body += (
            '<section class="public-compositions"><h2>Past compositions</h2>'
            '<div class="current-next">'
        )
        body += "".join(card(image, image["local_date"]) for image in history[:2]) + "</div>"
        if len(history) > 2:
            body += '<details><summary>More past compositions</summary><div class="current-next">'
            body += (
                "".join(card(image, image["local_date"]) for image in history[2:])
                + "</div></details>"
            )
        body += "</section>"
    return body


def install_routes(app, service):
    @app.get("/display/images/{image_id}.jpg")
    def composition_preview(image_id: int):
        current, upcoming, past = public_records(service)
        records = [current, *upcoming.values(), *past]
        chosen = next(
            (
                image
                for image in records
                if image and image["id"] == image_id and not image.get("hidden")
            ),
            None,
        )
        if not chosen or not service.cache_path(chosen["preview_path"]).is_file():
            raise HTTPException(404, "Public composition unavailable")
        return FileResponse(
            service.cache_path(chosen["preview_path"]),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
        )
