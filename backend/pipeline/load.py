"""Idempotent writes: running the same load twice leaves the database unchanged."""

from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.models import CorporateAction, Ipo, Price
from pipeline.sources.udiff import PriceRow


def _insert(session: Session):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert


def upsert_prices(session: Session, rows: Iterable[PriceRow], source: str, *, overwrite: bool = True) -> int:
    """Insert or update prices keyed on (isin, trade_date, exchange).

    ``overwrite=False`` only fills gaps; the fallback source uses it so it can never replace an
    exchange's own figure.
    """
    insert = _insert(session)
    values = [
        {
            "isin": r.isin,
            "trade_date": r.trade_date,
            "exchange": r.exchange,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "prev_close": r.prev_close,
            "volume": r.volume,
            "source": source,
        }
        for r in rows
    ]
    if not values:
        return 0
    stmt = insert(Price).values(values)
    keys = ["isin", "trade_date", "exchange"]
    if overwrite:
        update = {c: getattr(stmt.excluded, c) for c in ("open", "high", "low", "close", "prev_close", "volume", "source")}
        stmt = stmt.on_conflict_do_update(index_elements=keys, set_=update)
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=keys)
    result = session.execute(stmt)
    return result.rowcount if result.rowcount is not None and result.rowcount >= 0 else len(values)


IPO_FIELDS = [
    "isin",
    "company",
    "segment",
    "nse_symbol",
    "bse_code",
    "exchanges",
    "issue_open",
    "issue_close",
    "listing_date",
    "issue_price",
    "price_band_low",
    "price_band_high",
    "lot_size",
    "has_employee_quota",
    "employee_discount",
    "has_shareholder_quota",
    "individual_min_lots",
    "snii_min_lots",
    "bnii_min_lots",
    "sub_individual",
    "sub_snii",
    "sub_bnii",
    "sub_qib",
    "sub_total",
    "source",
    "notes",
]


def upsert_ipos(session: Session, records: Iterable[dict]) -> int:
    insert = _insert(session)
    values = [{k: r.get(k) for k in IPO_FIELDS} for r in records]
    if not values:
        return 0
    stmt = insert(Ipo).values(values)
    stmt = stmt.on_conflict_do_update(index_elements=["isin"], set_={k: getattr(stmt.excluded, k) for k in IPO_FIELDS if k != "isin"})
    session.execute(stmt)
    return len(values)


def replace_corporate_actions(session: Session, records: Iterable[dict]) -> int:
    """The CSV in git is the source of truth, so the table is rebuilt from it each time."""
    session.query(CorporateAction).delete()
    n = 0
    for r in records:
        session.add(CorporateAction(**r))
        n += 1
    return n
