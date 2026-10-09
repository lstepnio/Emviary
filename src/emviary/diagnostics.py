"""Bounded, owner-only device diagnostics carried by existing image requests."""

import base64
import json
from ipaddress import IPv4Address
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class DeviceMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    ssid: str | None = Field(default=None, max_length=32)
    rssi_dbm: int | None = Field(default=None, ge=-127, le=0)
    channel: int | None = Field(default=None, ge=1, le=14)
    local_ip: str | None = Field(default=None, max_length=15)
    connect_ms: int | None = Field(default=None, ge=0, le=3600000)
    disconnects: int | None = Field(default=None, ge=0, le=2147483647)
    disconnect_reason: int | None = Field(default=None, ge=0, le=255)
    uptime_ms: int | None = Field(default=None, ge=0, le=9007199254740991)
    boot_count: int | None = Field(default=None, ge=0, le=4294967295)
    wake_cause: int | None = Field(default=None, ge=0, le=16)
    reset_reason: int | None = Field(default=None, ge=0, le=32)
    free_heap: int | None = Field(default=None, ge=0, le=67108864)
    min_free_heap: int | None = Field(default=None, ge=0, le=67108864)
    previous_result: Literal["success", "unchanged", "failed"] | None = None
    previous_total_ms: int | None = Field(default=None, ge=0, le=3600000)
    previous_download_ms: int | None = Field(default=None, ge=0, le=3600000)
    previous_bytes: int | None = Field(default=None, ge=0, le=33554432)
    previous_http_status: int | None = Field(default=None, ge=0, le=599)
    previous_attempts: int | None = Field(default=None, ge=0, le=3)

    @field_validator("ssid")
    @classmethod
    def printable_network(cls, value):
        if value is not None and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Control characters are not a network name")
        return value

    @field_validator("local_ip")
    @classmethod
    def valid_address(cls, value):
        return str(IPv4Address(value)) if value is not None else None


def parse_metrics(header):
    if not header or len(header.encode()) > 2048:
        return None
    try:
        if header.startswith("b64:"):
            header = base64.b64decode(header[4:], validate=True).decode("utf-8")
        result = DeviceMetrics.model_validate_json(header).model_dump(exclude_none=True)
        return result or None
    except (ValidationError, ValueError):
        return None


def signal_label(value):
    if value is None:
        return "Not reported"
    quality = "Strong" if value >= -60 else "Good" if value >= -70 else "Weak"
    return f"{quality} · {value} dBm"


def diagnostics_section(store, frame_id, escape):
    rows = store.device_samples(frame_id)
    body = '<section class="card"><h3>Connectivity and device health</h3>'
    if not rows:
        return body + '<p class="empty-state">Waiting for device diagnostics.</p></section>'
    latest = json.loads(rows[-1]["metrics"])
    wake_names = {
        0: "Cold boot or reset",
        1: "Scheduled",
        2: "Green button",
        3: "Previous button",
        4: "Next button",
        5: "Other GPIO",
    }
    result = latest.get("previous_result", "Not reported")
    duration = latest.get("previous_total_ms")
    metrics = (
        ("Firmware", rows[-1]["firmware"] or "Not reported"),
        ("Wake reason", wake_names.get(latest.get("wake_cause"), "Not reported")),
        ("Wi-Fi signal", signal_label(latest.get("rssi_dbm"))),
        ("Network", latest.get("ssid", "Not reported")),
        ("Local address", latest.get("local_ip", "Not reported")),
        ("Channel", latest.get("channel", "Not reported")),
        (
            "Connection time",
            f"{latest['connect_ms'] / 1000:.1f} s" if "connect_ms" in latest else "Not reported",
        ),
        (
            "Previous refresh",
            result + (f" · {duration / 1000:.1f} s" if duration is not None else ""),
        ),
        (
            "Free internal memory",
            f"{latest['free_heap'] / 1024:.0f} KiB" if "free_heap" in latest else "Not reported",
        ),
    )
    body += '<div class="metric-grid">'
    for label, value in metrics:
        body += (
            '<div class="metric"><span class="metric-label">'
            + escape(label)
            + "</span><strong>"
            + escape(str(value))
            + "</strong></div>"
        )
    body += '</div><p class="quiet">Last reported: ' + escape(rows[-1]["recorded_at"]) + ". "
    body += (
        "Network and memory readings describe the request. Refresh results describe the "
        "previous completed attempt and arrive on the next image request. A sleeping frame "
        "does not send live readings. Up to 2,000 requests are retained for 90 days.</p>"
    )
    if latest.get("rssi_dbm", 0) < -70:
        body += '<p class="notice">Weak Wi-Fi may increase connection time and battery use.</p>'
    if result == "failed":
        body += '<p class="notice">The previous image attempt failed. Check the history below.</p>'
    body += (
        "<details><summary>Recent device readings</summary>"
        '<div class="table-wrap"><table><caption>Newest first; timestamps in UTC</caption>'
        "<tr><th>Received</th><th>Signal</th><th>Connect</th><th>Previous refresh</th>"
        "<th>Network / channel</th><th>Download</th><th>HTTP / tries</th><th>Memory low</th>"
        "<th>Wake / reset</th><th>Disconnects / reason</th></tr>"
    )
    for row in reversed(rows[-60:]):
        m = json.loads(row["metrics"])

        def seconds(key):
            return f"{m[key] / 1000:.1f} s" if key in m else "Unknown"

        values = [
            row["recorded_at"],
            signal_label(m.get("rssi_dbm")),
            seconds("connect_ms"),
            m.get("previous_result", "Unknown") + " / " + seconds("previous_total_ms"),
            f"{m.get('ssid', 'Unknown')} / {m.get('channel', '?')}",
            seconds("previous_download_ms") + " / " + str(m.get("previous_bytes", "?")) + " B",
            f"{m.get('previous_http_status', '?')} / {m.get('previous_attempts', '?')}",
            f"{m['min_free_heap'] / 1024:.0f} KiB" if "min_free_heap" in m else "Unknown",
            f"{m.get('wake_cause', '?')} / {m.get('reset_reason', '?')}",
            f"{m.get('disconnects', '?')} / {m.get('disconnect_reason', '?')}",
        ]
        body += "<tr>" + "".join("<td>" + escape(str(v)) + "</td>" for v in values) + "</tr>"
    return body + "</table></div></details></section>"
