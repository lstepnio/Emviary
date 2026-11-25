"""Authenticated device delivery and owner gift preparation routes."""

import asyncio
import json
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from .diagnostics import parse_metrics
from .showcase import framed_image
from .store import RevisionConflict, stable_json
from .trusted_network import record_frame_network
from .ui import local_time

LABELS = {
    "draft": "Preview ready",
    "armed": "Waiting for the frame",
    "ready": "Welcome loaded",
    "wrap_pending": "Finishing gift setup",
    "wrapped": "Ready to wrap",
    "opened": "Frame reported gift opened",
    "failed": "Gift needs attention",
    "cancelled": "Cancellation requested",
    "cancelled_done": "Gift mode ended",
}


def observe_contact(service, request, frame, metrics):
    raw = request.headers.get("x-battery-percentage", "")
    percent = int(raw) if raw.isdecimal() and len(raw) <= 3 and int(raw) <= 100 else None
    raw_voltage = request.headers.get("x-battery-voltage", "")
    try:
        voltage = float(raw_voltage)
        voltage = voltage / 1000 if 1000 <= voltage <= 6000 else None
    except ValueError:
        voltage = None

    def flag(name):
        return {"0": False, "1": True, "true": True, "false": False}.get(
            request.headers.get(name, "").lower()
        )

    service.store.telemetry(
        frame["id"],
        percent,
        request.headers.get("x-firmware-version", "")[:80] or None,
        frame.get("last_client_etag", ""),
        frame.get("last_served_etag", ""),
        voltage,
        flag("x-battery-charging"),
        flag("x-usb-connected"),
    )
    service.store.device_sample(
        frame["id"], metrics, request.headers.get("x-firmware-version", "")[:80]
    )


def install_device_routes(app, service, authenticated, check_geometry):
    @app.get("/v1/gift")
    def gift_manifest(request: Request):
        frame = authenticated(request, service)
        check_geometry(request, frame)
        record_frame_network(request, service, frame)
        metrics = parse_metrics(request.headers.get("x-frame-metrics"))
        service.gifts.observe(frame["id"], metrics)
        observe_contact(service, request, frame, metrics)
        try:
            value = service.gifts.payload(frame["id"])
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from None
        return JSONResponse(value, headers={"Cache-Control": "private, no-store"})

    @app.get("/v1/gift/{identifier}/{part}")
    def gift_asset(identifier: str, part: str, request: Request):
        frame = authenticated(request, service)
        check_geometry(request, frame)
        try:
            packet = service.gifts.get(frame["id"], identifier)
            if packet["status"] not in {"armed", "ready", "failed", "wrap_pending", "wrapped"}:
                raise ValueError("Gift package is not armed")
            path = service.gifts.path(packet, part)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None
        return FileResponse(
            path,
            media_type="application/octet-stream",
            headers={"Cache-Control": "private, no-store"},
        )


def image_control_response(service, request, frame, metrics):
    service.gifts.observe(frame["id"], metrics)
    if request.headers.get("x-emviary-gift-version") != "1":
        return None
    try:
        value = service.gifts.payload(frame["id"])
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from None
    if value["state"] in {"none", "cancelled"}:
        return None
    observe_contact(service, request, frame, metrics)
    # Firmware consumes this control before its ordinary 304 path. No ordinary
    # image is selected, delivered, or counted as displayed by this response.
    return Response(
        status_code=304,
        headers={"X-Emviary-Gift": stable_json(value), "Cache-Control": "private, no-store"},
    )


def panel(service, frame_id, csrf, escape, hidden, draft_values=None, error=None):
    packet = service.gifts.current(frame_id)
    values = (
        json.loads(packet["values_json"])
        if packet
        else {
            "heading": "For my love, Emily.",
            "message": "A little nature, every day.",
            "signature": "Love, Luke",
            "first_image_id": None,
        }
    )
    if draft_values:
        values.update(
            {k: draft_values[k] for k in ("heading", "message", "signature") if k in draft_values}
        )
        try:
            values["first_image_id"] = int(draft_values.get("first_image_id", ""))
        except ValueError:
            values["first_image_id"] = None
    url = "/manage/frames/" + quote(frame_id, safe="") + "/gift"
    state = packet["status"] if packet else "none"
    body = (
        '<section class="card gift-panel" id="gift-welcome" data-gift-state="'
        + escape(state)
        + '" data-gift-id="'
        + (packet["id"] if packet else "")
        + '" data-gift-status-url="'
        + url
        + '/status"><h2>Gift welcome</h2>'
    )
    if state in {"none", "draft", "cancelled_done", "opened"}:
        body += (
            "<p>Choose the welcome and first picture Emily will see when she opens her gift.</p>"
        )
    if error:
        body += '<p class="error" data-request-error role="alert">' + escape(error) + "</p>"
    if not service.gifts.capable(frame_id):
        body += (
            '<p class="notice">You can preview now. Before showing the welcome, '
            "update the frame to gift-capable firmware and let it check in.</p>"
        )
    active = packet and packet["status"] in {"armed", "ready", "failed", "wrap_pending", "wrapped"}
    if packet:
        body += (
            '<div class="gift-status" role="status"><strong>'
            + escape(LABELS[packet["status"]])
            + "</strong>"
        )
        if packet["reported_at"]:
            body += (
                '<span class="quiet">Last device report: '
                + escape(local_time(packet["reported_at"]))
                + "</span>"
            )
        if packet["error"]:
            body += "<p>" + escape(packet["error"]) + "</p>"
        body += (
            '</div><p><a href="/manage/appearance?frame='
            + quote(frame_id, safe="")
            + '#gift-welcome">Refresh status</a></p><div class="gift-previews">'
        )
        for part, title in (("welcome", "Welcome"), ("first", "First composition")):
            body += (
                "<figure><h3>"
                + title
                + "</h3>"
                + framed_image(f"{url}/{packet['id']}/preview/{part}", title + " on the frame")
                + "</figure>"
            )
        body += (
            '</div><p class="quiet">Prepared e-ink previews. Check the actual screen '
            "before wrapping.</p>"
        )
        if packet["status"] == "draft":
            body += '<form method="post" action="' + url + '/arm">' + hidden(csrf)
            body += '<input type="hidden" name="gift_id" value="' + packet["id"] + '">'
            body += (
                "<button"
                + ("" if service.gifts.capable(frame_id) else " disabled")
                + ">Show welcome on frame</button></form>"
            )
        if active:
            if packet["status"] == "ready":
                body += (
                    "<p>The welcome and first picture are saved on the frame. Check the actual "
                    "welcome before the final step.</p>"
                )
                if service.gifts.wrap_capable(frame_id):
                    body += (
                        '<form method="post" action="'
                        + url
                        + '/wrap">'
                        + hidden(csrf)
                        + '<input type="hidden" name="gift_id" value="'
                        + packet["id"]
                        + '">'
                        + '<label class="check"><input type="checkbox" name="welcome_confirmed" '
                        "required>I can see the welcome on the frame.</label>"
                        "<button>Ready to wrap</button></form>"
                    )
                else:
                    body += (
                        '<p class="notice">Update the frame for power-on reveal '
                        "before wrapping.</p>"
                    )
            elif packet["status"] == "wrap_pending":
                body += (
                    "<p>Keep the frame on while it finishes setup. If it has gone to sleep, "
                    "press green once. Wait for “Ready to wrap” before switching it off.</p>"
                )
            elif packet["status"] == "wrapped":
                body += (
                    "<p>The frame confirmed it is ready. Charge it if needed, then "
                    "switch it off and wrap it.</p><p><strong>The next power-on reveals "
                    "the first picture automatically, even offline.</strong> Keep it off "
                    "until the gift is opened. A software restart or timer wake "
                    "preserves the welcome.</p>"
                )
            elif packet["status"] == "failed":
                body += (
                    "<p>The frame could not finish gift preparation. Check the screen before "
                    "retrying, or cancel gift setup below.</p>"
                )
            else:
                body += (
                    "<p>Press the right white button once while online to load both pictures "
                    "and show the welcome. Then confirm the actual screen "
                    "and choose Ready to wrap. "
                    "Do not switch it off until setup is confirmed.</p>"
                )
            body += '<form method="post" action="' + url + '/cancel">' + hidden(csrf)
            body += (
                '<input type="hidden" name="gift_id" value="'
                + packet["id"]
                + '"><input type="hidden" name="expected_state" value="'
                + escape(state)
                + '">'
            )
            if state in {"wrap_pending", "wrapped"}:
                body += (
                    '<label class="check"><input type="checkbox" name="cancel_confirmed" required>'
                    "I want to cancel the next power-on reveal.</label>"
                )
            body += '<button class="secondary">Cancel gift setup</button></form>'
        elif packet["status"] == "cancelled":
            body += (
                "<p>Normal artwork resumes on the next online wake. An offline "
                "frame keeps its welcome until it receives the cancellation or "
                "the right white button reveals the first picture.</p>"
            )
        elif packet["status"] == "cancelled_done":
            body += "<p>The frame received the cancellation. Normal artwork is available again.</p>"
        elif packet["status"] == "opened":
            body += (
                "<p>The frame reported the reveal. It may have happened offline "
                "before this report arrived. Prepare a new package below to "
                "show the welcome again.</p>"
            )
    if not active and (not packet or packet["status"] != "cancelled"):
        body += (
            "<details"
            + ("" if packet else " open")
            + "><summary>"
            + ("Edit and preview a new welcome" if packet else "Prepare your gift")
            + "</summary>"
        )
        body += '<form method="post" action="' + url + '/prepare">' + hidden(csrf)
        for key, label, maximum in (
            ("heading", "Dedication", 40),
            ("message", "Message", 80),
            ("signature", "Signature", 30),
        ):
            body += (
                "<label>"
                + label
                + '<input name="'
                + key
                + '" required maxlength="'
                + str(maximum)
                + '" value="'
                + escape(values[key])
                + '"></label>'
            )
        body += (
            '<label>First composition<select name="first_image_id" '
            'required><option value="">Choose a picture</option>'
        )
        for image in service.gifts.sources(frame_id):
            plan = json.loads(image["manifest"])
            label = ", ".join(a["common_name"] for a in plan.get("artworks", [plan["artwork"]]))
            selected = " selected" if image["id"] == values.get("first_image_id") else ""
            body += (
                '<option value="'
                + str(image["id"])
                + '"'
                + selected
                + ">"
                + escape(label + " · " + image["local_date"])
                + "</option>"
            )
        body += (
            '</select></label><p class="quiet">The chosen composition is saved '
            "separately, with weather removed so it stays appropriate while "
            "wrapped. Preparing does not change the current frame, calendar or "
            "daily schedule.</p><button>Prepare gift "
            "preview</button></form></details>"
        )
    return body + "</section>"


def install_owner_routes(app, service, require, checked_form, escape, page):
    from .owner import hidden

    @app.post("/manage/frames/{frame_id}/gift/{action}")
    async def gift_action(frame_id: str, action: str, request: Request):
        data = await checked_form(request)
        try:
            service.store.frame(frame_id)
            if action == "prepare":
                await asyncio.to_thread(service.gifts.prepare, frame_id, data)
            elif action in {"arm", "wrap", "cancel"}:
                await asyncio.to_thread(
                    service.gifts.action,
                    frame_id,
                    data.get("gift_id", ""),
                    action,
                    data.get("welcome_confirmed") == "on",
                    expected_state=data.get("expected_state"),
                    cancel_confirmed=data.get("cancel_confirmed") == "on",
                )
            else:
                raise HTTPException(404, "Unknown gift action")
        except (RevisionConflict, ValueError, RuntimeError, OSError) as exc:
            if not any(f["id"] == frame_id for f in service.store.frames()):
                raise HTTPException(404, "Unknown frame") from None
            auth = require(request)
            body = panel(
                service,
                frame_id,
                auth["csrf"],
                escape,
                hidden,
                data if action == "prepare" else None,
                "Gift storage is unavailable. Please retry."
                if isinstance(exc, OSError)
                else str(exc),
            )
            response = page("Gift welcome", body, active="appearance", frame=frame_id)
            response.status_code = (
                503
                if isinstance(exc, OSError)
                else 409
                if isinstance(exc, (RevisionConflict, RuntimeError))
                else 400
            )
            return response
        return RedirectResponse(
            "/manage/appearance?frame=" + quote(frame_id, safe="") + "#gift-welcome",
            status_code=303,
        )

    @app.get("/manage/frames/{frame_id}/gift/status")
    def gift_status(frame_id: str, request: Request):
        auth = require(request)
        try:
            service.store.frame(frame_id)
        except ValueError:
            raise HTTPException(404, "Unknown frame") from None
        packet = service.gifts.current(frame_id)
        return JSONResponse(
            {
                "state": packet["status"] if packet else "none",
                "html": panel(service, frame_id, auth["csrf"], escape, hidden),
            },
            headers={"Cache-Control": "private, no-store"},
        )

    @app.get("/manage/frames/{frame_id}/gift/{identifier}/preview/{part}")
    def gift_preview(frame_id: str, identifier: str, part: str, request: Request):
        require(request)
        try:
            packet = service.gifts.get(frame_id, identifier)
            path = service.gifts.path(packet, part, preview=True)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None
        return FileResponse(
            path, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"}
        )
