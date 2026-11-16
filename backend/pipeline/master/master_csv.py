"""The IPO master list lives in ``data/ipo_master.csv``, checked into git.

Keeping it as a reviewed CSV ("data as code") means every change to an IPO's details shows up as a
diff in a pull request. Each collector only rewrites the rows it created (``source`` = ``nse_api``
or ``bse_api``); rows a person has corrected by hand (``source`` = ``manual``) are never overwritten.
"""

import csv
import re
from datetime import date
from pathlib import Path

COLUMNS = [
    "isin",
    "company",
    "segment",
    "nse_symbol",
    "bse_code",
    "exchanges",
    "issue_open",
    "issue_close",
    "listing_date",
    "issue_price",
    "price_band_low",
    "price_band_high",
    "lot_size",
    "has_employee_quota",
    "employee_discount",
    "has_shareholder_quota",
    "individual_min_lots",
    "snii_min_lots",
    "bnii_min_lots",
    "sub_individual",
    "sub_snii",
    "sub_bnii",
    "sub_qib",
    "sub_total",
    "source",
    "notes",
]
DATE_COLS = {"issue_open", "issue_close", "listing_date"}
FLOAT_COLS = {"issue_price", "price_band_low", "price_band_high", "employee_discount", "sub_individual", "sub_snii", "sub_bnii", "sub_qib", "sub_total"}
INT_COLS = {"lot_size", "individual_min_lots", "snii_min_lots", "bnii_min_lots"}
BOOL_COLS = {"has_employee_quota", "has_shareholder_quota"}
ISIN_RE = re.compile(r"^IN[A-Z0-9]{9}[0-9]$")


def _to_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _from_cell(col: str, v: str):
    v = (v or "").strip()
    if col in BOOL_COLS:
        return v.lower() in ("yes", "true", "1")
    if v == "":
        return 0.0 if col == "employee_discount" else None
    if col in DATE_COLS:
        return date.fromisoformat(v)
    if col in FLOAT_COLS:
        return float(v)
    if col in INT_COLS:
        return int(float(v))
    return v


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [{c: _from_cell(c, row.get(c, "")) for c in COLUMNS} for row in csv.DictReader(fh)]


def write(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = sorted(records, key=lambda r: (r["listing_date"], r["company"]))
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in records:
            w.writerow({c: _to_cell(r.get(c)) for c in COLUMNS})


def merge(existing: list[dict], collected: list[dict]) -> tuple[list[dict], int, int]:
    """Add new IPOs and refresh rows the collector owns. Returns (records, added, updated).

    A collector owns the rows it created (same ``source``) and may change them. In a row owned by
    someone else (another collector, or a person: ``source`` = ``manual``) it only fills blank cells,
    so nothing a person typed is ever overwritten.
    """
    by_isin = {r["isin"]: r for r in existing}
    added = updated = 0
    for new in collected:
        old = by_isin.get(new["isin"])
        if old is None:
            row = {c: new.get(c) for c in COLUMNS}
            row["exchanges"] = row.get("exchanges") or "NSE,BSE"
            by_isin[new["isin"]] = row
            added += 1
            continue
        owner = old.get("source") == new.get("source")
        changed = False
        for c in COLUMNS:
            if c in ("source", "notes") or new.get(c) is None or old.get(c) == new[c]:
                continue
            if owner or old.get(c) in (None, ""):
                old[c] = new[c]
                changed = True
        updated += int(changed)
    return list(by_isin.values()), added, updated


def problems(records: list[dict]) -> list[str]:
    """Checks that should never fail for a correct row."""
    out = []
    seen = set()
    for r in records:
        tag = f"{r.get('company')} ({r.get('isin')})"
        if not ISIN_RE.match(r.get("isin") or ""):
            out.append(f"{tag}: ISIN looks wrong")
        if r["isin"] in seen:
            out.append(f"{tag}: duplicate ISIN")
        seen.add(r["isin"])
        if r.get("segment") not in ("mainboard", "sme"):
            out.append(f"{tag}: segment must be mainboard or sme")
        if not r.get("issue_price") or r["issue_price"] <= 0:
            out.append(f"{tag}: issue price missing")
        if not r.get("lot_size") or r["lot_size"] <= 0:
            out.append(f"{tag}: lot size missing")
        if r.get("issue_close") and r.get("listing_date") and r["listing_date"] < r["issue_close"]:
            out.append(f"{tag}: listed before the issue closed")
        lo, hi = r.get("price_band_low"), r.get("price_band_high")
        if lo and hi and r.get("issue_price") and not (lo - 0.01 <= r["issue_price"] <= hi + 0.01):
            out.append(f"{tag}: issue price {r['issue_price']} outside band {lo}-{hi} (check for a revised band)")
    return out
