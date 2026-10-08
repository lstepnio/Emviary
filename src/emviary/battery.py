"""Battery history and deliberately conservative discharge estimates for the owner UI."""

from datetime import UTC, datetime
from statistics import median

from fastapi import Request

LOW_PERCENT = 20
FORECAST_DAYS = 7


def parse_time(value):
    return datetime.fromisoformat(value).astimezone(UTC)


def summarize(samples, now=None):
    now = now or datetime.now(UTC)
    result = {
        "percent": None,
        "status": "No battery readings yet",
        "alert": None,
        "days_to_charge": None,
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
            sample.get("charging") == 1
            or sample.get("usb_connected") == 1
            or (previous is not None and sample["percent"] > previous["percent"] + 5)
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
    if (
        len(cycle) < 5
        or span < 7
        or cycle[0]["percent"] - cycle[-1]["percent"] < 5
        or latest.get("charging") != 0
        or latest.get("usb_connected") != 0
        or age > 3
    ):
        return result
    # Limit computation and weight to at most one reading a day, preserving the latest one.
    daily = {}
    for sample in cycle:
        daily[parse_time(sample["recorded_at"]).date()] = sample
    readings = list(daily.values())
    if len(readings) < 5:
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
        return result
    days = max(0, (latest["percent"] - LOW_PERCENT) / rate - max(0, age))
    if days > 365:
        result["confidence"] = "Estimate exceeds the supported one-year horizon"
        return result
    spread = median(abs(slope - rate) for slope in slopes)
    if spread > rate * 0.75:
        result["confidence"] = "Readings vary too much for a reliable estimate"
        return result
    result["days_to_charge"] = round(days, 1)
    result["confidence"] = "Limited" if span < 21 or len(readings) < 10 else "Moderate"
    if days <= FORECAST_DAYS and not result["alert"]:
        result["alert"] = f"Plan to charge: estimated to reach {LOW_PERCENT}% in {days:.1f} days."
    return result


def battery_summary(service, frame_id):
    return summarize(service.store.battery_samples(frame_id))


def chart(samples):
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
        'style="width:100%;max-width:650px"><title>Battery percentage history</title>'
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
        body = '<p><a href="/manage">Back to management</a></p>'
        body += (
            "<p>Charge alerts appear here and in web management. Estimates use observed "
            "discharge history and may change with use, temperature, or battery condition. "
            "Percentage is derived from voltage. Reported USB and charging status can "
            "vary with hardware; some older boards may miss a data-less USB charger. "
            "No email or external notifications are sent.</p>"
        )
        for frame in service.store.frames():
            samples = service.store.battery_samples(frame["id"])
            summary = summarize(samples)
            body += f"<section><h2>{escape(frame['id'])}</h2>"
            percent = "Unknown" if summary["percent"] is None else f"{summary['percent']}%"
            body += f"<p>Battery: {percent}. {escape(summary['status'])}.</p>"
            if summary["recorded_at"]:
                body += f"<p>Last reported: {escape(summary['recorded_at'])}.</p>"
            if summary["alert"]:
                body += f'<p class="error" role="status">{escape(summary["alert"])}</p>'
            if summary["days_to_charge"] is not None:
                body += (
                    f"<p>Estimated days to 20%: {summary['days_to_charge']}. "
                    f"Confidence: {escape(summary['confidence'])}. Based on "
                    f"{summary['sample_count']} readings over {summary['span_days']} days "
                    "in the latest discharge cycle.</p>"
                )
            else:
                body += (
                    "<p>No charge-date estimate available. At least five confirmed unplugged "
                    "readings across seven days and a five-point drop are needed. "
                    f"{escape(summary['confidence'])}.</p>"
                )
            body += chart(samples)
            body += (
                "<details><summary>Recent battery readings (up to 60)</summary>"
                "<table><caption>Battery history, newest first; timestamps in UTC</caption>"
                "<tr><th>Recorded</th><th>Battery</th><th>Voltage</th>"
                "<th>Charging</th><th>USB</th></tr>"
            )
            for sample in reversed(samples[-60:]):
                voltage = "Unknown" if sample["voltage"] is None else f"{sample['voltage']:.3f} V"

                def state(key):
                    return {None: "Unknown", 0: "No", 1: "Yes"}[sample[key]]

                body += (
                    f"<tr><td>{escape(sample['recorded_at'])}</td>"
                    f"<td>{sample['percent']}%</td><td>{voltage}</td>"
                    f"<td>{state('charging')}</td><td>{state('usb_connected')}</td></tr>"
                )
            body += "</table></details></section>"
        return page("Battery and charging", body)
