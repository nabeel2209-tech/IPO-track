"""Tools the AI model can call to answer questions.

Design choice: the model never writes SQL. It can only call these typed functions, whose inputs
are validated here. That keeps the database safe from prompt injection and makes every answer
traceable to a specific query (the API returns the tool calls with the answer).
"""

from datetime import date
from statistics import median
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Ipo
from app.services.categories import categories_for
from app.services.pnl import DateOutOfRange, pnl_for, terms_from_ipo
from app.services.prices import load_series
from app.services.summary import build_summaries

CATEGORY_KEYS = ["individual", "snii", "bnii", "employee", "shareholder"]

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "search_ipos",
        "description": "Find IPOs by segment, listing-date range and name, sorted by listing-day return, current return or listing date. Returns up to 20 rows with returns as percentages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "segment": {"type": "string", "enum": ["mainboard", "sme", "any"]},
                "listed_from": {"type": "string", "description": "YYYY-MM-DD"},
                "listed_to": {"type": "string", "description": "YYYY-MM-DD"},
                "name_contains": {"type": "string"},
                "sort_by": {"type": "string", "enum": ["listing_return", "latest_return", "listing_date"]},
                "order": {"type": "string", "enum": ["asc", "desc"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
    },
    {
        "name": "ipo_pnl",
        "description": (
            "Profit or loss for the minimum application in every investor category (retail/individual, small HNI, big HNI, "
            "employee, shareholder) of one IPO: on listing day, on the latest date, and optionally on a chosen date."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ipo": {"type": "string", "description": "Company name, NSE symbol or ISIN"},
                "date": {"type": "string", "description": "Optional YYYY-MM-DD on or after listing"},
            },
            "required": ["ipo"],
        },
    },
    {
        "name": "category_totals",
        "description": "Totals if someone had been allotted the minimum application in one category in every IPO matching the filters: number of IPOs, money needed, listing-day P&L and current P&L.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": CATEGORY_KEYS},
                "segment": {"type": "string", "enum": ["mainboard", "sme", "any"]},
                "listed_from": {"type": "string"},
                "listed_to": {"type": "string"},
            },
            "required": ["category"],
        },
    },
    {
        "name": "market_stats",
        "description": "Counts and medians for IPOs matching the filters: how many gained on listing day and are up today, median returns, best and worst.",
        "input_schema": {
            "type": "object",
            "properties": {
                "segment": {"type": "string", "enum": ["mainboard", "sme", "any"]},
                "listed_from": {"type": "string"},
                "listed_to": {"type": "string"},
            },
        },
    },
]


class ToolError(ValueError):
    pass


def _date(v: Any, field: str) -> date | None:
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v))
    except ValueError as e:
        raise ToolError(f"{field} must be YYYY-MM-DD") from e


def _filtered_ipos(session: Session, args: dict) -> list[Ipo]:
    stmt = select(Ipo)
    seg = args.get("segment") or "any"
    if seg not in ("mainboard", "sme", "any"):
        raise ToolError("segment must be mainboard, sme or any")
    if seg != "any":
        stmt = stmt.where(Ipo.segment == seg)
    if d := _date(args.get("listed_from"), "listed_from"):
        stmt = stmt.where(Ipo.listing_date >= d)
    if d := _date(args.get("listed_to"), "listed_to"):
        stmt = stmt.where(Ipo.listing_date <= d)
    if name := (args.get("name_contains") or "").strip():
        like = f"%{name[:60]}%"
        stmt = stmt.where(or_(Ipo.company.ilike(like), Ipo.nse_symbol.ilike(like)))
    return list(session.execute(stmt).scalars().all())


def _pct(x: float | None) -> float | None:
    return None if x is None else round(x * 100, 2)


def search_ipos(session: Session, args: dict) -> dict:
    rows = build_summaries(session, _filtered_ipos(session, args))
    sort_by = args.get("sort_by") or "listing_date"
    if sort_by not in ("listing_return", "latest_return", "listing_date"):
        raise ToolError("invalid sort_by")
    desc = (args.get("order") or "desc") == "desc"
    rows = [r for r in rows if r[sort_by] is not None]
    rows.sort(key=lambda r: r[sort_by], reverse=desc)
    limit = max(1, min(int(args.get("limit") or 10), 20))
    return {
        "count_matching": len(rows),
        "rows": [
            {
                "company": r["company"],
                "isin": r["isin"],
                "segment": r["segment"],
                "listing_date": r["listing_date"].isoformat(),
                "issue_price": r["issue_price"],
                "lot_size": r["lot_size"],
                "listing_return_pct": _pct(r["listing_return"]),
                "latest_return_pct": _pct(r["latest_return"]),
                "latest_date": r["latest_date"].isoformat() if r["latest_date"] else None,
            }
            for r in rows[:limit]
        ],
    }


def _find_ipo(session: Session, text: str) -> Ipo:
    t = (text or "").strip()
    if not t:
        raise ToolError("ipo is required")
    exact = session.execute(select(Ipo).where(or_(Ipo.isin == t.upper(), Ipo.nse_symbol == t.upper()))).scalars().first()
    if exact:
        return exact
    matches = session.execute(select(Ipo).where(Ipo.company.ilike(f"%{t[:60]}%"))).scalars().all()
    if not matches:
        raise ToolError(f"no IPO matches '{t}'")
    if len(matches) > 1:
        names = ", ".join(m.company for m in matches[:5])
        raise ToolError(f"'{t}' matches several IPOs: {names}. Ask which one.")
    return matches[0]


def ipo_pnl(session: Session, args: dict) -> dict:
    ipo = _find_ipo(session, args.get("ipo", ""))
    on = _date(args.get("date"), "date")
    try:
        res = pnl_for(ipo, load_series(session, ipo.isin), on)
    except DateOutOfRange as e:
        raise ToolError(str(e)) from e
    cats = {c.key: c for c in res["categories"]}

    def day(d):
        if d is None:
            return None
        return {
            "trade_date": d.trade_date.isoformat(),
            "close": d.close,
            "categories": {c.key: {"lots": c.lots, "shares": c.shares, "invested": c.invested, "pnl": c.pnl, "pnl_pct": _pct(c.pnl_pct)} for c in d.categories},
        }

    return {
        "company": ipo.company,
        "isin": ipo.isin,
        "segment": ipo.segment,
        "listing_date": ipo.listing_date.isoformat(),
        "issue_price": ipo.issue_price,
        "lot_size": ipo.lot_size,
        "category_labels": {k: c.label for k, c in cats.items()},
        "listing_day": day(res["listing"]),
        "latest": day(res["latest"]),
        "on_date": day(res["on_date"]),
    }


def category_totals(session: Session, args: dict) -> dict:
    key = args.get("category")
    if key not in CATEGORY_KEYS:
        raise ToolError(f"category must be one of {CATEGORY_KEYS}")
    ipos = _filtered_ipos(session, args)
    summaries = {s["isin"]: s for s in build_summaries(session, ipos)}
    n = invested = listing_pnl = latest_pnl = 0.0
    for ipo in ipos:
        s = summaries[ipo.isin]
        cat = next((c for c in categories_for(terms_from_ipo(ipo)) if c.key == key), None)
        if cat is None or s["latest_adj_close"] is None or s["listing_close"] is None:
            continue
        shares = cat.shares(ipo.lot_size)
        listing_adj = (s["listing_return"] + 1) * ipo.issue_price
        n += 1
        invested += shares * cat.buy_price
        listing_pnl += shares * (listing_adj - cat.buy_price)
        latest_pnl += shares * (s["latest_adj_close"] - cat.buy_price)
    return {
        "category": key,
        "ipos_counted": int(n),
        "money_needed": round(invested),
        "listing_day_pnl": round(listing_pnl),
        "latest_pnl": round(latest_pnl),
        "latest_return_pct": _pct(latest_pnl / invested) if invested else None,
    }


def market_stats(session: Session, args: dict) -> dict:
    rows = build_summaries(session, _filtered_ipos(session, args))
    lr = [r["listing_return"] for r in rows if r["listing_return"] is not None]
    cr = [r for r in rows if r["latest_return"] is not None]
    best = max(cr, key=lambda r: r["latest_return"], default=None)
    worst = min(cr, key=lambda r: r["latest_return"], default=None)
    return {
        "ipos": len(rows),
        "with_prices": len(cr),
        "gained_on_listing_day": sum(1 for x in lr if x > 0),
        "up_today": sum(1 for r in cr if r["latest_return"] > 0),
        "median_listing_return_pct": _pct(median(lr)) if lr else None,
        "median_latest_return_pct": _pct(median([r["latest_return"] for r in cr])) if cr else None,
        "best": {"company": best["company"], "latest_return_pct": _pct(best["latest_return"])} if best else None,
        "worst": {"company": worst["company"], "latest_return_pct": _pct(worst["latest_return"])} if worst else None,
    }


TOOLS = {"search_ipos": search_ipos, "ipo_pnl": ipo_pnl, "category_totals": category_totals, "market_stats": market_stats}


def run_tool(session: Session, name: str, args: dict) -> dict:
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        return fn(session, args or {})
    except ToolError as e:
        return {"error": str(e)}
