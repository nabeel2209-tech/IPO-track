"""Collect IPOs listed on BSE's SME platform from BSE's public API.

BSE SME IPOs trade only on BSE, so NSE's data never mentions them. BSE's own public-issue pages
read four endpoints under ``https://api.bseindia.com/BseIndiaAPI/api/``:

- ``MoreCompanyN/w?Fromdt=YEAR&company=&flag=2&type=2``: SME IPOs listed in a year, with the issue
  price, the listing date and a link that carries the stock's BSE scrip code.
- ``ComHeadernew/w?quotetype=EQ&scripcode=CODE&seriesid=``: ISIN and trading symbol for a scrip code.
- ``HomePage_Issues_BBS_Landing_ng/w?flag=2&...&Start_DT=DD/MM/YYYY&end_dt=DD/MM/YYYY&IR_FLAG=IPO``:
  past issues (``IPO`` is book-built, ``FPO`` is fixed price), with dates and the price band.
- ``ipo_details_ng/w?stripono=IPO_NO``: one issue's details, including symbol and lot size.

No single record links an issue (which has the lot size) to the listed stock (which has the ISIN and
listing date), so the collector joins them: by trading symbol first, then by company name.

Parsing is separated from fetching so it can be tested against saved responses.
"""

import json
import re
import time
from datetime import date, datetime, timedelta

import httpx

from pipeline.http import FetchError, get_bytes

BASE = "https://api.bseindia.com/BseIndiaAPI/api/"
SITE = "https://www.bseindia.com"
ISSUE_KINDS = ("IPO", "FPO")  # book-built and fixed-price public issues
LOOKBACK_DAYS = 60  # an issue closes at most a few weeks before it lists
MAX_DAYS_TO_LIST = 45


def _num(text) -> float | None:
    if text is None:
        return None
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(text))
    return float(m.group(0).replace(",", "")) if m else None


def _bse_date(text) -> date | None:
    """BSE uses '2026-10-29T00:00:00', '29 Oct 2026' and '29/10/2026' in different places."""
    if not text:
        return None
    t = str(text).strip()
    for fmt, n in (("%Y-%m-%d", 10), ("%d %b %Y", 11), ("%d/%m/%Y", 10)):
        try:
            return datetime.strptime(t[:n].strip(), fmt).date()
        except ValueError:
            continue
    return None


def normalise_name(name: str) -> str:
    """'ANTALA INDUSTRIES LIMITED' and 'Antala Industries Ltd.' → 'antalaindustries'."""
    n = re.sub(r"\b(limited|ltd|private|pvt)\b\.?", " ", (name or "").lower())
    n = n.replace("&", " and ")
    return re.sub(r"[^a-z0-9]", "", n)


def parse_listings(payload: dict) -> list[dict]:
    out = []
    for r in payload.get("Table") or []:
        code = re.search(r"/(\d{6})/?$", r.get("IMAGE") or "")
        listed = _bse_date(r.get("ListedOn"))
        price = _num(r.get("IssuePrice"))
        if not code or not listed or not price:
            continue
        out.append({"company": (r.get("CompanyName") or "").strip(), "issue_price": price, "listing_date": listed, "bse_code": code.group(1)})
    return out


def parse_scrip_header(payload: dict) -> dict:
    return {
        "isin": (payload.get("ISIN") or "").strip().upper(),
        "symbol": (payload.get("SecurityId") or "").strip().upper(),
        "group": (payload.get("Group") or "").strip().upper(),
    }


def parse_past_issues(payload: dict) -> list[dict]:
    """SME public issues only; rights issues, buybacks, debt and mainboard rows are dropped."""
    out = []
    for r in payload.get("Table") or []:
        if (r.get("eXCHANGE_PLATFORM") or "").strip().upper() != "SME" or r.get("IR_flag") not in ISSUE_KINDS:
            continue
        band = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", r.get("Price_Band") or "")]
        out.append(
            {
                "ipo_no": int(r["IPO_NO"]),
                "name": (r.get("Scrip_Name") or "").strip(),
                "issue_open": _bse_date(r.get("Start_Dt")),
                "issue_close": _bse_date(r.get("End_Dt")),
                "price_band_low": band[0] if band else None,
                "price_band_high": band[-1] if band else None,
            }
        )
    return out


def _band_notes(row: dict) -> dict:
    """The Price Band row sometimes carries extra lines after the band itself.

    Two kinds matter: an employee discount ("Discount of Rs 5/- available for Employees...") and a
    revised band ("The revised price band w.e.f. 25/05/2026 will be Rs.86/- to Rs. 91/-").
    """
    out: dict = {}
    for line in (row.get("MultilineValues") or [])[1:]:
        text = str(line or "")
        low = text.lower()
        if "employee" in low and "discount" in low:
            m = re.search(r"discount of\s*(?:rs\.?|₹)?\s*(\d+(?:\.\d+)?)", low)
            if m:
                out["employee_discount"] = float(m.group(1))
        elif "revised" in low and "band" in low:
            m = re.search(r"will be\D*?(\d+(?:\.\d+)?)\D+?(\d+(?:\.\d+)?)", low)
            if m:
                out["revised_band"] = (float(m.group(1)), float(m.group(2)))
    return out


def parse_issue_detail(payload: dict) -> dict:
    raw = {(r.get("Label") or "").strip().lower(): r for r in payload.get("TableRows") or []}
    rows = {k: str(r.get("Value") or "").strip() for k, r in raw.items()}
    lot = _num(rows.get("market lot"))
    min_bid = _num(rows.get("minimum bid quantity"))
    categories = {c.strip().upper() for c in rows.get("ipo categories", "").split(",")}
    period = re.findall(r"\d{1,2} [A-Za-z]{3} \d{4}", rows.get("issue period", ""))
    notes = _band_notes(raw.get("price band") or {})
    return {
        "symbol": rows.get("symbol", "").upper(),
        "name": rows.get("scripname", ""),
        "lot_size": int(lot) if lot else None,
        "min_bid_lots": round(min_bid / lot) if lot and min_bid else None,
        "has_employee_quota": "EMP" in categories,
        "has_shareholder_quota": "SHA" in categories,
        "employee_discount": notes.get("employee_discount", 0.0),
        "revised_band": notes.get("revised_band"),
        "issue_open": _bse_date(period[0]) if period else None,
        "issue_close": _bse_date(period[1]) if len(period) > 1 else None,
    }


class BseClient:
    def __init__(self, client: httpx.Client, pause: float = 0.3):
        self.client = client
        self.pause = pause

    def _json(self, path: str):
        headers = {"Referer": SITE + "/", "Origin": SITE, "Accept": "application/json, text/plain, */*"}
        text = get_bytes(self.client, BASE + path, headers=headers).decode("utf-8-sig", errors="replace").strip()
        time.sleep(self.pause)
        if not text.startswith(("{", "[")):  # BSE answers 200 with a web page when it rejects a request
            raise FetchError(f"BSE returned a web page instead of data for {path}")
        return json.loads(text)

    def sme_listings(self, year: int) -> dict:
        return self._json(f"MoreCompanyN/w?Fromdt={year}&company=&flag=2&type=2")

    def scrip_header(self, bse_code: str) -> dict:
        return self._json(f"ComHeadernew/w?quotetype=EQ&scripcode={bse_code}&seriesid=")

    def past_issues(self, start: date, end: date, kind: str) -> dict:
        return self._json(f"HomePage_Issues_BBS_Landing_ng/w?flag=2&scrip_Name=&end_dt={end:%d/%m/%Y}&IR_FLAG={kind}&Start_DT={start:%d/%m/%Y}")

    def issue_detail(self, ipo_no: int) -> dict:
        return self._json(f"ipo_details_ng/w?stripono={ipo_no}")


def _best_issue(candidates: list[dict], listing_date: date) -> dict | None:
    """The issue that closed most recently before the listing (a company may have tried twice)."""
    ok = [i for i in candidates if i.get("issue_close") and timedelta(0) <= listing_date - i["issue_close"] <= timedelta(days=MAX_DAYS_TO_LIST)]
    return max(ok, key=lambda i: i["issue_close"]) if ok else None


def collect(bse: BseClient, start: date, end: date, log=print) -> list[dict]:
    """Every BSE SME IPO that listed between ``start`` and ``end``, with details."""
    listings = []
    for year in range(start.year, end.year + 1):
        listings += [x for x in parse_listings(bse.sme_listings(year)) if start <= x["listing_date"] <= end]

    issues = []
    for kind in ISSUE_KINDS:
        issues += parse_past_issues(bse.past_issues(start - timedelta(days=LOOKBACK_DAYS), end, kind))
    by_symbol: dict[str, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    for issue in issues:
        try:
            detail = parse_issue_detail(bse.issue_detail(issue["ipo_no"]))
        except Exception as e:  # keep going; this issue can still match by name
            log(f"  ! BSE issue {issue['name']}: {e}")
            detail = {}
        issue.update({k: v for k, v in detail.items() if v not in (None, "") and (k not in issue or issue[k] is None)})
        if issue.get("symbol"):
            by_symbol.setdefault(issue["symbol"], []).append(issue)
        for name in {normalise_name(issue["name"]), normalise_name(detail.get("name", ""))} - {""}:
            by_name.setdefault(name, []).append(issue)

    records = []
    for x in listings:
        try:
            header = parse_scrip_header(bse.scrip_header(x["bse_code"]))
        except Exception as e:
            log(f"  ! BSE {x['company']}: {e}")
            continue
        issue = _best_issue(by_symbol.get(header["symbol"], []), x["listing_date"]) or _best_issue(by_name.get(normalise_name(x["company"]), []), x["listing_date"])
        if not header["isin"] or issue is None or not issue.get("lot_size"):
            log(f"  ! BSE {x['company']} ({x['bse_code']}): no matching issue details, skipped (add it by hand with source=manual)")
            continue
        min_lots = issue.get("min_bid_lots")
        low, high = issue.get("revised_band") or (issue.get("price_band_low"), issue.get("price_band_high"))
        records.append(
            {
                "isin": header["isin"],
                "company": x["company"],
                "segment": "sme",
                "nse_symbol": None,
                "bse_code": x["bse_code"],
                "exchanges": "BSE",
                "issue_open": issue.get("issue_open"),
                "issue_close": issue.get("issue_close"),
                "listing_date": x["listing_date"],
                "issue_price": x["issue_price"],
                "price_band_low": low,
                "price_band_high": high,
                "lot_size": issue["lot_size"],
                "has_employee_quota": bool(issue.get("has_employee_quota")),
                "employee_discount": float(issue.get("employee_discount") or 0.0),
                "has_shareholder_quota": bool(issue.get("has_shareholder_quota")),
                # Individuals must apply for 2 lots in an SME IPO. An override is recorded only when the
                # offer asks for more; BSE sometimes shows 1 lot here (the employee minimum).
                "individual_min_lots": min_lots if min_lots and min_lots > 2 else None,
                "source": "bse_api",
            }
        )
    return records
