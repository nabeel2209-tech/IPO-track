"""Splits and bonuses: load the reviewed list, and detect ones we might have missed.

Exchange prices are *not* adjusted for splits or bonuses, so after a 1:10 split the price drops by
about 90% overnight. If we don't know about the split, it looks like a crash. Two defences:
1. ``data/corporate_actions.csv`` lists known actions (reviewed in git).
2. ``detect`` scans prices for overnight moves larger than any circuit limit allows (20%) that no
   known action explains, and suggests the likely ratio.
"""

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CorporateAction, Ipo, Price

CIRCUIT_LIMIT = 0.20  # the widest daily price band; a bigger overnight move means something else happened
COMMON_MULTIPLIERS = [1.5, 2, 3, 4, 5, 10, 20]


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [
            {
                "isin": r["isin"].strip(),
                "ex_date": date.fromisoformat(r["ex_date"].strip()),
                "kind": r["kind"].strip(),
                "share_multiplier": float(r["share_multiplier"]),
                "description": (r.get("description") or "").strip() or None,
            }
            for r in csv.DictReader(fh)
        ]


@dataclass
class Suspect:
    isin: str
    company: str
    trade_date: date
    prev_close: float
    close: float
    suggested_multiplier: float | None


def _nearest_multiplier(ratio: float) -> float | None:
    """ratio = prev_close / close. A 1:10 split gives ~10, a 1:1 bonus ~2."""
    best = min(COMMON_MULTIPLIERS, key=lambda m: abs(m - ratio) / m)
    return best if abs(best - ratio) / best < 0.25 else None


def detect(session: Session) -> list[Suspect]:
    known = {(a.isin, a.ex_date) for a in session.execute(select(CorporateAction)).scalars()}
    names = dict(session.execute(select(Ipo.isin, Ipo.company)).all())
    listing = dict(session.execute(select(Ipo.isin, Ipo.listing_date)).all())
    out = []
    rows = session.execute(select(Price).order_by(Price.isin, Price.exchange, Price.trade_date)).scalars().all()
    prev: Price | None = None
    for r in rows:
        if r.trade_date == listing.get(r.isin):
            prev = r
            continue
        # Prefer the exchange's own previous close (in the bhavcopy); fall back to our stored row.
        before = r.prev_close
        if before is None and prev is not None and prev.isin == r.isin and prev.exchange == r.exchange:
            before = prev.close
        if before:
            move = r.close / before - 1
            if abs(move) > CIRCUIT_LIMIT + 0.05 and (r.isin, r.trade_date) not in known:
                ratio = before / r.close
                out.append(Suspect(r.isin, names.get(r.isin, r.isin), r.trade_date, before, r.close, _nearest_multiplier(ratio) if ratio > 1 else None))
        prev = r
    # one suspect per stock and day, even if both exchanges show it
    uniq = {(s.isin, s.trade_date): s for s in out}
    return sorted(uniq.values(), key=lambda s: (s.trade_date, s.company))
