"""Data quality checks, run after every ingest (and in CI).

Errors mean the numbers on the site would be wrong; warnings are worth a look.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ipo, Price
from pipeline.actions import detect
from pipeline.ingest import trading_days


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # for information only

    @property
    def ok(self) -> bool:
        return not self.errors


def run(session: Session, today: date | None = None, max_exchange_gap: float = 0.03) -> Report:
    rep = Report()
    days = trading_days(session)
    last_day = days[-1] if days else None
    ipos = session.execute(select(Ipo)).scalars().all()
    quiet_sme = 0

    for ipo in ipos:
        prices = session.execute(select(Price).where(Price.isin == ipo.isin)).scalars().all()
        tag = f"{ipo.company} ({ipo.isin})"
        if last_day and ipo.listing_date <= last_day:
            if not prices:
                rep.errors.append(f"{tag}: listed {ipo.listing_date} but has no prices")
                continue
            if not any(p.trade_date == ipo.listing_date for p in prices):
                rep.errors.append(f"{tag}: no price on listing day {ipo.listing_date}")
            have = {p.trade_date for p in prices}
            gaps = [d for d in days if d >= ipo.listing_date and d not in have]
            if gaps and ipo.segment == "sme":
                quiet_sme += 1  # normal: thinly traded SME stocks skip days
            elif gaps:
                rep.warnings.append(f"{tag}: {len(gaps)} trading day(s) without a price, first {gaps[0]}")
        # NSE and BSE should agree closely on the same day
        by_day: dict[date, dict[str, float]] = {}
        for p in prices:
            by_day.setdefault(p.trade_date, {})[p.exchange] = p.close
        for d, ex in by_day.items():
            if "NSE" in ex and "BSE" in ex and abs(ex["NSE"] / ex["BSE"] - 1) > max_exchange_gap:
                rep.warnings.append(f"{tag}: NSE {ex['NSE']} vs BSE {ex['BSE']} on {d}")

    if quiet_sme:
        rep.notes.append(f"{quiet_sme} SME IPOs have days with no trades (expected for thinly traded stocks)")

    for s in detect(session):
        hint = f" - likely a split/bonus with multiplier {s.suggested_multiplier:g}" if s.suggested_multiplier else ""
        rep.errors.append(f"{s.company} ({s.isin}): price went {s.prev_close} → {s.close} on {s.trade_date} with no known corporate action{hint}")
    return rep
