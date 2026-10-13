"""Generate fresh E1002 settings in an isolated worker, never a persistent file."""

import hashlib
import json
import subprocess
import sys
import threading
from io import BytesIO

WORKER = threading.BoundedSemaphore(1)


def local_password(token):
    return hashlib.sha256(("emviary-usb-local-v1:" + token).encode()).hexdigest()[:24]


def generate(config):
    """Import Espressif's generator only in the short-lived recovery subprocess."""
    from esp_idf_nvs_partition_gen.nvs_partition_gen import NVS, Page

    output = BytesIO()
    with NVS(output, 0x5000, Page.VERSION2) as nvs:  # Last 4 KiB reserved: exactly 0x6000 total.
        nvs.write_namespace("photoframe")
        fields = {
            "device_name": "Emviary",
            "timezone": config["firmware_timezone"],
            "rotate_cron": "\n".join(config["firmware_rotate_cron"]),
            "image_url": config["image_url"],
            "access_token": config["access_token"],
            "http_password": local_password(config["access_token"]),
            "wifi_networks": json.dumps(config["wifi_networks"], separators=(",", ":")),
            "wifi_ssid": config["wifi_networks"][0]["ssid"],
            "wifi_pass": config["wifi_networks"][0]["password"],
        }
        for key, value in fields.items():
            nvs.write_entry(key, value, "string")
        for key, value in {
            "auto_rotate": 1,
            "rotation_mode": 1,
            "deep_sleep": 1,
            "debug_log": 0,
            "disp_orient": 0,
        }.items():
            nvs.write_entry(key, value, "u8")
    data = output.getvalue()
    if len(data) != 0x6000 or data[-4096:] != b"\xff" * 4096:
        raise ValueError("Incorrect E1002 NVS geometry")
    return data


def build(config):
    if not WORKER.acquire(blocking=False):
        raise RuntimeError("Another cloud recovery is preparing. Try again shortly.")
    try:
        process = subprocess.run(
            [sys.executable, "-m", "emviary.recovery_nvs"],
            input=json.dumps(config).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
        if process.returncode != 0 or len(process.stdout) != 0x6000:
            raise RuntimeError("Cloud recovery settings could not be prepared. Try again.")
        return process.stdout
    except subprocess.TimeoutExpired:
        raise RuntimeError("Cloud recovery preparation timed out. Try again.") from None
    finally:
        WORKER.release()


if __name__ == "__main__":
    try:
        result = generate(json.loads(sys.stdin.buffer.read(16384)))
        sys.stdout.buffer.write(result)
    except Exception:
        sys.exit(1)  # Never include passwords or token-bearing payloads in diagnostics.
