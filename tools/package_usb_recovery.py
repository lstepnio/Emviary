"""Copy a verified published E1002 build into the self-hosted browser recovery bundle."""

import argparse
import hashlib
import json
from pathlib import Path


def package(source, output, expected_version, build_url):
    source, output = Path(source).resolve(), Path(output)
    release = json.loads((source / "firmware-manifest.json").read_text())
    recovery = release["recovery"]
    if (
        release["version"] != expected_version
        or release["board"] != "seeedstudio_reterminal_e1002"
        or recovery["chip"] != "esp32s3"
        or recovery["flash_settings"]
        != {"flash_mode": "dio", "flash_size": "32MB", "flash_freq": "80m"}
    ):
        raise ValueError("Not the expected published E1002 build")
    files = recovery["files"]
    names = ["bootloader.bin", "partition-table.bin", "ota-data.bin", "application.bin"]
    addresses, limits = [0, 0x8000, 0xF000, 0x20000], [0x8000, 0x1000, 0x2000, 0x380000]
    if [f["address"] for f in files] != addresses:
        raise ValueError("Unexpected E1002 flash layout")
    blobs, parts = [], []
    for entry, name, address, limit in zip(files, names, addresses, limits, strict=True):
        path = (source / entry["asset"]).resolve()
        if not path.is_relative_to(source):
            raise ValueError("Recovery asset escaped the release directory")
        data = path.read_bytes()
        if not 0 < len(data) <= limit or len(data) != entry["size"]:
            raise ValueError("Invalid recovery file size")
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry["sha256"]:
            raise ValueError("Recovery file hash differs from its published manifest")
        blobs.append(data)
        parts.append({"name": name, "address": address, "size": len(data), "sha256": digest})
    if blobs[2] != b"\xff" * 8192:
        raise ValueError("Initial OTA selector must be blank 8 KiB")
    for image in (blobs[0], blobs[3]):
        if image[0] != 0xE9 or image[2:4] != bytes([2, 0x5F]):
            raise ValueError("Firmware header does not match DIO / 80 MHz / 32 MB")
    if parts[0]["sha256"] != release["bootloader_sha256"]:
        raise ValueError("Bootloader must match this application release")
    if parts[3]["sha256"] != release["sha256"]:
        raise ValueError("Application must match its published OTA asset")
    version = release["version"]
    target = output / version
    target.mkdir(parents=True, exist_ok=True)
    for name, data in zip(names, blobs, strict=True):
        (target / name).write_bytes(data)
    manifest = {
        "version": version,
        "board": release["board"],
        "chip": "ESP32-S3",
        "flash_size": "32MB",
        "flash_mode": "dio",
        "flash_freq": "80m",
        "commit": release["commit"],
        "source_release": "https://github.com/lstepnio/Emviary-firmware/releases/tag/" + version,
        "source_build": build_url,
        "parts": parts,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--build-url", required=True)
    parser.add_argument("--output", type=Path, default=Path("src/emviary/recovery_assets"))
    args = parser.parse_args()
    result = package(args.source, args.output, args.version, args.build_url)
    print("Verified and packaged " + result["version"] + " E1002 USB recovery parts")
