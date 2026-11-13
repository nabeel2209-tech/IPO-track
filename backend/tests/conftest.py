"""Shared test setup: a fresh in-memory database seeded with real exchange data.

The prices come from real BSE bhavcopy rows (tests/fixtures/bse_udiff_sample.csv) for Jio
Platforms, Nityas Gems, Waterways Leisure Tourism (1:10 split) and Aastha Spintex (1:1 bonus).
"""

import os
from datetime import date
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")  # never touch the real database in tests

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.main import app
from pipeline.load import replace_corporate_actions, upsert_ipos, upsert_prices
from pipeline.sources import udiff

FIXTURES = Path(__file__).parent / "fixtures"

IPOS = [
    dict(
        isin="INE0BJO01010",
        company="Jio Platforms Limited",
        segment="mainboard",
        nse_symbol="JPL",
        bse_code="545004",
        exchanges="NSE,BSE",
        issue_open=date(2026, 10, 21),
        issue_close=date(2026, 10, 23),
        listing_date=date(2026, 10, 28),
        issue_price=1119.0,
        price_band_low=1065.0,
        price_band_high=1119.0,
        lot_size=12,
        has_employee_quota=True,
        employee_discount=54.0,
        has_shareholder_quota=True,
        source="nse_api",
    ),
    dict(
        isin="INE211501023",
        company="Nityas Gems and Jewellery Limited",
        segment="mainboard",
        nse_symbol="NITYAS",
        bse_code="544974",
        exchanges="NSE,BSE",
        issue_open=date(2026, 9, 30),
        issue_close=date(2026, 10, 5),
        listing_date=date(2026, 10, 8),
        issue_price=75.0,
        price_band_low=70.0,
        price_band_high=75.0,
        lot_size=200,
        has_employee_quota=True,
        employee_discount=7.0,
        has_shareholder_quota=False,
        source="nse_api",
    ),
    dict(
        isin="INE0LZF01039",
        company="Waterways Leisure Tourism Limited",
        segment="mainboard",
        nse_symbol="CORDELIA",
        bse_code="544802",
        exchanges="NSE,BSE",
        issue_open=date(2026, 6, 23),
        issue_close=date(2026, 6, 25),
        listing_date=date(2026, 7, 1),
        issue_price=808.0,
        price_band_low=769.0,
        price_band_high=808.0,
        lot_size=18,
        has_employee_quota=False,
        employee_discount=0.0,
        has_shareholder_quota=False,
        source="nse_api",
    ),
    dict(
        isin="INE2FMX01012",
        company="Aastha Spintex Limited",
        segment="mainboard",
        nse_symbol="AASTHA",
        bse_code="544808",
        exchanges="NSE,BSE",
        issue_open=date(2026, 6, 29),
        issue_close=date(2026, 7, 1),
        listing_date=date(2026, 7, 6),
        issue_price=136.0,
        price_band_low=125.0,
        price_band_high=136.0,
        lot_size=110,
        has_employee_quota=False,
        employee_discount=0.0,
        has_shareholder_quota=False,
        source="nse_api",
    ),
    dict(
        isin="INE1UEL01023",
        company="Ravita Engineering Services Limited",
        segment="sme",
        nse_symbol="RAVITA",
        bse_code=None,
        exchanges="NSE",
        issue_open=date(2026, 10, 14),
        issue_close=date(2026, 10, 16),
        listing_date=date(2026, 10, 22),
        issue_price=112.0,
        price_band_low=105.0,
        price_band_high=112.0,
        lot_size=1200,
        has_employee_quota=False,
        employee_discount=0.0,
        has_shareholder_quota=False,
        source="nse_api",
    ),
]

ACTIONS = [
    dict(isin="INE0LZF01039", ex_date=date(2026, 8, 25), kind="split", share_multiplier=10.0, description="1:10 split"),
    dict(isin="INE2FMX01012", ex_date=date(2026, 9, 28), kind="bonus", share_multiplier=2.0, description="1:1 bonus"),
]


@pytest.fixture()
def engine():
    from app import models  # noqa: F401  (register tables)

    # StaticPool: one shared in-memory connection, so every session sees the same data
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def session(session_factory):
    with session_factory() as s:
        yield s


@pytest.fixture()
def bse_text() -> str:
    return (FIXTURES / "bse_udiff_sample.csv").read_text()


@pytest.fixture()
def seeded(session, bse_text):
    upsert_ipos(session, IPOS)
    upsert_prices(session, udiff.parse(bse_text), "bse_bhavcopy")
    replace_corporate_actions(session, ACTIONS)
    session.commit()
    return session


@pytest.fixture()
def client(seeded, session_factory):
    def _session():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
