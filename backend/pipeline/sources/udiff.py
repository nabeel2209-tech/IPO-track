"""Parser for the exchanges' UDiFF "common bhavcopy" files.

Since July 2024 NSE and BSE publish end-of-day prices in the same column layout (UDiFF), so one
parser serves both. Columns used: TradDt, FinInstrmTp, ISIN, TckrSymb, SctySrs, OpnPric, HghPric,
LwPric, ClsPric, PrvsClsgPric, TtlTradgVol, Src.
"""

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PriceRow:
    isin: str
    trade_date: date
    exchange: str
    symbol: str
    series: str
    open: float | None
    high: float | None
    low: float | None
    close: float
    prev_close: float | None
    volume: int | None


def _f(v: str) -> float | None:
    v = (v or "").strip()
    if not v:
        return None
    x = float(v)
    return x if x != 0 else None


def _i(v: str) -> int | None:
    v = (v or "").strip()
    return int(float(v)) if v else None


def decode(payload: bytes) -> str:
    """Bhavcopy files arrive as plain CSV (BSE) or a zip holding one CSV (NSE)."""
    if payload[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            payload = zf.read(name)
    return payload.decode("utf-8-sig", errors="replace")


def parse(text: str, wanted_isins: set[str] | None = None) -> list[PriceRow]:
    rows: list[PriceRow] = []
    reader = csv.DictReader(io.StringIO(text))
    required = {"TradDt", "FinInstrmTp", "ISIN", "ClsPric", "Src"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError(f"not a UDiFF bhavcopy (columns: {reader.fieldnames})")
    for r in reader:
        if r["FinInstrmTp"].strip() != "STK":
            continue
        isin = r["ISIN"].strip()
        if wanted_isins is not None and isin not in wanted_isins:
            continue
        close = _f(r["ClsPric"])
        if close is None:
            continue
        rows.append(
            PriceRow(
                isin=isin,
                trade_date=date.fromisoformat(r["TradDt"].strip()),
                exchange=r["Src"].strip().upper(),
                symbol=(r.get("TckrSymb") or "").strip(),
                series=(r.get("SctySrs") or "").strip(),
                open=_f(r.get("OpnPric", "")),
                high=_f(r.get("HghPric", "")),
                low=_f(r.get("LwPric", "")),
                close=close,
                prev_close=_f(r.get("PrvsClsgPric", "")),
                volume=_i(r.get("TtlTradgVol", "")),
            )
        )
    return rows
