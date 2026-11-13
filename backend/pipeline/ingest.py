"""Price ingestion: download bhavcopy files day by day, load them, log every attempt.

Properties that matter in production:
- Idempotent: loading a day twice gives the same rows (upsert on isin + date + exchange).
- Resumable: days already loaded successfully are skipped unless ``force`` is set.
- Fault tolerant: one exchange failing doesn't stop the other; failures are logged and the next
  run retries them; a Yahoo pass fills whatever both exchanges missed.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CorporateAction, IngestionRun, Ipo, Price
from pipeline.http import FetchError, NoFile
from pipeline.load import upsert_prices
from pipeline.sources import udiff
from pipeline.sources.exchanges import SOURCES, BhavcopySource
from pipeline.sources.yahoo import fetch_history, ticker_for


@dataclass
class DayResult:
    day: date
    status: dict[str, str] = field(default_factory=dict)
    rows: dict[str, int] = field(default_factory=dict)


def weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:  # exchanges are shut on weekends; holidays show up as "no file"
            yield d
        d += timedelta(days=1)


def wanted_isins(session: Session) -> set[str]:
    return set(session.execute(select(Ipo.isin)).scalars())


def _already_done(session: Session, source: str, day: date) -> bool:
    return session.execute(select(IngestionRun.id).where(IngestionRun.source == source, IngestionRun.trade_date == day, IngestionRun.status.in_(("ok", "no_file")))).first() is not None


def _log(session: Session, source: str, day: date, status: str, rows: int = 0, message: str | None = None) -> None:
    session.add(IngestionRun(source=source, trade_date=day, status=status, rows_loaded=rows, message=message))


def ingest_day(
    session: Session,
    client: httpx.Client,
    day: date,
    raw_dir: Path,
    isins: set[str],
    sources: list[BhavcopySource] | None = None,
    force: bool = False,
    sleep: Callable[[float], None] | None = None,
) -> DayResult:
    res = DayResult(day)
    for src in sources or list(SOURCES.values()):
        if not force and _already_done(session, src.name, day):
            res.status[src.name] = "skipped"
            continue
        try:
            payload = src.fetch(client, day, raw_dir, sleep=sleep)
            rows = [r for r in udiff.parse(udiff.decode(payload), isins) if r.trade_date == day]
            n = upsert_prices(session, rows, src.name)
            _log(session, src.name, day, "ok", n)
            res.status[src.name], res.rows[src.name] = "ok", n
        except NoFile:
            _log(session, src.name, day, "no_file", 0, "no file published (holiday?)")
            res.status[src.name] = "no_file"
        except (FetchError, ValueError) as e:
            _log(session, src.name, day, "failed", 0, str(e)[:500])
            res.status[src.name] = "failed"
        session.commit()
    return res


def backfill(session: Session, client: httpx.Client, start: date, end: date, raw_dir: Path, *, force: bool = False, log=print, sleep=None) -> list[DayResult]:
    isins = wanted_isins(session)
    out = []
    for day in weekdays(start, end):
        r = ingest_day(session, client, day, raw_dir, isins, force=force, sleep=sleep)
        log(f"{day}  " + "  ".join(f"{k}={v}{'(' + str(r.rows[k]) + ')' if k in r.rows else ''}" for k, v in r.status.items()))
        out.append(r)
    return out


def trading_days(session: Session) -> list[date]:
    """Days at least one exchange published a file for, i.e. days the market was open."""
    return sorted(set(session.execute(select(IngestionRun.trade_date).where(IngestionRun.status == "ok")).scalars()))


def missing_days(session: Session, ipo: Ipo, days: list[date]) -> list[date]:
    have = set(session.execute(select(Price.trade_date).where(Price.isin == ipo.isin)).scalars())
    return [d for d in days if d >= ipo.listing_date and d not in have]


def fill_gaps_with_yahoo(session: Session, *, log=print, downloader=None) -> int:
    """For each IPO, fetch Yahoo prices for trading days neither exchange file covered."""
    days = trading_days(session)
    total = 0
    for ipo in session.execute(select(Ipo)).scalars().all():
        gaps = missing_days(session, ipo, days)
        if not gaps:
            continue
        t = ticker_for(ipo.nse_symbol, ipo.bse_code)
        if t is None:
            continue
        ticker, exchange = t
        actions = [(a.ex_date, a.share_multiplier) for a in session.execute(select(CorporateAction).where(CorporateAction.isin == ipo.isin)).scalars()]
        try:
            rows = fetch_history(ipo.isin, ticker, exchange, gaps[0], gaps[-1], actions, downloader=downloader)
        except Exception as e:  # Yahoo is best-effort
            log(f"  ! yahoo {ticker}: {e}")
            continue
        wanted = set(gaps)
        rows = [r for r in rows if r.trade_date in wanted]
        upsert_prices(session, rows, "yahoo", overwrite=False)
        session.commit()
        if rows:
            log(f"  yahoo {ticker}: filled {len(rows)} of {len(gaps)} missing days")
        total += len(rows)
    return total
