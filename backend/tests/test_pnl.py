from datetime import date

import pytest
from sqlalchemy import select

from app.models import Ipo
from app.services.pnl import DateOutOfRange, pnl_for
from app.services.prices import load_series


def ipo(session, isin):
    return session.execute(select(Ipo).where(Ipo.isin == isin)).scalar_one()


def cat(day, key):
    return next(c for c in day.categories if c.key == key)


def test_listing_day_and_latest(seeded):
    jio = ipo(seeded, "INE0BJO01010")
    res = pnl_for(jio, load_series(seeded, jio.isin))
    assert res["listing"].trade_date == date(2026, 10, 28)
    retail = cat(res["listing"], "individual")
    assert (retail.lots, retail.shares, retail.invested) == (1, 12, 13428.0)
    assert retail.pnl == pytest.approx(12 * (1417.35 - 1119))
    assert res["latest"].trade_date == date(2026, 10, 30)
    snii = cat(res["latest"], "snii")
    assert snii.shares == 180 and snii.pnl == pytest.approx(180 * (1431.20 - 1119))
    emp = cat(res["latest"], "employee")
    assert emp.invested == 12 * 1065 and emp.pnl == pytest.approx(12 * (1431.20 - 1065))


def test_split_is_adjusted(seeded):
    # 1:10 split on 25 Aug 2026: one lot of 18 shares became 180 shares.
    ww = ipo(seeded, "INE0LZF01039")
    res = pnl_for(ww, load_series(seeded, ww.isin), date(2026, 8, 25))
    day = res["on_date"]
    assert day.close == 104.30 and day.adj_close == pytest.approx(1043.0)
    assert cat(day, "individual").pnl == pytest.approx(18 * (1043.0 - 808))


def test_bonus_is_adjusted_from_ex_date(seeded):
    a = ipo(seeded, "INE2FMX01012")
    series = load_series(seeded, a.isin)
    before = pnl_for(a, series, date(2026, 9, 25))["on_date"]
    after = pnl_for(a, series, date(2026, 9, 28))["on_date"]
    assert before.adj_close == pytest.approx(72.74)
    assert after.adj_close == pytest.approx(39.31 * 2)


def test_weekend_uses_last_trading_day(seeded):
    jio = ipo(seeded, "INE0BJO01010")
    day = pnl_for(jio, load_series(seeded, jio.isin), date(2026, 10, 31))["on_date"]  # a Saturday
    assert day.requested == date(2026, 10, 31) and day.trade_date == date(2026, 10, 30)


def test_date_before_listing_is_rejected(seeded):
    jio = ipo(seeded, "INE0BJO01010")
    with pytest.raises(DateOutOfRange):
        pnl_for(jio, load_series(seeded, jio.isin), date(2026, 10, 1))


def test_no_prices_yet(seeded):
    sme = ipo(seeded, "INE1UEL01023")
    res = pnl_for(sme, load_series(seeded, sme.isin))
    assert res["listing"] is None and res["latest"] is None
