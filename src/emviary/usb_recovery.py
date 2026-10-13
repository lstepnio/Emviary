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
        or manifest["version"] != "v0.8.4"
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
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/manage/usb-recovery/cloud-settings/{identifier}")
    async def cloud_settings(identifier: str, request: Request):
        import asyncio

        from .recovery_nvs import build, local_password

        data = await checked_form(request)
        if data.get("replace_local_settings") != "yes":
            raise HTTPException(400, "Confirm replacing local settings before cloud restoration")

        def prepare():
            with preparation_lock(service.settings.data_dir):
                frame = service.store.frame(identifier)
                policy = FramePolicy.model_validate_json(frame["policy"])
                token_path = service.settings.data_dir / "provisioning" / (identifier + ".token")
                try:
                    previous_token = token_path.read_text()
                    token = previous_token.strip()
                except FileNotFoundError:
                    previous_token, token = None, ""
                identity = service.store.authenticate(token)
                renew_binding = not identity or identity["id"] != identifier
                if renew_binding:
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
                if renew_binding:
                    from .owner import write_private

                    write_private(token_path, token + "\n")
                    try:
                        service.store.restore_recovery_binding(frame, updated, token)
                    except Exception:
                        if token_path.read_text().strip() == token:
                            if previous_token is None:
                                token_path.unlink()
                            else:
                                write_private(token_path, previous_token)
                        raise
                elif updated != policy:
                    service.store.set_policy(
                        identifier, updated, expected_revision=frame["config_revision"]
                    )
            return {
                "frame_id": identifier,
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
        + '"><h2>Recover your frame</h2>'
        "<p>Connect your reTerminal E1002 to this laptop with a USB data cable. "
        "We’ll restore its firmware, retry if needed, and check its connection to Emviary. "
        "Use Chrome or Edge. Keep the cable connected until recovery finishes.</p>"
        '<ol class="recovery-steps" aria-label="Recovery progress">'
        '<li data-usb-step="prepare">Prepare</li><li data-usb-step="restore">Restore</li>'
        '<li data-usb-step="connect">Connect</li><li data-usb-step="finish">Check picture</li></ol>'
        '<ol aria-label="USB connection instructions">'
        "<li>Turn the frame’s power switch on and connect it to this laptop with a "
        "USB data cable. Close other apps using the frame’s USB connection.</li>"
        "<li>Choose <strong>Recover frame</strong> below. In the browser’s port picker, "
        "select <strong>USB Serial</strong> (its name may include <strong>usbserial</strong>, "
        "<strong>CH340</strong> or a <strong>COM</strong> number), then click "
        "<strong>Connect</strong>.</li>"
        "<li>Leave USB connected and do not press the frame’s buttons while writing. "
        "When prompted, check that the picture is visible and choose "
        "<strong>Yes, finish recovery</strong> before unplugging.</li></ol>"
        '<p class="quiet">No USB entry? Cancel the picker, reconnect the cable and try '
        "another data cable or USB port. Do not select Bluetooth or a debug console.</p>"
        '<div class="actions"><button type="button" data-usb-start disabled>'
        "Recover frame</button></div>"
        '<progress max="100" value="0" hidden aria-label="Firmware recovery progress"></progress>'
        '<p data-usb-status class="notice" role="status" aria-live="polite">'
        "Preparing recovery…</p><noscript>Enable JavaScript for USB recovery.</noscript>"
        '<img class="preview" width="800" height="480" data-usb-preview hidden '
        'alt="Artwork fetched by the recovered frame">'
        "<div data-usb-finish hidden><p>Does the picture appear and stay visible?</p>"
        '<div class="actions"><button type="button" data-usb-good>Yes, finish recovery</button>'
        '<button type="button" class="secondary" data-usb-not-yet>Not yet</button></div></div>'
        "<div data-usb-wake-panel hidden><p>Press the green wake button "
        "once, keeping USB connected.</p>"
        '<button type="button" class="secondary" data-usb-wake>I pressed the green '
        "button</button></div>"
        "<form data-usb-cloud hidden><h3>Restore settings from the cloud</h3>"
        "<p>If the saved Wi-Fi or local settings are damaged, we can replace them and reconnect "
        "this frame to its cloud artwork and special days. No setup "
        "network or import file is needed.</p>"
        '<label>Wi-Fi network<input name="ssid" list="usb-recovery-networks" maxlength="32" '
        'autocomplete="off" required></label><datalist id="usb-recovery-networks" '
        "data-usb-networks></datalist>"
        '<label>Wi-Fi password<input type="password" name="password" autocomplete="new-password">'
        '<span class="quiet">Leave blank to use a password already saved in Emviary. '
        "New networks are saved in this frame’s cloud settings.</span></label>"
        '<label class="check"><input type="checkbox" name="open_network">This network '
        "has no password</label>"
        '<label class="check"><input type="checkbox" name="replace_local_settings" required>'
        "Replace local Wi-Fi settings and saved images. Keep my cloud "
        "artwork and special days.</label>"
        '<button type="submit" class="secondary">Restore from cloud</button></form>'
        "<details hidden><summary>Local frame access after cloud restoration</summary>"
        "<p>The frame’s local management password is <code data-usb-local-password></code>. "
        "Keep it private. Cloud management uses your existing sign-in.</p></details>"
        '<p class="quiet" data-usb-speed></p>'
        "<details><summary>Other recovery options</summary>"
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
