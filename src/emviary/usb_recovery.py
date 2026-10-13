"""Authenticated, immutable E1002 USB recovery files; flashing stays on the laptop."""

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from .service import preparation_lock
from .settings import FramePolicy, WifiNetwork

ROOT = Path(__file__).with_name("recovery_assets")


@lru_cache(maxsize=1)
def recovery_manifest():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    if (
        manifest["board"] != "seeedstudio_reterminal_e1002"
        or manifest["chip"] != "ESP32-S3"
        or manifest["flash_size"] != "32MB"
        or manifest["version"] != "v0.8.10"
        or [p["address"] for p in manifest["parts"]] != [0, 0x8000, 0xF000, 0x20000]
    ):
        raise ValueError("Unexpected USB recovery target or layout")
    for part in manifest["parts"]:
        path = (ROOT / manifest["version"] / part["name"]).resolve()
        if not path.is_relative_to(ROOT.resolve()):
            raise ValueError("Recovery asset escaped its bundle")
        if (
            path.stat().st_size != part["size"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != part["sha256"]
        ):
            raise ValueError("Recovery file does not match its immutable manifest")
    return {
        **manifest,
        "parts": [
            {
                **part,
                "url": f"/manage/usb-recovery/{manifest['version']}/{part['name']}",
            }
            for part in manifest["parts"]
        ],
    }


def install_routes(app, require, service, checked_form):
    @app.get("/manage/usb-recovery/status/{identifier}")
    def status(identifier: str, request: Request, since: str = ""):
        require(request)
        frame = service.store.frame(identifier)
        policy = FramePolicy.model_validate_json(frame["policy"])
        now = datetime.now(UTC)
        cutoff = now
        if since:
            try:
                cutoff = datetime.fromisoformat(since)
                if cutoff.tzinfo is None or not now - timedelta(days=1) <= cutoff <= now:
                    raise ValueError
            except ValueError:
                raise HTTPException(400, "Start recovery again to check its progress") from None
        samples = service.store.device_samples(identifier)
        latest = samples[-1] if samples else None
        metrics = json.loads(latest["metrics"]) if latest else {}
        reported_ssid = next(
            (
                value
                for sample in reversed(samples)
                if (value := json.loads(sample["metrics"]).get("ssid"))
            ),
            "",
        )
        eligible_networks = [network for network in policy.wifi_networks or [] if network.password]
        restore_network = next(
            (network for network in eligible_networks if network.ssid == reported_ssid),
            eligible_networks[0] if eligible_networks else None,
        )
        connected = bool(
            since
            and latest
            and datetime.fromisoformat(latest["recorded_at"]) > cutoff
            and latest["firmware"] == recovery_manifest()["version"]
        )
        image = service.delivered_image(frame)
        available = image or service.store.active_image(frame)
        return JSONResponse(
            {
                "checked_at": now.isoformat(),
                "last_contact": latest["recorded_at"] if latest else None,
                "reported_firmware": latest["firmware"] if latest else None,
                "expected_firmware": recovery_manifest()["version"],
                "fresh_contact": bool(
                    since and latest and datetime.fromisoformat(latest["recorded_at"]) > cutoff
                ),
                "connected": connected,
                "cloud_ready": bool(available and service.cache_path(available["path"]).is_file()),
                "firmware": latest["firmware"] if connected else None,
                "preview_url": f"/manage/images/{image['id']}/preview"
                if connected and image
                else None,
                "network_names": [n.ssid for n in policy.wifi_networks or []],
                "suggested_network": metrics.get("ssid", ""),
                "automatic_restore_ssid": restore_network.ssid if restore_network else "",
                "can_restore_without_input": restore_network is not None,
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/manage/usb-recovery/cloud-settings/{identifier}")
    async def cloud_settings(identifier: str, request: Request):
        import asyncio

        from .owner import write_private
        from .recovery_nvs import build, local_password
        from .recovery_sessions import RecoverySessions, lease_guard

        data = await checked_form(request)
        if data.get("replace_local_settings") != "yes":
            raise HTTPException(400, "Confirm replacing local settings before cloud restoration")

        session_id = data.get("session_id", "")
        if not session_id:
            raise HTTPException(400, "Start a recovery session before restoring settings")
        sessions = RecoverySessions(service.store)

        def prepare():
            with preparation_lock(service.settings.data_dir):
                with service.store.connect() as db:
                    session = sessions._session(db, session_id, identifier)
                    lease_guard(db, identifier, session_id)
                    if session["lease_expires_at"] <= datetime.now(UTC).isoformat():
                        raise HTTPException(409, "Resume recovery before restoring settings")
                frame = service.store.frame(identifier)
                policy = FramePolicy.model_validate_json(frame["policy"])
                token_path = service.settings.data_dir / "provisioning" / (identifier + ".token")
                pending_path = token_path.with_name(
                    identifier + "." + session_id + ".pending.token"
                )
                pending_exists = pending_path.is_file()
                token = ""
                if pending_exists:
                    if pending_path.stat().st_size > 130:
                        raise HTTPException(409, "Resume the unfinished settings transfer")
                    token = pending_path.read_text().strip()
                    staged = sessions.authenticate(token, session_id, session["nonce"])
                    if not staged or staged["id"] != identifier:
                        active = service.store.authenticate(token)
                        if not active or active["id"] != identifier:
                            raise HTTPException(409, "Resume the unfinished settings transfer")
                else:
                    try:
                        token = token_path.read_text().strip()
                    except FileNotFoundError:
                        pass
                    identity = service.store.authenticate(token)
                    if not identity or identity["id"] != identifier:
                        token = secrets.token_urlsafe(32)
                networks = policy.wifi_networks or []
                ssid = data.get("ssid", "")
                saved = next((n for n in networks if n.ssid == ssid), None)
                password = data.get("password", "")
                if data.get("open_network") == "on":
                    password = ""
                elif not password and saved:
                    password = saved.password
                if not ssid or not password and not saved and data.get("open_network") != "on":
                    raise HTTPException(
                        400, "Enter the Wi-Fi network and password for this location"
                    )
                try:
                    chosen = WifiNetwork(ssid=ssid, password=password)
                except ValidationError:
                    raise HTTPException(400, "Check the Wi-Fi network name and password") from None
                networks = [chosen] + [n for n in networks if n.ssid != ssid]
                if len(networks) > 5:
                    raise HTTPException(
                        400,
                        "Five Wi-Fi networks are already saved. Use a saved network or "
                        "remove one in Settings.",
                    )
                updated = policy.model_copy(
                    update={
                        "wifi_networks": networks,
                        "wifi_forget_ssids": [n for n in policy.wifi_forget_ssids if n != ssid],
                    }
                )
                config = {
                    "firmware_timezone": updated.firmware_timezone,
                    "firmware_rotate_cron": updated.firmware_rotate_cron,
                    "wifi_networks": [n.model_dump() for n in networks],
                    "image_url": service.settings.config.public_base_url + "/v1/image",
                    "access_token": token,
                }
                try:
                    binary = build(config)
                except (RuntimeError, TimeoutError) as exc:
                    raise HTTPException(503, str(exc)) from None
                # Save the resumable candidate privately, never replace the active token file.
                if not pending_exists:
                    write_private(pending_path, token + "\n")
                try:
                    sessions.stage_binding(frame, updated, token, session_id)
                except Exception:
                    if not pending_exists:
                        pending_path.unlink(missing_ok=True)
                    raise
            return {
                "frame_id": identifier,
                "session_id": session_id,
                "config_revision": frame["config_revision"] + 1,
                "binding_pending": True,
                "address": 0x9000,
                "size": len(binary),
                "sha256": hashlib.sha256(binary).hexdigest(),
                "data": base64.b64encode(binary).decode(),
                "local_password": local_password(token),
            }

        payload = await asyncio.to_thread(prepare)
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get("/manage/usb-recovery/manifest")
    def manifest(request: Request):
        require(request)
        try:
            value = recovery_manifest()
        except (OSError, ValueError, KeyError):
            raise HTTPException(503, "Verified USB recovery bundle is unavailable") from None
        return JSONResponse(value, headers={"Cache-Control": "no-store"})

    @app.get("/manage/usb-recovery/assets/{name}")
    def script(name: str, request: Request):
        require(request)
        if name not in {"recovery.js", "recovery.js.LEGAL.txt"}:
            raise HTTPException(404, "Unknown recovery asset")
        return FileResponse(
            ROOT / name,
            media_type="text/javascript" if name.endswith(".js") else "text/plain",
            headers={"Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"},
        )

    @app.get("/manage/usb-recovery/{version}/{name}")
    def binary(version: str, name: str, request: Request):
        require(request)
        try:
            value = recovery_manifest()
        except (OSError, ValueError, KeyError):
            raise HTTPException(503, "Verified USB recovery bundle is unavailable") from None
        if version != value["version"] or name not in {p["name"] for p in value["parts"]}:
            raise HTTPException(404, "Unknown recovery file")
        return FileResponse(
            ROOT / version / name,
            media_type="application/octet-stream",
            headers={"Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"},
        )


def panel(frame):
    from .owner import escape

    return (
        '<section class="card" id="usb-recovery" data-usb-recovery data-frame="'
        + escape(frame)
        + '"><div class="recovery-heading"><h2>Recover your frame</h2>'
        "<p>We’ll check your frame first, then repair only what needs fixing. "
        "Damaged connection settings can be restored from Emviary. Keep USB connected.</p></div>"
        '<ol class="recovery-steps" aria-label="Recovery progress">'
        '<li data-usb-step="prepare"><span>1</span>Connect</li>'
        '<li data-usb-step="restore"><span>2</span>Check &amp; repair</li>'
        '<li data-usb-step="connect"><span>3</span>Reconnect</li>'
        '<li data-usb-step="finish"><span>4</span>Check picture</li></ol>'
        '<div class="recovery-stage" data-usb-stage>'
        '<span class="recovery-orb" data-usb-orb aria-hidden="true">↻</span>'
        "<div><h3 data-usb-heading>Getting ready</h3>"
        '<p data-usb-status role="status">Preparing everything your frame needs.</p></div></div>'
        '<progress max="100" value="0" hidden aria-label="Firmware recovery progress"></progress>'
        '<p class="quiet" data-usb-progress-label hidden></p>'
        '<div data-usb-intro class="recovery-intro">'
        '<ol aria-label="USB connection instructions">'
        "<li>Connect your frame to this laptop with a <strong>USB data cable</strong>.</li>"
        "<li>Turn the frame’s <strong>power switch on</strong>.</li>"
        "<li>Choose <strong>Check and recover</strong>. If asked, "
        "select <strong>USB Serial</strong> "
        "and click <strong>Connect</strong>.</li></ol>"
        '<p class="quiet">Use Chrome or Edge. Do not select Bluetooth or a debug console.</p></div>'
        '<div class="actions recovery-actions"><button type="button" data-usb-start disabled>'
        'Check and recover</button><button type="button" class="secondary" data-usb-cancel hidden>'
        "Stop checking</button></div>"
        "<noscript>Enable JavaScript to start recovery.</noscript>"
        '<img class="preview" width="800" height="480" data-usb-preview hidden '
        'alt="Artwork fetched by the recovered frame">'
        "<div data-usb-finish hidden><p>Does this picture appear and stay visible "
        "on your frame?</p>"
        '<div class="actions"><button type="button" data-usb-good>Yes, finish</button>'
        '<button type="button" class="secondary" data-usb-not-yet>No, help me</button></div></div>'
        "<div data-usb-wake-panel hidden><p></p>"
        '<button type="button" class="secondary" data-usb-wake>Continue recovery</button></div>'
        "<form data-usb-cloud hidden><h3>Restore settings from the cloud</h3>"
        "<p>Choose a saved network or enter new Wi-Fi details. Your artwork and special days "
        "stay in Emviary.</p>"
        '<label>Wi-Fi network<input name="ssid" list="usb-recovery-networks" maxlength="32" '
        'autocomplete="off" required></label><datalist id="usb-recovery-networks" '
        "data-usb-networks></datalist>"
        '<label>Wi-Fi password<input type="password" name="password" autocomplete="new-password">'
        '<span class="quiet">Leave blank to use a password already saved in Emviary. '
        "New networks are saved in this frame’s cloud settings.</span></label>"
        '<label class="check"><input type="checkbox" name="open_network">This network '
        "has no password</label>"
        '<label class="check"><input type="checkbox" name="replace_local_settings" required>'
        "Replace local Wi-Fi and connection settings. Keep my cloud "
        "artwork and special days.</label>"
        '<button type="submit" class="secondary">Restore from cloud</button></form>'
        "<details hidden><summary>Local frame access after cloud restoration</summary>"
        "<p>The frame’s local management password is <code data-usb-local-password></code>. "
        "Keep it private. Cloud management uses your existing sign-in.</p></details>"
        '<details class="recovery-details"><summary>Recovery details &amp; '
        "troubleshooting</summary>"
        '<p class="quiet" data-usb-speed></p><p class="quiet" data-usb-debug></p>'
        "<p>Make sure the power switch is on. Close other serial apps and try another data cable "
        "if USB cannot connect. A charging-only cable does not work.</p>"
        "<p>For older firmware or manual Wi-Fi setup, you can "
        '<a href="/manage/frames/' + escape(frame) + '/provision?import_file=true">'
        "download a private recovery import file</a> and follow the instructions below.</p>"
        "<p>Repair preserves your settings first. Cloud restoration replaces local settings only "
        "after you confirm. The installer stays on this laptop and checks each firmware file.</p>"
        '</details></section><script type="module" '
        'src="/manage/usb-recovery/assets/recovery.js"></script>'
    )
