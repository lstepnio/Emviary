"""Render original AI birds through the production six-ink pipeline for review."""

import argparse
import json
from pathlib import Path

from emviary import render
from emviary.settings import FramePolicy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--art-dir", type=Path, default=Path("art"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    collection = json.loads(args.manifest.read_text())
    birds = collection["artworks"]
    policy = FramePolicy(show_location_name=True, seasonal_themes=False).model_dump()
    results = []
    groups = [("solo-" + a["id"], [a]) for a in birds]
    groups += [(f"trio-{n // 3 + 1:02d}", birds[n : n + 3]) for n in range(0, len(birds), 3)]
    for name, group in groups:
        plan = {
            "local_date": "2026-10-08",
            "location_label": "COLORADO",
            "policy": policy,
            "artworks": group,
            "layout": {"name": {1: "solo", 2: "pair", 3: "trio"}[len(group)]},
            "inputs": {
                "open_meteo": {
                    "local_date": "2026-10-08",
                    "values": {
                        "weather_code": 0,
                        "temperature_2m_max": 24,
                        "temperature_2m_min": 7,
                        "precipitation_sum": 0,
                        "wind_speed_10m_max": 5,
                    },
                }
            },
        }
        source = args.output / f"{name}.png"
        packed = args.output / f"{name}.epdgz"
        preview = args.output / f"{name}.jpg"
        render.compose(args.art_dir.resolve(), group[0], plan, source)
        digest = render.convert(source, packed, preview, policy, 60)
        results.append({"name": name, "artwork_ids": [a["id"] for a in group], "sha256": digest})
        print(name, flush=True)
    (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    cards = "".join(
        f'<figure><img src="{r["name"]}.jpg"><figcaption>{r["name"]}</figcaption></figure>'
        for r in results
    )
    (args.output / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Emviary six-color bird review</title>'
        "<style>body{background:#fff;font:14px sans-serif;margin:20px}"
        ".grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}"
        "figure{margin:0}img{width:100%;display:block}figcaption{padding:8px}</style>"
        '<h1>Emviary: actual packed six-ink previews</h1><div class="grid">' + cards + "</div>"
    )


if __name__ == "__main__":
    main()
