"""Offline tests for the half-hourly history collector. Run: python3 -m unittest discover tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fetch_pinergy as f  # noqa: E402

FETCHED = "2026-11-02T06:30:00+00:00"


def payload(labels, value=0.1):
    return {"usageData": {"daily": {"values": [
        {"label": lab, "halfHourlykWh": [str(value)] * 48} for lab in labels]}}}


class ResolveDate(unittest.TestCase):
    def test_same_year(self):
        self.assertEqual(f._resolve_label_date("01/11", FETCHED), "2026-11-01")

    def test_year_rollover(self):
        self.assertEqual(f._resolve_label_date("31/12", "2027-01-02T06:30:00+00:00"), "2026-12-31")


class FindGap(unittest.TestCase):
    def test_contiguous(self):
        self.assertEqual(f.find_gap(["2026-10-25"], ["2026-10-26", "2026-10-27"]), [])

    def test_overlap(self):
        self.assertEqual(f.find_gap(["2026-10-30"], ["2026-10-26", "2026-10-31"]), [])

    def test_lost_days(self):
        self.assertEqual(f.find_gap(["2026-10-20"], ["2026-10-24"]),
                         ["2026-10-21", "2026-10-22", "2026-10-23"])

    def test_empty_file(self):
        self.assertEqual(f.find_gap([], ["2026-10-24"]), [])


class Merge(unittest.TestCase):
    def test_creates_dedupes_and_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hh.ndjson"
            self.assertEqual(f.merge_halfhourly(payload(["31/10", "01/11"]), FETCHED, path), 2)
            # second run overlaps by one day with a revised value, adds one new day
            n = f.merge_halfhourly(payload(["01/11", "02/11"], value=0.2), FETCHED, path)
            self.assertEqual(n, 3)
            recs = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([r["date"] for r in recs], ["2026-10-31", "2026-11-01", "2026-11-02"])
            self.assertEqual(recs[1]["kwh"][0], 0.2)   # overwritten by the latest look
            self.assertEqual(recs[0]["kwh"][0], 0.1)   # untouched
            self.assertTrue(all(len(r["kwh"]) == 48 for r in recs))

    def test_rejects_wrong_slot_count(self):
        bad = {"usageData": {"daily": {"values": [{"label": "01/11", "halfHourlykWh": ["0.1"] * 47}]}}}
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                f.merge_halfhourly(bad, FETCHED, Path(d) / "hh.ndjson")


if __name__ == "__main__":
    unittest.main()
