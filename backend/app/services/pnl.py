"""Profit and loss for each investor category on a given day."""

from dataclasses import dataclass
from datetime import date

from app.models import Ipo
from app.services.categories import Category, IssueTerms, categories_for
from app.services.prices import PricePoint, point_on_or_before


def terms_from_ipo(ipo: Ipo) -> IssueTerms:
    return IssueTerms(
        segment=ipo.segment,
        issue_price=ipo.issue_price,
        lot_size=ipo.lot_size,
        issue_open=ipo.issue_open,
        has_employee_quota=ipo.has_employee_quota,
        employee_discount=ipo.employee_discount or 0.0,
        has_shareholder_quota=ipo.has_shareholder_quota,
        individual_min_lots=ipo.individual_min_lots,
        snii_min_lots=ipo.snii_min_lots,
        bnii_min_lots=ipo.bnii_min_lots,
    )


@dataclass(frozen=True)
class CategoryPnl:
    key: str
    lots: int
    shares: int
    invested: float
    value: float
    pnl: float
    pnl_pct: float


@dataclass(frozen=True)
class DayPnl:
    requested: date
    trade_date: date  # the trading day actually used (may be earlier than requested)
    close: float
    adj_close: float
    exchange: str
    categories: list[CategoryPnl]


def category_pnl(cat: Category, lot_size: int, adj_close: float) -> CategoryPnl:
    shares = cat.shares(lot_size)
    invested = shares * cat.buy_price
    value = shares * adj_close
    pnl = value - invested
    return CategoryPnl(cat.key, cat.min_lots, shares, round(invested, 2), round(value, 2), round(pnl, 2), round(pnl / invested, 6) if invested else 0.0)


def day_pnl(categories: list[Category], lot_size: int, point: PricePoint, requested: date) -> DayPnl:
    return DayPnl(
        requested=requested,
        trade_date=point.trade_date,
        close=point.close,
        adj_close=round(point.adj_close, 4),
        exchange=point.exchange,
        categories=[category_pnl(c, lot_size, point.adj_close) for c in categories],
    )


class DateOutOfRange(ValueError):
    pass


def pnl_for(ipo: Ipo, series: list[PricePoint], on: date | None = None) -> dict:
    """P&L on listing day, on the latest available day, and (optionally) on ``on``."""
    cats = categories_for(terms_from_ipo(ipo))
    result: dict = {"categories": cats, "listing": None, "latest": None, "on_date": None}
    if not series:
        return result
    listing_point = next((p for p in series if p.trade_date == ipo.listing_date), None)
    if listing_point:
        result["listing"] = day_pnl(cats, ipo.lot_size, listing_point, ipo.listing_date)
    latest = series[-1]
    result["latest"] = day_pnl(cats, ipo.lot_size, latest, latest.trade_date)
    if on is not None:
        if on < ipo.listing_date:
            raise DateOutOfRange(f"{ipo.company} listed on {ipo.listing_date.isoformat()}; pick a date on or after that")
        point = point_on_or_before(series, on)
        if point is None:
            raise DateOutOfRange("no price available on or before that date")
        result["on_date"] = day_pnl(cats, ipo.lot_size, point, on)
    return result
