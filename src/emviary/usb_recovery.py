"""Authenticated, immutable E1002 USB recovery files; flashing stays on the laptop."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).with_name("recovery_assets")


@lru_cache(maxsize=1)
def recovery_manifest():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    if (
        manifest["board"] != "seeedstudio_reterminal_e1002"
        or manifest["chip"] != "ESP32-S3"
        or manifest["flash_size"] != "32MB"
        or manifest["version"] != "v0.8.3"
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


def install_routes(app, require):
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
        '<section class="card" id="usb-recovery" data-usb-recovery>'
        "<h2>Restore firmware over USB</h2><p>Repair a reTerminal E1002 from this laptop, "
        "even when the frame cannot connect to Wi-Fi. Use Chrome or Edge and a USB data cable.</p>"
        '<ol><li><a href="/manage/frames/' + escape(frame) + '/provision?import_file=true">'
        "Download the private recovery import file</a> before starting. Keep it private.</li>"
        "<li>Connect the E1002 to your laptop. Close serial monitors or other flashing apps. "
        "Prepare the installer, then choose the frame’s USB port when prompted.</li>"
        "<li>Keep the cable connected and this tab open until writing and verification finish. "
        "If Wi-Fi setup appears afterward, follow the hotspot and import steps below.</li></ol>"
        '<p class="quiet">Installs Emviary v0.8.3, including its rollback bootloader and '
        "partition table. Normal repair preserves Wi-Fi and local settings on the Emviary "
        "partition layout. USB communication stays between this browser and the frame.</p>"
        '<label class="check"><input type="checkbox" data-usb-board>'
        "This USB device is a reTerminal E1002</label>"
        "<details><summary>Start fresh instead of repairing</summary>"
        '<label class="check"><input type="checkbox" data-usb-erase>'
        "Erase all local settings and saved images</label>"
        '<p class="quiet">Use if local settings or storage are corrupted, or if the frame '
        "has different firmware. You will need to reconnect Wi-Fi and import the recovery file. "
        "Cloud artwork, dates, and settings stay on the server.</p></details>"
        '<div class="actions"><button type="button" data-usb-prepare>Prepare USB installer</button>'
        '<button type="button" data-usb-install disabled>Connect and restore firmware'
        "</button></div>"
        '<progress max="100" value="0" hidden aria-label="Firmware recovery progress"></progress>'
        '<p data-usb-status class="notice" role="status" aria-live="polite">'
        "Loading USB recovery controls…</p><noscript>Enable JavaScript for USB recovery.</noscript>"
        "<details><summary>If the USB connection fails</summary><p>Try another data cable and "
        "USB port. Close other serial apps and browser tabs using the frame. A charging-only "
        "cable will not work. Make sure the power switch is on, press the green wake "
        "button once, and retry. For hardware troubleshooting, see the "
        '<a href="https://wiki.seeedstudio.com/getting_started_with_reterminal_e1002/" '
        'target="_blank" rel="noopener">Seeed E1002 guide</a>.</p>'
        "<p>If a write is interrupted, reconnect USB and run recovery "
        "again. Do not disconnect during writing.</p></details></section>"
        '<script type="module" src="/manage/usb-recovery/assets/recovery.js"></script>'
    )
