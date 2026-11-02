#!/usr/bin/env python3
"""Fetch Pinergy Smart account data (balance, usage, comparison) into
data/pinergy_data.json.

Credentials: read from the PINERGY_EMAIL / PINERGY_PASSWORD environment
variables (this is how GitHub Actions injects the repo secrets). For local
manual runs only, falls back to a ~/.pinergy.env file (KEY=VALUE per line)
when the env vars are not already set.

Data minimization: only balance, usage (day/week/month) and compare are
fetched and written. active_topups is deliberately NOT called — it is not
needed by the dashboard and this keeps the exported payload smaller. More
importantly, the balance/usage/compare endpoints never return the
pypinergy User / House / CreditCard objects or a premises number (those
only ever appear inside pypinergy.LoginResponse, which this script never
touches) — so this JSON is PII-free by construction, not by post-hoc
filtering.

Exit code is non-zero on any failure (missing credentials, import error,
API/network error), with a clear message on stderr, so a scheduled CI run
fails loudly instead of publishing stale or partial data.
"""
import dataclasses
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_env_fallback() -> None:
    """Populate PINERGY_EMAIL / PINERGY_PASSWORD from ~/.pinergy.env if unset.

    Local convenience only. CI must supply the env vars directly via
    repository secrets — this fallback is never exercised there.
    """
    env_file = Path.home() / ".pinergy.env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key in ("PINERGY_EMAIL", "PINERGY_PASSWORD") and not os.environ.get(key):
            os.environ[key] = value


def dump(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    return obj


def _iso_date(value) -> str:
    """Return the plain YYYY-MM-DD for a datetime/date/str usage-day value."""
    if hasattr(value, "date"):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)[:10]


def merge_history(usage_day: list, fetched_at: str, history_path: Path) -> int:
    """Append/update data/history.ndjson with today's usage.day entries.

    One JSON line per calendar date: {date, kwh, amount, fetched_at}.
    The 7-day sliding window returned by the API overlaps previous runs, so
    entries are deduplicated by date — a duplicate date is overwritten by the
    value from *this* run, since Pinergy can consolidate/revise a day's
    figures after the fact and this run is always the most recent look at
    that date. The file is created if it doesn't exist yet, and always
    rewritten sorted by date.

    Returns the number of distinct days now in the file.
    """
    entries: dict = {}
    if history_path.exists():
        for line in history_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            date_key = rec.get("date")
            if date_key:
                entries[date_key] = rec

    for day in usage_day:
        date_key = _iso_date(day.get("date"))
        entries[date_key] = {
            "date": date_key,
            "kwh": day.get("kwh"),
            "amount": day.get("amount"),
            "fetched_at": fetched_at,
        }

    history_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(entries[d], sort_keys=False) for d in sorted(entries.keys())]
    history_path.write_text("\n".join(lines) + ("\n" if lines else ""))
    return len(lines)

def _resolve_label_date(label: str, fetched_at: str) -> str:
    """Turn a 'dd/mm' label from /api/levelpayusage/ into YYYY-MM-DD.

    The year is not in the payload: take the fetch year, and step back one
    year when that would land after the fetch date (31/12 read on 02/01).
    """
    from datetime import date
    fetched = datetime.fromisoformat(fetched_at).date()
    day, month = (int(x) for x in label.split("/"))
    candidate = date(fetched.year, month, day)
    if candidate > fetched:
        candidate = date(fetched.year - 1, month, day)
    return candidate.isoformat()


def find_gap(dates_on_file: list, window_dates: list) -> list:
    """Return the dates (YYYY-MM-DD) lost between the file and the API window.

    The API only exposes the last 7 days: if the newest day on file is more
    than one day before the oldest day of the fresh window, the days in
    between can never be recovered. Returns them so the caller can warn.
    """
    from datetime import date, timedelta
    if not dates_on_file or not window_dates:
        return []
    last = date.fromisoformat(max(dates_on_file))
    first = date.fromisoformat(min(window_dates))
    return [(last + timedelta(days=i)).isoformat() for i in range(1, (first - last).days)]


def merge_halfhourly(raw: dict, fetched_at: str, path: Path) -> int:
    """Append/update data/history_halfhourly.ndjson from /api/levelpayusage/.

    The endpoint only returns the last 7 days, so this file is the only way
    to build a longer half-hourly history. One JSON line per date:
    {date, kwh: [48 floats, 00:00 -> 23:30], fetched_at}. Duplicate dates are
    overwritten by this run (Pinergy can revise recent days). Returns the
    number of distinct days on file.
    """
    entries: dict = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("date"):
                entries[rec["date"]] = rec

    values = raw["usageData"]["daily"]["values"]
    window = [_resolve_label_date(v["label"], fetched_at) for v in values]
    lost = find_gap(list(entries), window)
    if lost:
        print(
            f"::warning::half-hourly gap: {len(lost)} day(s) permanently lost "
            f"({lost[0]} -> {lost[-1]}) — the API only keeps 7 days, run the refresh more often",
            file=sys.stderr,
        )
    for v in values:
        slots = [float(x) for x in v["halfHourlykWh"]]
        if len(slots) != 48:
            raise ValueError(f"expected 48 half-hour slots, got {len(slots)} for {v.get('label')}")
        date_key = _resolve_label_date(v["label"], fetched_at)
        entries[date_key] = {"date": date_key, "kwh": slots, "fetched_at": fetched_at}

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(entries[d]) for d in sorted(entries)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""))
    return len(lines)


def main() -> int:
    load_env_fallback()

    email = os.environ.get("PINERGY_EMAIL", "").strip()
    password = os.environ.get("PINERGY_PASSWORD", "").strip()
    if not email or not password:
        print(
            "ERROR: PINERGY_EMAIL / PINERGY_PASSWORD not set "
            "(environment variables, or ~/.pinergy.env for local runs)",
            file=sys.stderr,
        )
        return 1

    try:
        from pypinergy import PinergyClient
    except ImportError as exc:
        print(f"ERROR: pypinergy is not installed: {exc}", file=sys.stderr)
        return 1

    out: dict = {}
    levelpay_raw = None
    try:
        with PinergyClient(email, password) as client:
            out["balance"] = dump(client.get_balance())
            out["usage"] = dump(client.get_usage())
            out["compare"] = dump(client.compare_usage())
            # Half-hourly data: pypinergy's typed model drops halfHourlykWh,
            # so read the raw payload. Optional — a failure here must not
            # fail the run (see below), but it IS surfaced as a CI warning.
            try:
                levelpay_raw = client._get("/api/levelpayusage/")
            except Exception as exc:  # noqa: BLE001
                levelpay_raw = None
                print(f"::warning::half-hourly fetch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            # NOTE: do not add get_active_topups() or anything touching
            # login()'s User/House/CreditCard/premises_number here — see
            # module docstring. This script must stay PII-free by
            # construction.
    except Exception as exc:  # noqa: BLE001 - surface any API/network failure
        print(f"ERROR: Pinergy API call failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    out["fetched_at"] = datetime.now(timezone.utc).isoformat()

    out_dir = Path(__file__).parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pinergy_data.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"Wrote {out_path} ({out_path.stat().st_size} bytes)")

    try:
        history_path = out_dir / "history.ndjson"
        day_count = merge_history(out["usage"]["day"], out["fetched_at"], history_path)
        print(f"Updated {history_path} ({day_count} distinct day(s) on file)")
    except Exception as exc:  # noqa: BLE001 - a broken history file must fail the run
        print(f"ERROR: failed to update history.ndjson: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if levelpay_raw is not None:
        try:
            hh_path = out_dir / "history_halfhourly.ndjson"
            n = merge_halfhourly(levelpay_raw, out["fetched_at"], hh_path)
            print(f"Updated {hh_path} ({n} distinct day(s) on file)")
        except Exception as exc:  # noqa: BLE001 - optional dataset, loud but non-fatal
            print(f"::warning::half-hourly history not updated: {type(exc).__name__}: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
