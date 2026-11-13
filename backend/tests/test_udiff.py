import io
import zipfile
from datetime import date

import pytest

from pipeline.sources import udiff


def test_parse_real_bse_rows(bse_text):
    rows = udiff.parse(bse_text)
    jio = [r for r in rows if r.isin == "INE0BJO01010"]
    assert {r.trade_date for r in jio} == {date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30)}
    listing = next(r for r in jio if r.trade_date == date(2026, 10, 28))
    assert listing.exchange == "BSE" and listing.close == 1417.35 and listing.open == 1358.0
    assert listing.prev_close is None  # "0.00" on listing day means no previous close


def test_filter_by_isin(bse_text):
    rows = udiff.parse(bse_text, {"INE2FMX01012"})
    assert rows and all(r.symbol == "AASTHA" for r in rows)


def test_decode_nse_style_zip(bse_text):
    nse_csv = bse_text.replace(",BSE,", ",NSE,")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BhavCopy_NSE_CM_0_0_0_20261030_F_0000.csv", nse_csv)
    rows = udiff.parse(udiff.decode(buf.getvalue()))
    assert rows and {r.exchange for r in rows} == {"NSE"}


def test_rejects_old_format():
    with pytest.raises(ValueError):
        udiff.parse("SYMBOL,SERIES,OPEN,HIGH\nABC,EQ,1,2\n")
