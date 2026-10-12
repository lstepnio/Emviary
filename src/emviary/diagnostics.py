"""Bounded, owner-only device diagnostics carried by existing image requests."""

import base64
import json
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from typing import Literal
from zoneinfo import ZoneInfo

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

    ota_rollback: bool | None = None
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
    firmware_update_result: Literal["failed", "success", "retry_held"] | None = None
    firmware_update_version: str | None = Field(default=None, max_length=32)

    @field_validator("firmware_update_version")
    @classmethod
    def printable_version(cls, value):
        if value is not None and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Invalid firmware version")
        return value

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


def management_alerts(service, frame, now=None):
    """Read existing evidence only; a sleeping frame never needs an extra check-in."""
    from .settings import FramePolicy

    now = now or service.clock()
    site = service.settings.config.site(frame["site_id"])
    policy = FramePolicy.model_validate_json(frame["policy"])
    zone = ZoneInfo(site.timezone)
    local = now.astimezone(zone)
    wake = (
        datetime.fromisoformat(local.date().isoformat() + "T" + policy.wake_local_time)
        .replace(tzinfo=zone)
        .astimezone(UTC)
    )
    grace = timedelta(minutes=45)
    # Before today's grace expires, yesterday is the latest completed opportunity.
    if now < wake + grace:
        day = local.date() - timedelta(days=1)
        wake = datetime.fromisoformat(day.isoformat() + "T" + policy.wake_local_time)
        wake = wake.replace(tzinfo=zone).astimezone(UTC)
    alerts = []
    contact = datetime.fromisoformat(frame["last_contact"]) if frame["last_contact"] else None
    enrolled = datetime.fromisoformat(frame["created_at"])
    if enrolled <= wake and (contact is None or contact < wake):
        alerts.append(
            (
                "scheduled_refresh",
                "Daily connection missed",
                "The frame has not connected since its expected daily wake. "
                "Check its battery and Wi-Fi, then press the right white button.",
            )
        )

    if policy.weather_cues and site.providers.open_meteo.enabled:
        snapshot = service.store.snapshot(frame["site_id"], "open_meteo")
        payload = json.loads(snapshot["payload"]) if snapshot else {}
        stamp = payload.get("fetched_at")
        weather_age = timedelta(minutes=policy.weather_max_age_minutes)
        try:
            fetched = datetime.fromisoformat(stamp) if stamp else None
            expected_day = wake.astimezone(zone).date().isoformat()
            forecast_day = payload.get("local_date")
            # The daily forecast remains useful all day. Its age limit governs
            # preparation and delivery, not how long a sleeping panel may show it.
            forecast_wake = (
                (
                    datetime.fromisoformat(forecast_day + "T" + policy.wake_local_time)
                    .replace(tzinfo=zone)
                    .astimezone(UTC)
                )
                if forecast_day
                else wake
            )
            stale = (
                fetched is None
                or fetched.tzinfo is None
                or forecast_day not in {expected_day, local.date().isoformat()}
                or not (forecast_wake - weather_age < fetched <= now + timedelta(minutes=5))
            )
            # A rebuilt weather-free buffer is evidence that fresh weather was
            # unavailable for that preparation. An afternoon cache age alone is not.
            if not stale:
                for purpose in ("scheduled", "navigation"):
                    image = service.store.slot_image(frame["id"], purpose)
                    if not image or image["local_date"] != local.date().isoformat():
                        continue
                    manifest = json.loads(image["manifest"])
                    prepared = datetime.fromisoformat(
                        manifest.get("prepared_at", image["created_at"])
                    )
                    if (
                        not manifest.get("inputs", {}).get("open_meteo")
                        and fetched + weather_age <= prepared <= now
                    ):
                        stale = True
                        break
        except (TypeError, ValueError):
            stale = True
        if stale:
            alerts.append(
                (
                    "stale_weather",
                    "Forecast out of date" if stamp else "Forecast unavailable",
                    "A fresh forecast is unavailable. "
                    "New pictures can omit weather until it returns.",
                )
            )

    with service.store.connect() as db:
        job = db.execute(
            "SELECT status,finished_at FROM jobs WHERE frame_id=? "
            "ORDER BY local_date DESC,revision DESC LIMIT 1",
            (frame["id"],),
        ).fetchone()
    slot = service.store.slot_state(frame["id"], "scheduled")
    recent = now - timedelta(days=2)
    failed_job = (
        job
        and job["status"] == "failed"
        and job["finished_at"]
        and (recent <= datetime.fromisoformat(job["finished_at"]) <= now)
    )
    failed_slot = (
        slot
        and slot["error"]
        and slot["last_attempt_at"]
        and (recent <= datetime.fromisoformat(slot["last_attempt_at"]) <= now)
    )
    if failed_job or failed_slot:
        alerts.append(
            (
                "image_preparation",
                "Picture preparation failed",
                "The service could not prepare a new picture. "
                "The frame can keep its current picture. Try preparing again.",
            )
        )

    rows = service.store.device_samples(frame["id"])
    if rows and recent <= datetime.fromisoformat(rows[-1]["recorded_at"]) <= now:
        metrics = json.loads(rows[-1]["metrics"])
        result = metrics.get("firmware_update_result")
        if result in ("failed", "retry_held"):
            version = metrics.get("firmware_update_version")
            alerts.append(
                (
                    "firmware_update",
                    "Firmware update needs attention",
                    "The frame reported "
                    + (
                        "an interrupted update with automatic retries paused"
                        if result == "retry_held"
                        else "a failed firmware update"
                    )
                    + (" to " + version if version else "")
                    + ". Check local frame controls while it is awake.",
                )
            )
    return alerts


def management_alerts_section(service, frame, escape, now=None):
    alerts = management_alerts(service, frame, now)
    if not alerts:
        return ""
    return (
        '<div class="frame-alerts" aria-label="Frame alerts">'
        + "".join(
            '<div class="notice" role="status" data-alert="'
            + code
            + '"><strong>'
            + escape(title)
            + "</strong><p>"
            + escape(detail)
            + "</p></div>"
            for code, title, detail in alerts
        )
        + "</div>"
    )


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
