#!/usr/bin/env python3
"""Build public/index.html from data/pinergy_data.json + template.html.

The template is static HTML/CSS/JS; this script's only job is to inject the
fetched JSON payload into it (as window.PINERGY_DATA) so every KPI and chart
is computed client-side, in the browser, from the actual data of the day.

Exit code is non-zero if the data file is missing/invalid or the template's
injection placeholder can't be found, so a broken build fails the CI job
instead of silently publishing stale content.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DATA_PATH = ROOT / "data" / "pinergy_data.json"
HISTORY_PATH = ROOT / "data" / "history.ndjson"
TEMPLATE_PATH = ROOT / "template.html"
OUT_PATH = ROOT / "public" / "index.html"
PLACEHOLDER = "__PINERGY_DATA_JSON__"


def load_history() -> list:
    """Read data/history.ndjson (one JSON record per line) if present.

    Malformed lines are skipped rather than failing the build — the history
    file is a nice-to-have for the weekday-profile chart, not a hard
    dependency of the dashboard.
    """
    if not HISTORY_PATH.exists():
        return []
    records = []
    for line in HISTORY_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def main() -> int:
    if not DATA_PATH.exists():
        print(f"ERROR: {DATA_PATH} not found — run fetch_pinergy.py first", file=sys.stderr)
        return 1

    try:
        data = json.loads(DATA_PATH.read_text())
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON in {DATA_PATH}: {exc}", file=sys.stderr)
        return 1

    history = load_history()
    data["history"] = history
    print(f"Loaded {len(history)} history record(s) from {HISTORY_PATH}")

    if not TEMPLATE_PATH.exists():
        print(f"ERROR: template not found: {TEMPLATE_PATH}", file=sys.stderr)
        return 1

    template = TEMPLATE_PATH.read_text()
    if PLACEHOLDER not in template:
        print(f"ERROR: placeholder {PLACEHOLDER} not found in {TEMPLATE_PATH}", file=sys.stderr)
        return 1

    html = template.replace(PLACEHOLDER, json.dumps(data))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html)
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
