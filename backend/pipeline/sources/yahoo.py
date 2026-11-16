"""Yahoo Finance fallback (via the ``yfinance`` package) for days the exchange files missed.

Watch out: Yahoo rewrites old prices after a split or bonus (it divides pre-split prices by the
ratio). Our database stores prices *as traded* and applies splits itself, so Yahoo prices are
converted back to as-traded before saving. Without this step, mixing the two sources would make a
split look like a crash or a jump.
"""

from collections.abc import Iterable
from datetime import date, timedelta

from pipeline.sources.udiff import PriceRow


def ticker_for(nse_symbol: str | None, bse_code: str | None) -> tuple[str, str] | None:
    if nse_symbol:
        return f"{nse_symbol}.NS", "NSE"
    if bse_code:
        return f"{bse_code}.BO", "BSE"
    return None


def as_traded(yahoo_close: float, day: date, actions: Iterable[tuple[date, float]]) -> float:
    """Undo Yahoo's retroactive split adjustment: multiply by every split that came *after* ``day``."""
    m = 1.0
    for ex_date, multiplier in actions:
        if ex_date > day:
            m *= multiplier
    return round(yahoo_close * m, 2)  # Yahoo sends float32-style values like 668.0999755859375


def fetch_history(isin: str, ticker: str, exchange: str, start: date, end: date, actions: list[tuple[date, float]], downloader=None) -> list[PriceRow]:
    """Daily rows from ``start`` to ``end`` inclusive. ``downloader`` is injectable for tests."""
    if downloader is None:
        import yfinance as yf  # imported lazily: optional dependency

        def downloader(t, s, e):
            return yf.Ticker(t).history(start=s, end=e, interval="1d", auto_adjust=False, actions=False)

    df = downloader(ticker, start.isoformat(), (end + timedelta(days=1)).isoformat())
    rows: list[PriceRow] = []
    if df is None or len(df) == 0:
        return rows
    for ts, r in df.iterrows():
        d = ts.date() if hasattr(ts, "date") else date.fromisoformat(str(ts)[:10])
        close = float(r["Close"])
        if close != close or close <= 0:  # NaN or bad row
            continue
        rows.append(
            PriceRow(
                isin=isin,
                trade_date=d,
                exchange=exchange,
                symbol=ticker,
                series="",
                open=as_traded(float(r["Open"]), d, actions),
                high=as_traded(float(r["High"]), d, actions),
                low=as_traded(float(r["Low"]), d, actions),
                close=as_traded(close, d, actions),
                prev_close=None,
                volume=int(r["Volume"]) if r.get("Volume") == r.get("Volume") else None,
            )
        )
    return rows
