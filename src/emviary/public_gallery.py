"""Read-only composition previews for the configured public frame only."""

import json
from functools import partial
from html import escape
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.responses import FileResponse

from .compositions import composition_key
from .display_history import reported_label
from .showcase import framed_image


def catalog_keys(service):
    return {
        (art["id"], art["asset_sha256"])
        for art in service.settings.artworks
        if art.get("approved") and art.get("asset_sha256") and not art.get("event_only")
    }


def shareable(record, *, catalog):
    """Check upcoming and past compositions, including plans that predate public_display."""
    if not record or record.get("hidden"):
        return False
    try:
        plan = json.loads(record["manifest"])
    except (KeyError, ValueError, TypeError):
        return False
    if not isinstance(plan, dict) or plan.get("public_display", True) is not True:
        return False
    if (
        plan.get("special_day") is not None
        or plan.get("special_day_test")
        or plan.get("content_category") == "special_day"
    ):
        return False
    primary = plan.get("artwork")
    members = plan.get("artworks", [primary])
    if not isinstance(members, list) or not members:
        return False
    return all(
        isinstance(art, dict)
        and not art.get("event_only")
        and art.get("source_url") != "owner-upload"
        and isinstance(art.get("id"), str)
        and isinstance(art.get("asset_sha256"), str)
        and (art["id"], art["asset_sha256"]) in catalog
        for art in [primary, *members]
    )


def public_delivery(service):
    """Return the selected frame and its last delivered, visible preview."""
    identifier = service.settings.config.public_frame_id
    if not identifier:
        return None, None
    try:
        frame = service.store.frame(identifier)
    except ValueError:
        return None, None
    current = service.delivered_image(frame)
    if current and not current["hidden"] and service.cache_path(current["preview_path"]).is_file():
        return frame, current
    return frame, None


def public_records(service):
    frame, current = public_delivery(service)
    if not frame:
        return None, {}, []
    visible = partial(shareable, catalog=catalog_keys(service))
    daily = service.next_daily_refresh(frame)
    preview = daily["preview"]
    preview = {**preview, "preview_url": "/display/next-daily.jpg"} if visible(preview) else None
    navigation = service.store.active_image(frame)
    upcoming = {
        "Daily refresh": preview,
        "Next button": navigation if visible(navigation) else None,
    }
    past = service.display_history.past(
        frame["id"], current["id"] if current else None, 10, include=visible
    )
    return current, upcoming, past


def gallery_markup(service, records):
    _, upcoming, past = records

    def usable(record):
        return (
            record
            and not record.get("hidden")
            and service.cache_path(record["preview_path"]).is_file()
        )

    def card(record, label):
        url = record.get("preview_url") or f"/display/images/{record['id']}.jpg"
        return (
            '<figure><a href="'
            + escape(url, quote=True)
            + '">'
            + framed_image(url, label)
            + "</a><figcaption>"
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
        body += (
            '<p class="quiet">Next daily refresh: '
            + escape(wake)
            + " · "
            + escape(site.timezone.rsplit("/", 1)[-1].replace("_", " "))
            + "</p>"
        )
        if daily["status"] == "failed":
            body += '<p class="notice">Daily refresh preparation is delayed.</p>'

        body += (
            '<div class="current-next">'
            + "".join(card(image, label) for label, image in ready)
            + "</div>"
        )
        if not ready:
            body += '<p class="empty-state">No upcoming public preview is available.</p>'
        body += "</section>"
    history = [image for image in past if usable(image)]
    if upcoming:
        site = service.settings.config.site(
            service.store.frame(service.settings.config.public_frame_id)["site_id"]
        )
        body += '<section class="public-compositions"><h2>Past compositions</h2>'
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
    @app.get("/display.jpg")
    def public_display():
        _, current = public_delivery(service)
        if not current:
            raise HTTPException(404, "Public composition unavailable")
        return FileResponse(
            service.cache_path(current["preview_path"]),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

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
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
