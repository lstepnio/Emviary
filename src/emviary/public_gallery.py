"""Read-only composition previews for the configured public frame only."""

from html import escape
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.responses import FileResponse

from .compositions import composition_key
from .display_history import HISTORY_NOTE, reported_label


def public_records(service):
    identifier = service.settings.config.public_frame_id
    if not identifier:
        return None, {}, []
    try:
        frame = service.store.frame(identifier)
    except ValueError:
        return None, {}, []
    current = service.delivered_image(frame)
    daily = service.next_daily_refresh(frame)
    preview = daily["preview"]
    if preview:
        preview = {**preview, "preview_url": "/display/next-daily.jpg"}
    upcoming = {"Daily refresh": preview, "Next button": service.store.active_image(frame)}
    past = service.store.past_compositions(identifier, current["id"] if current else None, 10)
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
        url = record.get("preview_url") or f"/display/images/{record['id']}.jpg"
        return (
            '<figure><a href="' + escape(url, quote=True) + '">'
            '<img class="preview" loading="lazy" width="800" height="480" '
            'alt="'
            + escape(label, quote=True)
            + '" src="'
            + escape(url, quote=True)
            + '"></a><figcaption>'
            + escape(label)
            + "</figcaption></figure>"
        )

    body = ""
    grouped = {}
    for label, image in upcoming.items():
        if usable(image):
            labels, record = grouped.setdefault(composition_key(image), ([], image))
            labels.append(label)
    ready = [
        (
            ("Planned · " if image.get("planned") else "Prepared · ")
            + " · ".join(labels)
            + " · "
            + image["local_date"],
            image,
        )
        for labels, image in grouped.values()
    ]
    if ready or upcoming:
        body += '<section class="public-compositions"><h2>Coming up</h2>'
        frame = service.store.frame(service.settings.config.public_frame_id)
        daily = service.next_daily_refresh(frame)
        site = service.settings.config.site(frame["site_id"])
        zone = ZoneInfo(site.timezone)
        wake = daily["wake_at"].astimezone(zone).strftime("%b %d, %I:%M %p")
        weather = daily["prepare_at"].astimezone(zone).strftime("%b %d, %I:%M %p")
        body += (
            '<p class="quiet">Next daily refresh: '
            + escape(wake)
            + " · "
            + escape(site.timezone.rsplit("/", 1)[-1].replace("_", " "))
            + ". Artwork and layout are planned in advance; weather updates before the refresh at "
            + escape(weather)
            + ".</p>"
        )
        if daily["status"] == "failed":
            body += (
                '<p class="notice">Daily refresh preparation is delayed. The frame keeps '
                "its current picture until it is ready.</p>"
            )

        body += (
            '<div class="current-next">'
            + "".join(card(image, label) for label, image in ready)
            + "</div>"
        )
        if not ready:
            body += '<p class="empty-state">The next composition preview is being prepared.</p>'
        body += "</section>"
    history = [image for image in past if usable(image)]
    if upcoming:
        site = service.settings.config.site(
            service.store.frame(service.settings.config.public_frame_id)["site_id"]
        )
        body += (
            '<section class="public-compositions"><h2>Past compositions</h2>'
            '<p class="quiet">' + HISTORY_NOTE + "</p>"
        )
        if history:
            body += '<div class="current-next">'
            body += (
                "".join(card(image, reported_label(image, site.timezone)) for image in history[:2])
                + "</div>"
            )
            if len(history) > 2:
                body += (
                    '<details><summary>More past compositions</summary><div class="current-next">'
                )
                body += (
                    "".join(
                        card(image, reported_label(image, site.timezone)) for image in history[2:]
                    )
                    + "</div></details>"
                )
        else:
            body += '<p class="empty-state">No frame-confirmed past pictures are available yet.</p>'
        body += "</section>"
    return body


def install_routes(app, service):
    @app.get("/display/next-daily.jpg")
    def daily_composition_preview():
        _, upcoming, _ = public_records(service)
        chosen = upcoming.get("Daily refresh")
        if not chosen or not service.cache_path(chosen["preview_path"]).is_file():
            raise HTTPException(404, "Public daily composition unavailable")
        return FileResponse(
            service.cache_path(chosen["preview_path"]),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

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
