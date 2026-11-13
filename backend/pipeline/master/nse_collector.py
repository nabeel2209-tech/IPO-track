"""Collect IPO details (issue price, lot size, quotas, discount, subscription) from NSE's public API.

Two endpoints, both used by NSE's own IPO pages:
- ``/api/public-past-issues?from_date=DD-MM-YYYY&to_date=DD-MM-YYYY``: every issue in a period.
- ``/api/ipo-detail?symbol=XYZ&series=EQ``: one issue's details, including ISIN and lot size.

Parsing is separated from fetching so it can be tested against saved responses.
"""

import re
import time
from datetime import date, datetime

import httpx

from pipeline.http import get_bytes

BASE = "https://www.nseindia.com"
EQUITY_TYPES = {"EQ": "mainboard", "BE": "mainboard", "SME": "sme"}


def _num(text: str | None) -> float | None:
    if text is None:
        return None
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(text))
    return float(m.group(0).replace(",", "")) if m else None


def _nse_date(text: str | None) -> date | None:
    """NSE uses both '28-OCT-2026' and '2026-10-28'."""
    if not text or text.strip() in ("-", ""):
        return None
    t = text.strip().title()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def parse_past_issues(payload: list[dict]) -> list[dict]:
    """Keep listed equity IPOs (mainboard EQ/BE and NSE Emerge SME), drop debt, REITs and InvITs."""
    out = []
    seen = set()
    for x in payload:
        seg = EQUITY_TYPES.get((x.get("securityType") or "").strip())
        listing = _nse_date(x.get("listingDate"))
        price = _num(x.get("issuePrice"))
        if not seg or not listing or not price:
            continue
        key = (x["symbol"], x["securityType"])
        if key in seen:
            continue
        seen.add(key)
        band = re.findall(r"\d[\d,]*(?:\.\d+)?", x.get("priceRange") or "")
        out.append(
            {
                "nse_symbol": x["symbol"].strip(),
                "series": x["securityType"].strip(),
                "segment": seg,
                "company": (x.get("company") or x.get("companyName") or "").strip(),
                "issue_open": _nse_date(x.get("ipoStartDate")),
                "issue_close": _nse_date(x.get("ipoEndDate")),
                "listing_date": listing,
                "issue_price": price,
                "price_band_low": float(band[0].replace(",", "")) if band else None,
                "price_band_high": float(band[-1].replace(",", "")) if band else None,
            }
        )
    return out


def _times(b: dict | None) -> float | None:
    if not b:
        return None
    try:
        return round(float(b.get("noOfTime")), 2)
    except (TypeError, ValueError):
        return None


def parse_ipo_detail(payload: dict) -> dict:
    meta = payload.get("metaInfo") or {}
    items = (payload.get("issueInfo") or {}).get("dataList") or []

    def field(pattern: str) -> str | None:
        rx = re.compile(pattern, re.I)
        for d in items:
            if d.get("title") and rx.search(d["title"]):
                return str(d.get("value") or "")
        return None

    lot = _num(field(r"^Bid Lot")) or _num(field(r"^Lot Size")) or _num(field(r"^Minimum Order Quantity"))
    discount_text = field(r"^Discount") or ""
    discount = _num(discount_text) if re.search(r"employee", discount_text, re.I) else None

    bids = payload.get("bidDetails") or []
    # ``activeCat`` holds subscription across all exchanges; ``bidDetails`` counts NSE bids only.
    consolidated = [
        {"category": r.get("category"), "noOfSharesOffered": r.get("noOfShareOffered"), "noOfTime": r.get("noOfTotalMeant")}
        for r in ((payload.get("activeCat") or {}).get("dataList") or [])
        if r.get("srNo") not in ("Sr.No.", None) or r.get("category") == "Total"
    ]

    def cat(pattern: str, rows=None) -> dict | None:
        rx = re.compile(pattern, re.I)
        return next((b for b in (rows if rows is not None else bids) if rx.search(b.get("category") or "")), None)

    def sub(pattern: str) -> float | None:
        return _times(cat(pattern, consolidated)) if consolidated else _times(cat(pattern))

    emp, sh = cat(r"^Employee"), cat(r"^Shareholder")
    categories = (field(r"^Categories") or "").upper()
    return {
        "isin": (meta.get("isin") or "").strip(),
        "listing_date": _nse_date(meta.get("listingDate")),
        "lot_size": int(lot) if lot else None,
        "employee_discount": discount or 0.0,
        "has_employee_quota": bool(emp and _num(emp.get("noOfSharesOffered"))) or "EMP" in categories,
        "has_shareholder_quota": bool(sh and _num(sh.get("noOfSharesOffered"))) or "SHA" in categories,
        "sub_individual": sub(r"Retail Individual|Individual Investor"),
        "sub_snii": sub(r"Two Lakh"),
        "sub_bnii": sub(r"more than Ten Lakh"),
        "sub_qib": sub(r"^Qualified"),
        "sub_total": sub(r"^Total"),
    }


class NseClient:
    def __init__(self, client: httpx.Client, pause: float = 0.4):
        self.client = client
        self.pause = pause
        self._warm = False

    def _json(self, path: str):
        if not self._warm:
            self.client.get(BASE + "/market-data/all-upcoming-issues-ipo")
            self._warm = True
        data = get_bytes(self.client, BASE + path, headers={"Referer": BASE + "/market-data/all-upcoming-issues-ipo", "Accept": "application/json"})
        time.sleep(self.pause)
        import json

        return json.loads(data)

    def past_issues(self, start: date, end: date) -> list[dict]:
        return self._json(f"/api/public-past-issues?from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}")

    def ipo_detail(self, symbol: str, series: str) -> dict:
        return self._json(f"/api/ipo-detail?symbol={symbol}&series={series}")


def collect(nse: NseClient, start: date, end: date, log=print) -> list[dict]:
    """Every listed equity IPO between ``start`` and ``end`` (by listing date), with details."""
    records = []
    for issue in parse_past_issues(nse.past_issues(start, end)):
        if not (start <= issue["listing_date"] <= end):
            continue
        try:
            detail = parse_ipo_detail(nse.ipo_detail(issue["nse_symbol"], issue["series"]))
        except Exception as e:  # keep going; the issue is reported and can be retried
            log(f"  ! {issue['nse_symbol']}: {e}")
            continue
        if not detail["isin"] or not detail["lot_size"]:
            log(f"  ! {issue['nse_symbol']}: missing ISIN or lot size, skipped (add it by hand with source=manual)")
            continue
        if detail["isin"].startswith("IN9"):  # partly paid shares from a rights issue, not an IPO
            continue
        rec = {**issue, **{k: v for k, v in detail.items() if v is not None}}
        rec.pop("series", None)
        rec["source"] = "nse_api"
        records.append(rec)
    return records
