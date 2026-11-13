import json
from datetime import date
from pathlib import Path

from pipeline.master import master_csv
from pipeline.master.nse_collector import collect, parse_ipo_detail, parse_past_issues

FIX = json.loads((Path(__file__).parent / "fixtures" / "nse_ipo_api_sample.json").read_text())


def test_past_issues_keeps_listed_equity_only():
    rows = parse_past_issues(FIX["past"])
    syms = {r["nse_symbol"]: r for r in rows}
    assert set(syms) == {"JPL", "NITYAS", "RAVITA"}  # debt and not-yet-listed issues dropped
    assert syms["RAVITA"]["segment"] == "sme" and syms["NITYAS"]["segment"] == "mainboard"
    assert syms["JPL"]["listing_date"] == date(2026, 10, 28)
    assert (syms["JPL"]["price_band_low"], syms["JPL"]["price_band_high"], syms["JPL"]["issue_price"]) == (1065, 1119, 1119)


def test_ipo_detail_parsing():
    jio = parse_ipo_detail(FIX["detail"]["JPL"])
    assert jio["isin"] == "INE0BJO01010" and jio["lot_size"] == 12
    assert jio["employee_discount"] == 54 and jio["has_employee_quota"] and jio["has_shareholder_quota"]
    assert jio["sub_qib"] == 37.22  # NSE-only figure when no consolidated table is present
    nityas = parse_ipo_detail(FIX["detail"]["NITYAS"])
    assert nityas["employee_discount"] == 7 and nityas["has_employee_quota"] and not nityas["has_shareholder_quota"]
    ravita = parse_ipo_detail(FIX["detail"]["RAVITA"])
    assert ravita["lot_size"] == 1200 and not ravita["has_employee_quota"]


def test_consolidated_subscription_preferred():
    payload = dict(FIX["detail"]["JPL"])
    payload["activeCat"] = {
        "dataList": [
            {"category": "Category", "noOfShareOffered": "No.of shares", "noOfSharesBid": "bid", "noOfTotalMeant": "times", "srNo": "Sr.No."},
            {"category": "Qualified Institutional Buyers(QIBs)", "noOfShareOffered": "49007827", "noOfSharesBid": "3457557456", "noOfTotalMeant": "70.55112759845484", "srNo": "1"},
        ]
    }
    assert parse_ipo_detail(payload)["sub_qib"] == 70.55


def test_discount_written_without_space():
    payload = {
        "metaInfo": {"isin": "INE05XR01022"},
        "issueInfo": {
            "dataList": [
                {"title": "Bid Lot", "value": "600 Equity Shares"},
                {"title": "Discount", "value": "Re.1 per Equity Share to Eligible Employees"},
            ]
        },
    }
    assert parse_ipo_detail(payload)["employee_discount"] == 1


class FakeNse:
    def past_issues(self, start, end):
        return FIX["past"]

    def ipo_detail(self, symbol, series):
        return FIX["detail"][symbol]


def test_collect_end_to_end():
    recs = collect(FakeNse(), date(2026, 10, 1), date(2026, 10, 31), log=lambda *_: None)
    assert {r["isin"] for r in recs} == {"INE0BJO01010", "INE211501023", "INE1UEL01023"}
    assert all(r["source"] == "nse_api" for r in recs)


def test_master_csv_round_trip_and_merge(tmp_path):
    recs = collect(FakeNse(), date(2026, 10, 1), date(2026, 10, 31), log=lambda *_: None)
    path = tmp_path / "m.csv"
    master_csv.write(path, recs)
    back = master_csv.read(path)
    assert len(back) == 3 and back[0]["listing_date"] <= back[-1]["listing_date"]
    # a hand-corrected row survives the next collection
    jio = next(r for r in back if r["isin"] == "INE0BJO01010")
    jio["source"], jio["lot_size"] = "manual", 13
    merged, added, updated = master_csv.merge(back, recs)
    assert added == 0
    assert next(r for r in merged if r["isin"] == "INE0BJO01010")["lot_size"] == 13


def test_master_problems_are_caught():
    bad = [{"isin": "XYZ", "company": "Bad Co", "segment": "other", "issue_price": 0, "lot_size": 0, "issue_close": date(2026, 1, 10), "listing_date": date(2026, 1, 5)}]
    msgs = " | ".join(master_csv.problems(bad))
    for part in ("ISIN", "segment", "issue price", "lot size", "listed before"):
        assert part in msgs


def test_repo_master_file_is_valid():
    path = Path(__file__).resolve().parent.parent / "data" / "ipo_master.csv"
    recs = master_csv.read(path)
    assert len(recs) > 100
    hard = [p for p in master_csv.problems(recs) if "outside band" not in p]
    assert hard == []
