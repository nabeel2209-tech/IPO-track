"""Read-only endpoints for IPOs, their categories, P&L and prices."""

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import schemas
from app.db import get_session
from app.models import CorporateAction, IngestionRun, Ipo
from app.services.categories import categories_for
from app.services.pnl import DateOutOfRange, pnl_for, terms_from_ipo
from app.services.prices import load_series
from app.services.summary import build_summaries, latest_price_date

router = APIRouter(prefix="/api", tags=["ipos"])

SortKey = Literal["listing_date", "listing_return", "latest_return", "company"]


def _get_ipo(session: Session, isin: str) -> Ipo:
    ipo = session.execute(select(Ipo).where(Ipo.isin == isin.upper())).scalar_one_or_none()
    if ipo is None:
        raise HTTPException(status_code=404, detail=f"No IPO with ISIN {isin}")
    return ipo


@router.get("/ipos", response_model=schemas.IpoList)
def list_ipos(
    segment: Literal["mainboard", "sme"] | None = None,
    year: int | None = Query(None, ge=2000, le=2100),
    q: str | None = Query(None, max_length=80, description="Search company name or symbol"),
    sort: SortKey = "listing_date",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    stmt = select(Ipo)
    if segment:
        stmt = stmt.where(Ipo.segment == segment)
    if year:
        stmt = stmt.where(Ipo.listing_date >= date(year, 1, 1), Ipo.listing_date <= date(year, 12, 31))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Ipo.company.ilike(like), Ipo.nse_symbol.ilike(like), Ipo.bse_code.ilike(like)))
    ipos = session.execute(stmt).scalars().all()
    rows = build_summaries(session, list(ipos))

    reverse = order == "desc"
    if sort == "company":
        rows.sort(key=lambda r: r["company"].lower(), reverse=reverse)
    else:
        # IPOs without prices yet go to the end whichever way we sort.
        with_val = [r for r in rows if r[sort] is not None]
        without = [r for r in rows if r[sort] is None]
        with_val.sort(key=lambda r: r[sort], reverse=reverse)
        rows = with_val + without
    return {"items": rows[offset : offset + limit], "total": len(rows)}


@router.get("/ipos/{isin}", response_model=schemas.IpoDetail)
def get_ipo(isin: str, session: Session = Depends(get_session)):
    ipo = _get_ipo(session, isin)
    series = load_series(session, ipo.isin)
    cats = categories_for(terms_from_ipo(ipo))
    plain = ("isin", "company", "segment", "nse_symbol", "bse_code", "exchanges", "issue_open", "issue_close", "listing_date")
    plain += ("issue_price", "price_band_low", "price_band_high", "lot_size", "notes")
    return {
        **{c: getattr(ipo, c) for c in plain},
        "employee_discount": ipo.employee_discount or 0.0,
        "categories": [
            {
                "key": c.key,
                "label": c.label,
                "eligibility": c.eligibility,
                "min_lots": c.min_lots,
                "max_lots": c.max_lots,
                "shares": c.shares(ipo.lot_size),
                "buy_price": c.buy_price,
                "amount": round(c.shares(ipo.lot_size) * c.buy_price, 2),
            }
            for c in cats
        ],
        "subscription": {"individual": ipo.sub_individual, "snii": ipo.sub_snii, "bnii": ipo.sub_bnii, "qib": ipo.sub_qib, "total": ipo.sub_total},
        "first_price_date": series[0].trade_date if series else None,
        "latest_price_date": series[-1].trade_date if series else None,
    }


@router.get("/ipos/{isin}/pnl", response_model=schemas.PnlOut)
def get_pnl(
    isin: str,
    on: date | None = Query(None, alias="date", description="Any date on or after listing (YYYY-MM-DD)"),
    session: Session = Depends(get_session),
):
    ipo = _get_ipo(session, isin)
    series = load_series(session, ipo.isin)
    try:
        res = pnl_for(ipo, series, on)
    except DateOutOfRange as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"isin": ipo.isin, "listing": res["listing"], "latest": res["latest"], "on_date": res["on_date"]}


@router.get("/ipos/{isin}/prices", response_model=schemas.PriceSeries)
def get_prices(isin: str, session: Session = Depends(get_session)):
    ipo = _get_ipo(session, isin)
    series = load_series(session, ipo.isin)
    actions = session.execute(select(CorporateAction).where(CorporateAction.isin == ipo.isin).order_by(CorporateAction.ex_date)).scalars().all()
    return {
        "isin": ipo.isin,
        "issue_price": ipo.issue_price,
        "points": [{"date": p.trade_date, "close": p.close, "adj_close": round(p.adj_close, 4), "exchange": p.exchange} for p in series],
        "corporate_actions": [{"ex_date": a.ex_date, "kind": a.kind, "share_multiplier": a.share_multiplier, "description": a.description} for a in actions],
    }


@router.get("/meta", response_model=schemas.Meta)
def get_meta(session: Session = Depends(get_session)):
    counts = dict(session.execute(select(Ipo.segment, func.count()).group_by(Ipo.segment)).all())
    last_ok = session.execute(select(func.max(IngestionRun.trade_date)).where(IngestionRun.status == "ok")).scalar_one_or_none()
    since = date.today() - timedelta(days=30)
    failed = session.execute(select(func.count(func.distinct(IngestionRun.trade_date))).where(IngestionRun.status == "failed", IngestionRun.trade_date >= since)).scalar_one()
    return {
        "ipo_count": sum(counts.values()),
        "mainboard_count": counts.get("mainboard", 0),
        "sme_count": counts.get("sme", 0),
        "latest_price_date": latest_price_date(session),
        "last_successful_ingest": last_ok,
        "failed_days_last_30": failed,
    }
