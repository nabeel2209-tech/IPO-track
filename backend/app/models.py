"""Database tables.

Five tables, each with one job:
- ``ipos``: one row per IPO (the "master" data: issue price, lot size, quotas...).
- ``prices``: one end-of-day price per stock, per exchange, per trading day.
- ``corporate_actions``: splits and bonuses, needed to compare today's price with the issue price.
- ``ingestion_runs``: a log of every download attempt, so failed days can be retried.
- ``history_loads``: which IPOs have had their full price history loaded (see ``ingest.catch_up``).
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Ipo(Base):
    __tablename__ = "ipos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    isin: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    company: Mapped[str] = mapped_column(String(200))
    segment: Mapped[str] = mapped_column(String(10), index=True)  # "mainboard" | "sme"
    nse_symbol: Mapped[str | None] = mapped_column(String(40), index=True)
    bse_code: Mapped[str | None] = mapped_column(String(10), index=True)
    exchanges: Mapped[str] = mapped_column(String(10), default="NSE,BSE")  # where it trades
    issue_open: Mapped[date | None] = mapped_column(Date)
    issue_close: Mapped[date | None] = mapped_column(Date)
    listing_date: Mapped[date] = mapped_column(Date, index=True)
    issue_price: Mapped[float] = mapped_column(Float)
    price_band_low: Mapped[float | None] = mapped_column(Float)
    price_band_high: Mapped[float | None] = mapped_column(Float)
    lot_size: Mapped[int] = mapped_column(Integer)

    # Reservation quotas. Not every IPO has them.
    has_employee_quota: Mapped[bool] = mapped_column(Boolean, default=False)
    employee_discount: Mapped[float] = mapped_column(Float, default=0.0)
    has_shareholder_quota: Mapped[bool] = mapped_column(Boolean, default=False)

    # Optional overrides when an offer document sets a minimum that differs from the standard rules.
    individual_min_lots: Mapped[int | None] = mapped_column(Integer)
    snii_min_lots: Mapped[int | None] = mapped_column(Integer)
    bnii_min_lots: Mapped[int | None] = mapped_column(Integer)

    # Subscription (times subscribed) per category, where the exchange published it.
    sub_individual: Mapped[float | None] = mapped_column(Float)
    sub_snii: Mapped[float | None] = mapped_column(Float)
    sub_bnii: Mapped[float | None] = mapped_column(Float)
    sub_qib: Mapped[float | None] = mapped_column(Float)
    sub_total: Mapped[float | None] = mapped_column(Float)

    source: Mapped[str] = mapped_column(String(40), default="nse_api")
    notes: Mapped[str | None] = mapped_column(Text)


class Price(Base):
    __tablename__ = "prices"
    __table_args__ = (UniqueConstraint("isin", "trade_date", "exchange", name="uq_price_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    isin: Mapped[str] = mapped_column(String(12), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    exchange: Mapped[str] = mapped_column(String(4))  # "NSE" | "BSE"
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    prev_close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20))  # "nse_bhavcopy" | "bse_bhavcopy" | "yahoo"


class CorporateAction(Base):
    """A split or bonus. ``share_multiplier`` is how many shares one pre-action share became.

    A 1:10 split (face value ₹10 → ₹1) has multiplier 10; a 1:1 bonus (one free share per share
    held) has multiplier 2.
    """

    __tablename__ = "corporate_actions"
    __table_args__ = (UniqueConstraint("isin", "ex_date", "kind", name="uq_action"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    isin: Mapped[str] = mapped_column(String(12), index=True)
    ex_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(10))  # "split" | "bonus"
    share_multiplier: Mapped[float] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(String(200))


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(20), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(12))  # "ok" | "no_file" | "failed"
    rows_loaded: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HistoryLoad(Base):
    """One row per IPO whose price history has been read from every loaded day's file.

    Daily files are loaded once and only rows for the IPOs known at that moment are kept. An IPO
    added to the master list later has no row here, which is how ``ingest.catch_up`` knows to go
    back through the saved files for it.
    """

    __tablename__ = "history_loads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    isin: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    loaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
