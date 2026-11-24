"""Battery history and deliberately conservative discharge estimates for the owner UI."""

import math
from datetime import UTC, datetime
from statistics import median

from fastapi import HTTPException, Request

from .status_data import timestamp
from .ui import local_time

LOW_PERCENT = 20
FORECAST_DAYS = 7


def parse_time(value):
    return datetime.fromisoformat(value).astimezone(UTC)


def battery_readings(samples):
    readings = []
    for sample in samples:
        if timestamp(sample.get("recorded_at")) is None:
            continue
        percent = sample.get("percent")
        if type(percent) is not int or not 0 <= percent <= 100:
            continue
        value = dict(sample)
        for key in ("charging", "usb_connected"):
            value[key] = value.get(key) if value.get(key) in (0, 1) else None
        voltage = value.get("voltage")
        value["voltage"] = (
            voltage
            if (type(voltage) in (int, float) and math.isfinite(voltage) and 0 <= voltage <= 10)
            else None
        )
        readings.append(value)
    return sorted(readings, key=lambda sample: timestamp(sample["recorded_at"]))


def summarize(samples, now=None):
    now = now or datetime.now(UTC)
    samples = battery_readings(samples)
    result = {
        "percent": None,
        "status": "No battery readings yet",
        "alert": None,
        "days_to_charge": None,
        "estimate_label": None,
        "estimate_reason": "No battery readings yet.",
        "drop_points": 0,
        "daily_sample_count": 0,
        "sample_count": 0,
        "span_days": 0,
        "confidence": "Insufficient history",
        "recorded_at": None,
    }
    if not samples:
        return result
    latest = samples[-1]
    result.update(percent=latest["percent"], recorded_at=latest["recorded_at"])
    age = (now - parse_time(latest["recorded_at"])).total_seconds() / 86400
    plugged = latest.get("charging") == 1 or latest.get("usb_connected") == 1
    result["status"] = "Charging or USB connected" if plugged else "Running on battery"
    if not plugged and (latest.get("charging") is None or latest.get("usb_connected") is None):
        result["status"] = "Power status unknown"
    if age > 3:
        result["status"] += "; last reading is over 3 days old"
    if latest["percent"] <= LOW_PERCENT and not plugged:
        result["alert"] = f"Charge soon: last reported battery is {latest['percent']}%."

    cycle = []
    previous = None
    for sample in samples:
        if (
            sample.get("charging") != 0
            or sample.get("usb_connected") != 0
            or (previous is not None and sample["percent"] > previous["percent"] + 5)
            or (
                previous is not None
                and (
                    parse_time(sample["recorded_at"]) - parse_time(previous["recorded_at"])
                ).total_seconds()
                > 3 * 86400
            )
        ):
            cycle = []
        if sample.get("charging") == 0 and sample.get("usb_connected") == 0:
            cycle.append(sample)
        previous = sample
    result["sample_count"] = len(cycle)
    if cycle:
        span = (
            parse_time(cycle[-1]["recorded_at"]) - parse_time(cycle[0]["recorded_at"])
        ).total_seconds() / 86400
        result["span_days"] = round(span, 1)
    else:
        span = 0
    # Use distinct days for both eligibility and fitting. Extra wakes must not
    # substitute for a longer observed discharge.
    daily = {}
    for sample in cycle:
        daily[parse_time(sample["recorded_at"]).date()] = sample
    readings = list(daily.values())
    drop = readings[0]["percent"] - readings[-1]["percent"] if readings else 0
    result.update(daily_sample_count=len(readings), drop_points=drop)
    if latest.get("charging") == 1 or latest.get("usb_connected") == 1:
        result["estimate_reason"] = "Unplug the frame to measure its discharge trend."
        return result
    if latest.get("charging") != 0 or latest.get("usb_connected") != 0:
        result["estimate_reason"] = "The latest reading does not confirm battery-only power."
        return result
    if age > 3:
        result["estimate_reason"] = (
            "A fresh battery reading is needed; the last is over 3 days old."
        )
        return result
    if len(readings) < 5 or span < 7:
        result["estimate_reason"] = (
            f"Collected {len(readings)} daily unplugged readings over {span:.1f} days. "
            "At least five days of readings spanning seven days are needed."
        )
        return result
    # A small voltage-derived percentage drop needs a longer observation window,
    # rather than waiting indefinitely for an arbitrary five-point drop.
    slow_trend = drop < 5
    if slow_trend and not (drop >= 3 and span >= 21 and len(readings) >= 10):
        result["estimate_reason"] = (
            f"Battery changed by {drop} percentage points over {span:.1f} days. "
            "A five-point drop, or a three-point drop with ten daily readings "
            "spanning at least 21 days, is needed."
        )
        return result
    slopes = []
    for i, a in enumerate(readings):
        for b in readings[i + 1 :]:
            days = (parse_time(b["recorded_at"]) - parse_time(a["recorded_at"])).total_seconds()
            days /= 86400
            if days >= 1:
                slopes.append((a["percent"] - b["percent"]) / days)
    rate = median(slopes) if slopes else 0
    if rate <= 0:
        result["estimate_reason"] = "The readings do not yet show a consistent battery decline."
        return result
    days = max(0, (latest["percent"] - LOW_PERCENT) / rate - max(0, age))
    spread = median(abs(slope - rate) for slope in slopes)
    if spread > rate * 0.75:
        result["confidence"] = "Readings vary too much for a reliable estimate"
        result["estimate_reason"] = result["confidence"] + "."
        return result
    if days > 365:
        result["estimate_label"] = "Over one year at the recent rate"
        result["confidence"] = "Limited"
        result["estimate_reason"] = (
            "Only a small part of the battery discharge has been observed. "
            "This is a straight-line trend, not a prediction of battery life; "
            "the discharge rate may change as the battery empties."
        )
        return result
    result["estimate_reason"] = (
        "An early trend based on a small battery drop; it may change as the battery empties."
        if slow_trend
        else "Based on the recent unplugged discharge trend; use and temperature can change it."
    )
    result["days_to_charge"] = round(days, 1)
    result["confidence"] = (
        "Limited" if slow_trend or span < 21 or len(readings) < 10 else "Moderate"
    )
    if days <= FORECAST_DAYS and not result["alert"]:
        result["alert"] = f"Plan to charge: estimated to reach {LOW_PERCENT}% in {days:.1f} days."
    return result


def battery_summary(service, frame_id):
    return summarize(service.store.battery_samples(frame_id))


def chart(samples):
    samples = battery_readings(samples)
    if not samples:
        return ""
    # A daily point keeps the chart readable with a year of history.
    daily = {}
    for sample in samples:
        daily[parse_time(sample["recorded_at"]).date()] = sample
    points = list(daily.values())
    start = parse_time(points[0]["recorded_at"]).timestamp()
    end = parse_time(points[-1]["recorded_at"]).timestamp()

    def x_position(point):
        elapsed = parse_time(point["recorded_at"]).timestamp() - start
        return 40 + 540 * elapsed / max(1, end - start)

    coordinates = " ".join(f"{x_position(p):.1f},{170 - p['percent'] * 1.4:.1f}" for p in points)
    return (
        '<svg viewBox="0 0 600 205" role="img" aria-label="Battery percentage history" '
        'style="width:100%;max-width:650px;max-height:185px"><title>Battery '
        "percentage history</title>"
        '<text x="2" y="35">100%</text><text x="10" y="174">0%</text>'
        '<path d="M40 30V170H580" fill="none" stroke="#999"/>'
        '<path d="M40 142H580" stroke="#a66" stroke-dasharray="5 4"/>'
        f'<polyline points="{coordinates}" fill="none" stroke="#536750" stroke-width="2"/>'
        + "".join(
            f'<circle cx="{xy.split(",")[0]}" cy="{xy.split(",")[1]}" r="2" fill="#536750"/>'
            for xy in coordinates.split()
        )
        + '</svg><p class="quiet">Dashed line: charge threshold (20%). '
        "The table below provides the exact readings.</p>"
    )


def install_battery_routes(app, service, require, escape, page):
    @app.get("/manage/battery")
    def battery_history(request: Request):
        require(request)
        body = '<p class="quiet">Charging reminders appear here and on your overview.</p>'
        body += (
            "<details><summary>How charging estimates work</summary><p>Estimates use observed "
            "discharge history and may change with use, temperature, or battery condition. "
            "Percentage is derived from voltage. Reported USB and charging status can "
            "vary with hardware; some older boards may miss a data-less USB charger. "
            "No email or external notifications are sent.</p></details>"
        )
        frames = service.store.frames()
        chosen = request.query_params.get("frame")
        if chosen and not any(f["id"] == chosen for f in frames):
            raise HTTPException(404, "Unknown frame")
        if chosen:
            body += '<p><a href="/manage/battery">View all frames</a></p>'
        for frame in (f for f in frames if not chosen or f["id"] == chosen):
            samples = battery_readings(service.store.battery_samples(frame["id"]))
            summary = summarize(samples)
            body += f"<section><h2>{escape(frame['id'])}</h2>"
            percent = "Unknown" if summary["percent"] is None else f"{summary['percent']}%"
            body += (
                '<div class="metric-grid"><div class="metric"><span '
                'class="metric-label">Battery level</span><strong>'
                + percent
                + '</strong></div><div class="metric"><span '
                'class="metric-label">Status</span><strong class="battery-status">'
                + escape(summary["status"])
                + "</strong></div></div>"
            )
            if summary["recorded_at"]:
                body += f"<p>Last reported: {escape(local_time(summary['recorded_at']))}.</p>"
            if summary["alert"]:
                body += f'<p class="error" role="status">{escape(summary["alert"])}</p>'
            if summary["days_to_charge"] is not None:
                body += (
                    f"<p>Estimated days to 20%: {summary['days_to_charge']}. "
                    f"Confidence: {escape(summary['confidence'])}. Based on "
                    f"{summary['sample_count']} readings over {summary['span_days']} days "
                    "in the latest discharge cycle.</p>"
                )
                body += f'<p class="quiet">{escape(summary["estimate_reason"])}</p>'
            elif summary["estimate_label"]:
                body += (
                    "<p><strong>Time to 20%: "
                    + escape(summary["estimate_label"])
                    + '.</strong></p><p class="quiet">'
                    + escape(summary["estimate_reason"])
                    + f" Based on {summary['daily_sample_count']} daily unplugged readings "
                    + f"over {summary['span_days']} days, with a "
                    + f"{summary['drop_points']}-point drop. Confidence: "
                    + escape(summary["confidence"])
                    + ".</p>"
                )
            else:
                body += (
                    '<p class="quiet"><strong>Estimate not ready.</strong> '
                    + escape(summary["estimate_reason"])
                    + "</p>"
                )
            body += chart(samples)
            body += (
                "<details><summary>Recent battery readings (up to 60)</summary>"
                '<div class="table-wrap"><table><caption>Battery history, newest '
                "first · Mountain time</caption>"
                "<tr><th>Recorded</th><th>Battery</th><th>Voltage</th>"
                "<th>Charging</th><th>USB</th></tr>"
            )
            for sample in reversed(samples[-60:]):
                voltage = "Unknown" if sample["voltage"] is None else f"{sample['voltage']:.3f} V"

                def state(key):
                    return {None: "Unknown", 0: "No", 1: "Yes"}[sample[key]]

                body += (
                    f"<tr><td>{escape(local_time(sample['recorded_at']))}</td>"
                    f"<td>{sample['percent']}%</td><td>{voltage}</td>"
                    f"<td>{state('charging')}</td><td>{state('usb_connected')}</td></tr>"
                )
            body += "</table></div></details></section>"
            from .diagnostics import diagnostics_section

            body += diagnostics_section(service.store, frame["id"], escape)
        return page("Battery and device health", body)
