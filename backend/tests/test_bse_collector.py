import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from pipeline.http import FetchError
from pipeline.master import master_csv
from pipeline.master.bse_collector import BseClient, collect, normalise_name, parse_issue_detail, parse_listings, parse_past_issues, parse_scrip_header

FIX = json.loads((Path(__file__).parent / "fixtures" / "bse_ipo_api_sample.json").read_text())


class FakeBse:
    def __init__(self):
        self.detail_calls = []

    def sme_listings(self, year):
        return FIX["listings"] if year == 2026 else {"Table": []}

    def scrip_header(self, bse_code):
        return FIX["headers"][bse_code]

    def past_issues(self, start, end, kind):
        return FIX["issues"][kind]

    def issue_detail(self, ipo_no):
        self.detail_calls.append(ipo_no)
        return FIX["details"][str(ipo_no)]


def collected():
    recs = collect(FakeBse(), date(2026, 1, 1), date(2026, 12, 31), log=lambda *_: None)
    return {r["bse_code"]: r for r in recs}


def test_listings_carry_the_scrip_code_from_the_link():
    rows = parse_listings(FIX["listings"])
    antala = next(r for r in rows if r["bse_code"] == "545024")
    assert (antala["issue_price"], antala["listing_date"]) == (66, date(2026, 11, 11))
    assert parse_listings({"Table": [{"CompanyName": "No link", "IssuePrice": 10, "ListedOn": "2026-01-05T00:00:00", "IMAGE": None}]}) == []


def test_scrip_header():
    assert parse_scrip_header(FIX["headers"]["545024"]) == {"isin": "INE15Z101013", "symbol": "ANTALA", "group": "MT"}


def test_past_issues_keep_sme_public_issues_only():
    names = {r["name"] for kind in ("IPO", "FPO") for r in parse_past_issues(FIX["issues"][kind])}
    assert "BOMBAY COATED AND SPECIAL STEELS LIMITED" not in names  # mainboard: NSE's data covers it
    assert "CONTINENTAL CONTROLS LTD" not in names  # rights issue
    assert len(names) == 4
    liotech = parse_past_issues(FIX["issues"]["FPO"])[0]
    assert (liotech["price_band_low"], liotech["price_band_high"]) == (321, 321)  # fixed price: one number


def test_issue_detail():
    d = parse_issue_detail(FIX["details"]["8070"])
    assert (d["symbol"], d["lot_size"], d["min_bid_lots"]) == ("ANTALA", 2000, 2)
    assert (d["issue_open"], d["issue_close"]) == (date(2026, 10, 29), date(2026, 11, 5))  # extended close date
    assert not d["has_employee_quota"] and d["employee_discount"] == 0


def test_employee_discount_and_revised_band_come_from_the_extra_lines():
    dhaval = parse_issue_detail(FIX["details"]["7854"])
    assert dhaval["has_employee_quota"] and dhaval["employee_discount"] == 5
    assert parse_issue_detail(FIX["details"]["7722"])["revised_band"] == (86, 91)


def test_names_match_despite_spelling():
    assert normalise_name("ANTALA INDUSTRIES LIMITED") == normalise_name(" Antala Industries Ltd.")
    assert normalise_name("Q&T FOODS LIMITED") == normalise_name("Q and T Foods Pvt Ltd")


def test_collect_joins_issue_and_listing():
    recs = collected()
    assert set(recs) == {"545024", "544854", "544769", "544796"}
    antala = recs["545024"]
    assert (antala["isin"], antala["segment"], antala["exchanges"], antala["nse_symbol"]) == ("INE15Z101013", "sme", "BSE", None)
    assert (antala["lot_size"], antala["issue_close"], antala["source"]) == (2000, date(2026, 11, 5), "bse_api")
    assert antala["individual_min_lots"] is None  # the standard 2 lots needs no override


def test_collect_falls_back_to_the_company_name():
    # BSE lists the issue under DHAVALPACK but the stock trades as DHAVAL
    dhaval = collected()["544854"]
    assert (dhaval["lot_size"], dhaval["employee_discount"], dhaval["has_employee_quota"]) == (1200, 5, True)
    assert dhaval["individual_min_lots"] is None  # BSE shows 1 lot here; individuals still need 2


def test_collect_uses_the_revised_band_and_fixed_price():
    recs = collected()
    assert (recs["544769"]["price_band_low"], recs["544769"]["price_band_high"], recs["544769"]["issue_price"]) == (86, 91, 91)
    assert (recs["544796"]["price_band_low"], recs["544796"]["issue_price"], recs["544796"]["lot_size"]) == (321, 321, 400)
    assert master_csv.problems(list(recs.values())) == []


def test_collect_respects_the_date_range_and_skips_unmatched():
    recs = collect(FakeBse(), date(2026, 11, 1), date(2026, 11, 30), log=lambda *_: None)
    assert [r["bse_code"] for r in recs] == ["545024"]

    class NoIssues(FakeBse):
        def past_issues(self, start, end, kind):
            return {"Table": []}

    said = []
    assert collect(NoIssues(), date(2026, 1, 1), date(2026, 12, 31), log=said.append) == []
    assert len(said) == 4 and "by hand" in said[0]  # every skipped IPO is reported


def test_old_issue_of_the_same_company_is_not_matched():
    class Stale(FakeBse):
        def past_issues(self, start, end, kind):
            rows = [dict(r, End_Dt="2026-03-01T00:00:00") for r in FIX["issues"][kind]["Table"]]
            return {"Table": rows}

    assert collect(Stale(), date(2026, 11, 1), date(2026, 11, 30), log=lambda *_: None) == []


def test_web_page_instead_of_json_is_an_error():
    class Page:
        def get(self, url, headers=None):
            return httpx.Response(200, content=b"<!DOCTYPE html><html></html>")

    with pytest.raises(FetchError):
        BseClient(Page(), pause=0).sme_listings(2026)


def test_client_builds_the_urls_bse_expects():
    seen = []

    class Recorder:
        def get(self, url, headers=None):
            seen.append((url, headers))
            return httpx.Response(200, content=b'{"Table": []}')

    bse = BseClient(Recorder(), pause=0)
    bse.past_issues(date(2026, 1, 1), date(2026, 11, 14), "IPO")
    bse.scrip_header("545024")
    assert "Start_DT=01/01/2026" in seen[0][0] and "end_dt=14/11/2026" in seen[0][0] and "IR_FLAG=IPO" in seen[0][0]
    assert seen[1][0].endswith("ComHeadernew/w?quotetype=EQ&scripcode=545024&seriesid=")
    assert seen[0][1]["Referer"] == "https://www.bseindia.com/"


# ---------- merging two collectors into one master list ----------


def test_collectors_do_not_overwrite_each_others_rows():
    nse_row = {"isin": "INE15Z101013", "company": "Antala", "source": "nse_api", "lot_size": 999, "bse_code": None, "segment": "sme"}
    manual = {"isin": "INE1HX301016", "company": "Dhaval", "source": "manual", "lot_size": 1, "bse_code": "544854", "issue_open": None}
    merged, added, updated = master_csv.merge([nse_row, manual], list(collected().values()))
    by = {r["isin"]: r for r in merged}
    assert added == 2 and updated == 2
    assert by["INE15Z101013"]["lot_size"] == 999 and by["INE15Z101013"]["source"] == "nse_api"  # kept
    assert by["INE15Z101013"]["bse_code"] == "545024"  # blank cell filled
    assert by["INE1HX301016"]["lot_size"] == 1 and by["INE1HX301016"]["issue_open"] == date(2026, 7, 30)


def test_collector_refreshes_its_own_rows():
    recs = list(collected().values())
    stale = [dict(r, lot_size=1) for r in recs]
    merged, added, updated = master_csv.merge(stale, recs)
    assert (added, updated) == (0, 4) and all(r["lot_size"] > 1 for r in merged)
    assert master_csv.merge(merged, recs)[1:] == (0, 0)  # running it again changes nothing
