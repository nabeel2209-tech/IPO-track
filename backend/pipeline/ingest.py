"""Price ingestion: download bhavcopy files day by day, load them, log every attempt.

Properties that matter in production:
- Idempotent: loading a day twice gives the same rows (upsert on isin + date + exchange).
- Resumable: days already loaded successfully are skipped unless ``force`` is set.
- Fault tolerant: one exchange failing doesn't stop the other; failures are logged and the next
  run retries them; a Yahoo pass fills whatever both exchanges missed.
- Self-healing: an IPO added to the master list later gets its history from the saved raw files
  (``catch_up``), without downloading every day again.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CorporateAction, HistoryLoad, IngestionRun, Ipo, Price
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


def loaded_days(session: Session) -> dict[str, set[date]]:
    """For each source, the days its file was loaded successfully."""
    out: dict[str, set[date]] = {}
    for source, day in session.execute(select(IngestionRun.source, IngestionRun.trade_date).where(IngestionRun.status == "ok")):
        out.setdefault(source, set()).add(day)
    return out


def _sources_for(ipo: Ipo, sources: list[BhavcopySource]) -> list[BhavcopySource]:
    """The exchange files this IPO can appear in ("BSE" for a BSE SME stock, both for most others)."""
    where = {x.strip().upper() for x in (ipo.exchanges or "NSE,BSE").split(",")}
    return [s for s in sources if s.exchange in where]


def catch_up(session: Session, client: httpx.Client, raw_dir: Path, *, sources: list[BhavcopySource] | None = None, log=print, sleep=None) -> int:
    """Load history for IPOs that joined the master list after their trading days were ingested.

    ``ingest_day`` skips a day once its file is loaded, and it only keeps rows for the IPOs known at
    that moment. So a newly added IPO would never get its earlier prices. For every IPO not yet
    recorded in ``history_loads`` this re-reads the saved file (downloading only if one is missing)
    of each loaded day since it listed, then records the IPO as done. An IPO is recorded only if
    every file was read, so a failure is retried on the next run.

    It doesn't guess from the prices already held: a new IPO may already have today's price (today
    was loaded after it was added) and still be missing everything before.
    """
    sources = sources or list(SOURCES.values())
    loaded = loaded_days(session)
    done = set(session.execute(select(HistoryLoad.isin)).scalars())
    pending = [ipo for ipo in session.execute(select(Ipo)).scalars() if ipo.isin not in done]
    todo: dict[tuple[str, date], set[str]] = {}  # (source, day) → ISINs to look for
    for ipo in pending:
        for src in _sources_for(ipo, sources):
            for d in loaded.get(src.name, set()):
                if d >= ipo.listing_date:
                    todo.setdefault((src.name, d), set()).add(ipo.isin)
    by_name = {s.name: s for s in sources}
    total = 0
    incomplete: set[str] = set()
    for (name, day), isins in sorted(todo.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        try:
            payload = by_name[name].fetch(client, day, raw_dir, sleep=sleep)
            rows = [r for r in udiff.parse(udiff.decode(payload), isins) if r.trade_date == day]
        except (FetchError, ValueError) as e:
            log(f"  ! catch-up {name} {day}: {e}")
            incomplete |= isins
            continue
        total += upsert_prices(session, rows, name)
    for ipo in pending:
        if ipo.isin not in incomplete:
            session.add(HistoryLoad(isin=ipo.isin))
    session.commit()
    if todo:
        log(f"catch-up: re-read {len(todo)} saved files for {len(pending)} IPOs without full history, loaded {total} price rows")
    return total


def missing_days(session: Session, ipo: Ipo, days: list[date]) -> list[date]:
    have = set(session.execute(select(Price.trade_date).where(Price.isin == ipo.isin)).scalars())
    return [d for d in days if d >= ipo.listing_date and d not in have]


def yahoo_gaps(ipo: Ipo, missing: list[date], loaded: dict[str, set[date]]) -> list[date]:
    """Which missing days are worth asking Yahoo about.

    A mainboard stock trades every day, so any missing day is a gap. Many SME stocks don't trade
    every day, and a stock that didn't trade isn't in the exchange file. For SME stocks a missing
    day is a gap only if the listing day itself is missing, or the exchange file for that day was
    never loaded.
    """
    if ipo.segment != "sme" or ipo.listing_date in missing:
        return missing
    covered = set().union(*(loaded.get(s.name, set()) for s in _sources_for(ipo, list(SOURCES.values()))))
    return [d for d in missing if d not in covered]


def fill_gaps_with_yahoo(session: Session, *, log=print, downloader=None) -> int:
    """For each IPO, fetch Yahoo prices for trading days the exchange files didn't cover."""
    days = trading_days(session)
    loaded = loaded_days(session)
    total = 0
    for ipo in session.execute(select(Ipo)).scalars().all():
        gaps = yahoo_gaps(ipo, missing_days(session, ipo, days), loaded)
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
