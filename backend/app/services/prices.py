"""Reading prices back out of the database, adjusted for splits and bonuses."""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CorporateAction, Price

# When a stock trades on both exchanges we show NSE's price, falling back to BSE.
EXCHANGE_PREFERENCE = ("NSE", "BSE")


@dataclass(frozen=True)
class PricePoint:
    trade_date: date
    close: float  # as traded on that day
    adj_close: float  # in "original shares" terms, comparable with the issue price
    exchange: str
    source: str


def share_multiplier_on(actions: list[CorporateAction], on: date) -> float:
    """How many shares one allotted share had become by ``on`` (1.0 when nothing happened)."""
    m = 1.0
    for a in actions:
        if a.ex_date <= on:
            m *= a.share_multiplier
    return m


def load_series(session: Session, isin: str) -> list[PricePoint]:
    """One adjusted closing price per trading day, oldest first."""
    rows = session.execute(select(Price).where(Price.isin == isin).order_by(Price.trade_date)).scalars().all()
    actions = session.execute(select(CorporateAction).where(CorporateAction.isin == isin).order_by(CorporateAction.ex_date)).scalars().all()
    by_day: dict[date, Price] = {}
    for r in rows:
        current = by_day.get(r.trade_date)
        if current is None or EXCHANGE_PREFERENCE.index(r.exchange) < EXCHANGE_PREFERENCE.index(current.exchange):
            by_day[r.trade_date] = r
    out = []
    for d in sorted(by_day):
        r = by_day[d]
        m = share_multiplier_on(list(actions), d)
        out.append(PricePoint(d, r.close, r.close * m, r.exchange, r.source))
    return out


def point_on_or_before(series: list[PricePoint], on: date) -> PricePoint | None:
    """Closing price on ``on``, or on the last trading day before it (weekends, holidays)."""
    dates = [p.trade_date for p in series]
    i = bisect_right(dates, on)
    return series[i - 1] if i else None
