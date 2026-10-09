"""Bounded, owner-only device diagnostics carried by existing image requests."""

import base64
import json
from ipaddress import IPv4Address
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class SavedNetwork(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    ssid: str = Field(min_length=1, max_length=32)
    password_set: bool

    @field_validator("ssid")
    @classmethod
    def valid_ssid(cls, value):
        if len(value.encode("utf-8")) > 32 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Invalid network name")
        return value


class DeviceMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    ssid: str | None = Field(default=None, max_length=32)
    wifi_networks: list[SavedNetwork] | None = Field(default=None, max_length=5)
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

    @field_validator("wifi_networks")
    @classmethod
    def unique_networks(cls, value):
        if value is not None and len({n.ssid for n in value}) != len(value):
            raise ValueError("Duplicate network names")
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
    body = '<section class="card"><h3>Connectivity and refreshes</h3>'
    if not rows:
        return (
            body
            + '<p class="empty-state">Readings will appear after the frame connects.</p></section>'
        )

    from .ui import local_time as reported

    def refresh(m):
        labels = {"success": "Updated", "unchanged": "Already current", "failed": "Failed"}
        label = labels.get(m.get("previous_result"), "Not yet reported")
        duration = m.get("previous_total_ms")
        return label + (f" · {duration / 1000:.1f} s" if duration is not None else "")

    def connection(m):
        return f"{m['connect_ms'] / 1000:.1f} s" if "connect_ms" in m else "Not reported"

    latest = json.loads(rows[-1]["metrics"])
    metrics = (
        ("Wi-Fi", signal_label(latest.get("rssi_dbm")), latest.get("ssid", "")),
        ("Last completed refresh", refresh(latest), "Reported on the next connection"),
        ("Wi-Fi connection time", connection(latest), "Time to connect to the network"),
    )
    body += '<div class="metric-grid device-health-grid">'
    for label, value, detail in metrics:
        body += (
            '<div class="metric"><span class="metric-label">'
            + escape(label)
            + "</span><strong>"
            + escape(value)
            + '</strong><p class="quiet">'
            + escape(detail)
            + "</p></div>"
        )
    body += '</div><p class="quiet">Last connected: ' + escape(reported(rows[-1]["recorded_at"]))
    if rows[-1]["firmware"]:
        body += " · Firmware " + escape(rows[-1]["firmware"])
    body += ". Readings update when the frame connects.</p>"
    if latest.get("rssi_dbm", 0) < -70:
        body += (
            '<p class="notice">Weak Wi-Fi. Moving the frame closer to the router '
            "may improve reliability and battery life.</p>"
        )
    if latest.get("previous_result") == "failed":
        body += (
            '<p class="notice">The last refresh failed. '
            "Check Wi-Fi and try the next-image button.</p>"
        )
    body += (
        "<details><summary>Recent connections</summary>"
        '<div class="table-wrap"><table><caption>Newest first · Mountain time</caption>'
        "<tr><th>Connected</th><th>Wi-Fi</th><th>Connection time</th>"
        "<th>Completed refresh</th></tr>"
    )
    for row in reversed(rows[-30:]):
        m = json.loads(row["metrics"])
        values = [
            reported(row["recorded_at"]),
            signal_label(m.get("rssi_dbm")),
            connection(m),
            refresh(m),
        ]
        body += "<tr>" + "".join("<td>" + escape(v) + "</td>" for v in values) + "</tr>"
    return body + "</table></div></details></section>"


def saved_networks_section(store, frame_id, policy, escape):
    """Device-confirmed inventory is distinct from additive cloud-staged changes."""
    from .ui import local_time

    body = "<h3>Saved on the frame</h3>"
    for row in reversed(store.device_samples(frame_id)):
        metrics = json.loads(row["metrics"])
        if "wifi_networks" not in metrics:
            continue
        networks = metrics["wifi_networks"]
        body += (
            '<p class="quiet">'
            + str(len(networks))
            + " of 5 networks saved. Last reported: "
            + escape(local_time(row["recorded_at"]))
            + ". The list updates on each artwork fetch, including unchanged images.</p>"
            '<div class="table-wrap"><table><tr><th>Network</th><th>Security</th>'
            "<th>Status at last report</th></tr>"
        )
        for network in networks:
            status = "Connected" if network["ssid"] == metrics.get("ssid") else "Saved"
            if network["ssid"] in policy.get("wifi_forget_ssids", []):
                status += " · Removal pending"
            body += (
                "<tr>"
                + "".join(
                    "<td>" + escape(value) + "</td>"
                    for value in (
                        network["ssid"],
                        "Password saved" if network["password_set"] else "Open network",
                        status,
                    )
                )
                + "</tr>"
            )
        return body + "</table></div>"
    return body + (
        '<p class="empty-state">The frame has not reported its saved network list yet. '
        "Firmware v0.7.6 or later reports all networks on its next artwork fetch.</p>"
    )
