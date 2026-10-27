"""Bounded, owner-only device diagnostics carried by existing image requests."""

import base64
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .status_data import json_object, timestamp


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

    offline_mode: bool | None = None
    offline_image_id: int | None = Field(default=None, ge=0, le=2147483647)
    offline_cache_count: int | None = Field(default=None, ge=0, le=256)
    offline_cache_bytes: int | None = Field(default=None, ge=0, le=16777216)
    offline_rotations: int | None = Field(default=None, ge=0, le=4294967295)
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
    if not isinstance(header, str) or not header or len(header.encode()) > 2048:
        return None
    try:
        if header.startswith("b64:"):
            header = base64.b64decode(header[4:], validate=True).decode("utf-8")
        result = DeviceMetrics.model_validate_json(header).model_dump(exclude_none=True)
        return result or None
    except (ValidationError, ValueError):
        return None


def device_readings(store, frame_id):
    """Revalidate optional historical telemetry; leave stored evidence unchanged."""
    readings = []
    for row in store.device_samples(frame_id):
        if timestamp(row["recorded_at"]) is None:
            continue
        try:
            metrics = DeviceMetrics.model_validate_json(row["metrics"]).model_dump(
                exclude_none=True
            )
        except (ValidationError, ValueError, TypeError):
            continue
        readings.append({**row, "metrics": metrics})
    return sorted(readings, key=lambda row: timestamp(row["recorded_at"]))


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
    contact = timestamp(frame["last_contact"])
    enrolled = timestamp(frame["created_at"])
    if enrolled is not None and enrolled <= wake and (contact is None or contact < wake):
        alerts.append(
            (
                "scheduled_refresh",
                "Daily connection missed",
                "The frame has not connected since its expected daily wake. "
                "It may still be displaying cached artwork. "
                "Check its battery and Wi-Fi, then briefly press the green button to reconnect.",
            )
        )

    if policy.weather_cues and site.weather_enabled:
        schedule = service.daily_schedule(frame, local.date())
        before_preparation = now < schedule["prepare_at"]
        weather_age = timedelta(minutes=policy.weather_max_age_minutes)
        # A midnight navigation forecast need not yet satisfy a future daily wake.
        # Until preparation is due, yesterday's completed daily forecast is also
        # valid evidence for the sleeping panel. Never select a future day's cache.
        days = [local.date()]
        if before_preparation:
            days.append(local.date() - timedelta(days=1))
        stale, stamp, fetched = True, None, None
        for day in days:
            snapshot = service.store.snapshot(frame["site_id"], "open_meteo", day.isoformat())
            payload = json_object(snapshot["payload"]) if snapshot else {}
            stamp = payload.get("fetched_at") or stamp
            candidate = timestamp(payload.get("fetched_at"))
            lower = (
                now - weather_age
                if day == local.date() and before_preparation
                else service.daily_schedule(frame, day)["wake_at"] - weather_age
            )
            if (
                candidate is not None
                and payload.get("local_date") == day.isoformat()
                and lower < candidate <= now + timedelta(minutes=5)
            ):
                stale, fetched = False, candidate
                break
        if not stale:
            for purpose in ("scheduled", "navigation"):
                image = service.store.slot_image(frame["id"], purpose)
                if not image or image["local_date"] != local.date().isoformat():
                    continue
                manifest = json_object(image["manifest"])
                prepared = timestamp(manifest.get("prepared_at", image["created_at"]))
                inputs = manifest.get("inputs")
                if (
                    isinstance(inputs, dict)
                    and not inputs.get("open_meteo")
                    and prepared is not None
                    and fetched + weather_age <= prepared <= now
                ):
                    stale = True
                    break
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
        and (stamp := timestamp(job["finished_at"])) is not None
        and recent <= stamp <= now
    )
    failed_slot = (
        slot
        and slot["error"]
        and slot["last_attempt_at"]
        and (stamp := timestamp(slot["last_attempt_at"])) is not None
        and recent <= stamp <= now
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

    rows = device_readings(service.store, frame["id"])
    if rows and recent <= timestamp(rows[-1]["recorded_at"]) <= now:
        metrics = rows[-1]["metrics"]
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
    rows = device_readings(store, frame_id)
    body = '<section class="card"><h3>Connectivity and refreshes</h3>'
    if not rows:
        message = (
            "No readable diagnostic readings are available. Saved readings have not been changed."
            if store.device_samples(frame_id)
            else "Readings will appear after the frame connects."
        )
        return body + '<p class="empty-state">' + message + "</p></section>"

    from .ui import local_time as reported

    def refresh(m):
        labels = {"success": "Updated", "unchanged": "Already current", "failed": "Failed"}
        label = labels.get(m.get("previous_result"), "Not yet reported")
        duration = m.get("previous_total_ms")
        return label + (f" · {duration / 1000:.1f} s" if duration is not None else "")

    def connection(m):
        return f"{m['connect_ms'] / 1000:.1f} s" if "connect_ms" in m else "Not reported"

    latest = rows[-1]["metrics"]
    metrics = (
        ("Wi-Fi", signal_label(latest.get("rssi_dbm")), latest.get("ssid", "")),
        ("Last completed refresh", refresh(latest), "Reported on the next connection"),
        ("Wi-Fi connection time", connection(latest), "Time to connect to the network"),
    )
    if "offline_cache_count" in latest:
        cache_bytes = latest.get("offline_cache_bytes", 0)
        mode = "Cached artwork" if latest.get("offline_mode") else "Cloud artwork"
        rotations = latest.get("offline_rotations", 0)
        metrics += (
            (
                "Offline library",
                f"{latest['offline_cache_count']} pictures · {cache_bytes / 1048576:.2f} MiB",
                f"Last reported: {mode}. {rotations} offline rotations. "
                "Updates on the next connection.",
            ),
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
            '<p class="notice">The last reported refresh failed. '
            "Cached pictures may still work. Check Wi-Fi and briefly press the green "
            "button to reconnect.</p>"
        )
    body += (
        "<details><summary>Recent connections</summary>"
        '<div class="table-wrap"><table><caption>Newest first · Mountain time</caption>'
        "<tr><th>Connected</th><th>Wi-Fi</th><th>Connection time</th>"
        "<th>Completed refresh</th></tr>"
    )
    for row in reversed(rows[-30:]):
        m = row["metrics"]
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
    for row in reversed(device_readings(store, frame_id)):
        metrics = row["metrics"]
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


def weather_sources_section(service, site, escape, format_time):
    """Read-only provenance; management page loads never call weather services."""
    now = service.clock()
    day = now.astimezone(ZoneInfo(site.timezone)).date().isoformat()
    body = "<details><summary>Weather source status</summary><ul>"
    for key, label, enabled in (
        ("open_meteo", "Open-Meteo", site.providers.open_meteo.enabled),
        ("nws", "National Weather Service", site.providers.nws.enabled),
    ):
        record = service.store.snapshot(site.id, "weather_" + key, day)
        payload = json_object(record["payload"]) if record else {}
        fetched = timestamp(payload.get("fetched_at"))
        failure = service.store.snapshot(site.id, "weather_" + key + "_failure", day)
        failed = json_object(failure["payload"]) if failure else {}
        attempted = timestamp(failed.get("attempted_at"))
        state = "Off" if not enabled else "Awaiting the next preparation"
        if enabled and fetched is not None:
            state = "Last received " + format_time(fetched.isoformat())
            issued = timestamp(payload.get("issued_at"))
            if issued is not None:
                state += "; forecast issued " + format_time(issued.isoformat())
        if (
            enabled
            and attempted is not None
            and attempted <= now
            and (fetched is None or attempted > fetched)
        ):
            state = "Last request failed; retrying during background preparation"
        body += "<li><strong>" + label + "</strong>: " + escape(state) + "</li>"
    record = service.store.snapshot(site.id, "open_meteo", day)
    payload = json_object(record["payload"]) if record else {}
    agreement = payload.get("agreement")
    note = {
        "agreement": "Both sources agree on conditions. Temperatures use their median.",
        "single_source": "One source is available. Its forecast is used independently.",
        "disagreement": "Sources differ. Local NWS conditions take precedence; temperatures "
        "are blended only when within 6°C.",
    }.get(agreement)
    body += "</ul>"
    if note:
        body += '<p class="quiet">' + escape(note) + "</p>"
    return (
        body + '<p class="quiet">Weather is fetched in the background. Missing or invalid '
        "forecasts are omitted from new pictures; the artwork remains available.</p></details>"
    )
