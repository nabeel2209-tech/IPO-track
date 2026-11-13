"""Listing-day and latest returns for every IPO, computed with a handful of queries.

Loading every price row to build the list page would be wasteful, so this pulls only two prices
per IPO (listing day and latest) plus the corporate actions, and adjusts in Python.
"""

from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CorporateAction, Ipo, Price
from app.services.categories import categories_for
from app.services.pnl import terms_from_ipo
from app.services.prices import EXCHANGE_PREFERENCE, share_multiplier_on


def _pick(rows: list[Price]) -> Price | None:
    if not rows:
        return None
    return sorted(rows, key=lambda r: EXCHANGE_PREFERENCE.index(r.exchange))[0]


def build_summaries(session: Session, ipos: list[Ipo]) -> list[dict]:
    isins = [i.isin for i in ipos]
    if not isins:
        return []

    listing_rows = session.execute(select(Price).join(Ipo, (Ipo.isin == Price.isin) & (Ipo.listing_date == Price.trade_date)).where(Price.isin.in_(isins))).scalars()
    listing_by_isin: dict[str, list[Price]] = defaultdict(list)
    for r in listing_rows:
        listing_by_isin[r.isin].append(r)

    latest_day = select(Price.isin, func.max(Price.trade_date).label("d")).where(Price.isin.in_(isins)).group_by(Price.isin).subquery()
    latest_rows = session.execute(select(Price).join(latest_day, (latest_day.c.isin == Price.isin) & (latest_day.c.d == Price.trade_date))).scalars()
    latest_by_isin: dict[str, list[Price]] = defaultdict(list)
    for r in latest_rows:
        latest_by_isin[r.isin].append(r)

    actions_by_isin: dict[str, list[CorporateAction]] = defaultdict(list)
    for a in session.execute(select(CorporateAction).where(CorporateAction.isin.in_(isins))).scalars():
        actions_by_isin[a.isin].append(a)

    out = []
    for ipo in ipos:
        lp = _pick(listing_by_isin.get(ipo.isin, []))
        latest = _pick(latest_by_isin.get(ipo.isin, []))
        acts = actions_by_isin.get(ipo.isin, [])
        listing_adj = lp.close * share_multiplier_on(acts, lp.trade_date) if lp else None
        latest_adj = latest.close * share_multiplier_on(acts, latest.trade_date) if latest else None
        first_cat = categories_for(terms_from_ipo(ipo))[0]
        out.append(
            {
                "isin": ipo.isin,
                "company": ipo.company,
                "segment": ipo.segment,
                "nse_symbol": ipo.nse_symbol,
                "bse_code": ipo.bse_code,
                "listing_date": ipo.listing_date,
                "issue_price": ipo.issue_price,
                "lot_size": ipo.lot_size,
                "min_investment": first_cat.shares(ipo.lot_size) * first_cat.buy_price,
                "listing_close": lp.close if lp else None,
                "listing_return": (listing_adj / ipo.issue_price - 1) if listing_adj else None,
                "latest_date": latest.trade_date if latest else None,
                "latest_adj_close": round(latest_adj, 4) if latest_adj else None,
                "latest_return": (latest_adj / ipo.issue_price - 1) if latest_adj else None,
            }
        )
    return out


def latest_price_date(session: Session) -> date | None:
    return session.execute(select(func.max(Price.trade_date))).scalar_one_or_none()
