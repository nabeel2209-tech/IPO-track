from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.models import IngestionRun, Ipo, Price
from pipeline import actions, ingest, validate
from pipeline.http import FetchError, NoFile, get_bytes
from pipeline.load import replace_corporate_actions, upsert_ipos
from pipeline.sources.exchanges import BhavcopySource
from pipeline.sources.yahoo import as_traded, fetch_history
from tests.conftest import ACTIONS, IPOS

# ---------- HTTP retries ----------


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, headers=None):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return httpx.Response(r[0], content=r[1])


def test_retries_then_succeeds():
    waits = []
    c = FakeClient([(503, b""), httpx.ConnectTimeout("slow"), (200, b"ok")])
    assert get_bytes(c, "u", sleep=waits.append, base_delay=1) == b"ok"
    assert waits == [1, 2]  # exponential backoff


def test_404_means_no_file_and_is_not_retried():
    c = FakeClient([(404, b"")])
    with pytest.raises(NoFile):
        get_bytes(c, "u", sleep=lambda s: None)
    assert c.calls == 1


def test_gives_up_after_all_tries():
    c = FakeClient([(403, b"")] * 3)
    with pytest.raises(FetchError):
        get_bytes(c, "u", tries=3, sleep=lambda s: None)


# ---------- daily ingestion ----------


class FakeSource(BhavcopySource):
    def __init__(self, name, exchange, behaviour):
        super().__init__(name, exchange, "", "{ymd}")
        self.behaviour = behaviour
        self.fetches = 0

    def fetch(self, client, day, raw_dir, *, use_cache=True, sleep=None):
        self.fetches += 1
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return self.behaviour.encode()


def test_ingest_day_is_idempotent_and_logs_each_source(session, bse_text, tmp_path: Path):
    upsert_ipos(session, IPOS)
    session.commit()
    good = FakeSource("bse_bhavcopy", "BSE", bse_text)
    holiday = FakeSource("nse_bhavcopy", "NSE", NoFile("404"))
    day = date(2026, 10, 30)
    isins = ingest.wanted_isins(session)

    r1 = ingest.ingest_day(session, None, day, tmp_path, isins, sources=[good, holiday])
    assert r1.status == {"bse_bhavcopy": "ok", "nse_bhavcopy": "no_file"}
    assert r1.rows["bse_bhavcopy"] == 4  # Jio, Nityas, Waterways, Aastha on that day

    r2 = ingest.ingest_day(session, None, day, tmp_path, isins, sources=[good, holiday])
    assert r2.status == {"bse_bhavcopy": "skipped", "nse_bhavcopy": "skipped"}
    assert good.fetches == 1
    assert session.execute(select(func.count()).select_from(Price)).scalar_one() == 4

    r3 = ingest.ingest_day(session, None, day, tmp_path, isins, sources=[good], force=True)
    assert r3.status["bse_bhavcopy"] == "ok"
    assert session.execute(select(func.count()).select_from(Price)).scalar_one() == 4  # upsert, not duplicate


def test_failed_source_is_logged_and_retried_next_run(session, tmp_path: Path):
    upsert_ipos(session, IPOS)
    session.commit()
    blocked = FakeSource("nse_bhavcopy", "NSE", FetchError("HTTP 403"))
    day = date(2026, 10, 30)
    ingest.ingest_day(session, None, day, tmp_path, set(), sources=[blocked])
    ingest.ingest_day(session, None, day, tmp_path, set(), sources=[blocked])
    assert blocked.fetches == 2  # failures are not marked done
    statuses = session.execute(select(IngestionRun.status)).scalars().all()
    assert statuses == ["failed", "failed"]


class PageClient:
    """Answers every request with 200 and the given body, like BSE on a holiday."""

    cookies = {"warm": "1"}

    def __init__(self, body: bytes):
        self.body = body

    def get(self, url, headers=None):
        return httpx.Response(200, content=self.body)


def test_holiday_web_page_is_no_file_and_not_cached(tmp_path: Path):
    from pipeline.sources.exchanges import BSE

    page = b'<!DOCTYPE html><html lang="en"><head></head></html>'
    with pytest.raises(NoFile):
        BSE.fetch(PageClient(page), date(2026, 1, 26), tmp_path, sleep=lambda s: None)
    assert not BSE.raw_path(tmp_path, date(2026, 1, 26)).exists()


def test_bad_cached_file_is_replaced(tmp_path: Path, bse_text):
    from pipeline.sources.exchanges import BSE

    day = date(2026, 10, 30)
    path = BSE.raw_path(tmp_path, day)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"<!DOCTYPE html><html></html>")  # saved by an older version
    data = BSE.fetch(PageClient(bse_text.encode()), day, tmp_path, sleep=lambda s: None)
    assert data.startswith(b"TradDt") and path.read_bytes() == data


def test_weekdays_skip_weekends():
    days = list(ingest.weekdays(date(2026, 10, 30), date(2026, 11, 2)))
    assert days == [date(2026, 10, 30), date(2026, 11, 2)]


# ---------- corporate actions ----------


def test_detects_unknown_split_and_bonus_from_real_data(session, bse_text):
    from pipeline.load import upsert_prices
    from pipeline.sources import udiff

    upsert_ipos(session, IPOS)
    upsert_prices(session, udiff.parse(bse_text), "bse_bhavcopy")
    session.commit()
    found = {(s.isin, s.trade_date): s.suggested_multiplier for s in actions.detect(session)}
    assert found[("INE0LZF01039", date(2026, 8, 25))] == 10  # Waterways 1:10 split
    assert found[("INE2FMX01012", date(2026, 9, 28))] == 2  # Aastha 1:1 bonus

    replace_corporate_actions(session, ACTIONS)
    session.commit()
    assert actions.detect(session) == []


def test_validate_passes_on_clean_data(seeded):
    rep = validate.run(seeded)
    assert rep.errors == [] or all("no prices" in e for e in rep.errors)


# ---------- Yahoo fallback ----------


def test_yahoo_prices_are_converted_back_to_as_traded():
    split = [(date(2026, 8, 25), 10.0)]
    assert as_traded(104.22, date(2026, 8, 24), split) == pytest.approx(1042.2)
    assert as_traded(104.30, date(2026, 8, 25), split) == pytest.approx(104.30)


def test_fetch_history_with_fake_downloader():
    class Frame:
        def __init__(self, rows):
            self.rows = rows

        def __len__(self):
            return len(self.rows)

        def iterrows(self):
            return iter(self.rows)

    rows = [
        (date(2026, 8, 24), {"Open": 103.0, "High": 105.0, "Low": 102.0, "Close": 104.22, "Volume": 10}),
        (date(2026, 8, 25), {"Open": 102.9, "High": 107.5, "Low": 101.3, "Close": 104.30, "Volume": 12}),
    ]
    out = fetch_history("INE0LZF01039", "CORDELIA.NS", "NSE", date(2026, 8, 24), date(2026, 8, 25), [(date(2026, 8, 25), 10.0)], downloader=lambda *a: Frame(rows))
    assert [round(r.close, 2) for r in out] == [1042.2, 104.3]


# ---------- IPOs added to the master list later ----------


def _load_day(session, source, day, tmp_path, isins):
    return ingest.ingest_day(session, None, day, tmp_path, isins, sources=[source])


def test_catch_up_loads_history_for_a_newly_added_ipo(session, bse_text, tmp_path: Path):
    jio, nityas = IPOS[0], IPOS[1]
    upsert_ipos(session, [jio])
    session.commit()
    src = FakeSource("bse_bhavcopy", "BSE", bse_text)
    for day in (date(2026, 10, 8), date(2026, 10, 28), date(2026, 10, 29)):
        _load_day(session, src, day, tmp_path, ingest.wanted_isins(session))
    ingest.catch_up(session, None, tmp_path, sources=[src], log=lambda *_: None)  # records Jio as complete
    fetched = src.fetches
    assert ingest.catch_up(session, None, tmp_path, sources=[src], log=lambda *_: None) == 0  # nothing new
    assert src.fetches == fetched

    # Nityas listed on 8 Oct but joins the master list only now, and the next day is loaded before
    # the catch-up runs. Having that one price must not make its history look complete.
    upsert_ipos(session, [nityas])
    session.commit()
    _load_day(session, src, date(2026, 10, 30), tmp_path, ingest.wanted_isins(session))
    assert session.execute(select(Price.trade_date).where(Price.isin == nityas["isin"])).scalars().all() == [date(2026, 10, 30)]
    said = []
    ingest.catch_up(session, None, tmp_path, sources=[src], log=said.append)
    days = session.execute(select(Price.trade_date).where(Price.isin == nityas["isin"]).order_by(Price.trade_date)).scalars().all()
    assert days == [date(2026, 10, 8), date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30)]
    assert "4 saved files for 1 IPOs" in said[0]
    assert session.execute(select(func.count()).select_from(Price).where(Price.isin == jio["isin"])).scalar_one() == 3  # untouched

    fetched = src.fetches
    assert ingest.catch_up(session, None, tmp_path, sources=[src], log=lambda *_: None) == 0  # second run does nothing
    assert src.fetches == fetched


def test_catch_up_retries_an_ipo_whose_files_could_not_be_read(session, bse_text, tmp_path: Path):
    good = FakeSource("bse_bhavcopy", "BSE", bse_text)
    _load_day(session, good, date(2026, 10, 8), tmp_path, set())
    upsert_ipos(session, [IPOS[1]])
    session.commit()
    broken = FakeSource("bse_bhavcopy", "BSE", FetchError("file missing and BSE is down"))
    said = []
    assert ingest.catch_up(session, None, tmp_path, sources=[broken], log=said.append) == 0
    assert "catch-up bse_bhavcopy 2026-10-08" in said[0]
    assert ingest.catch_up(session, None, tmp_path, sources=[good], log=lambda *_: None) == 1  # not marked done, so tried again


def test_catch_up_only_reads_the_exchange_the_ipo_trades_on(session, bse_text, tmp_path: Path):
    bse_only = dict(IPOS[1], exchanges="BSE", nse_symbol=None)
    bse = FakeSource("bse_bhavcopy", "BSE", bse_text)
    nse = FakeSource("nse_bhavcopy", "NSE", bse_text)
    for src in (bse, nse):
        _load_day(session, src, date(2026, 10, 8), tmp_path, set())
    upsert_ipos(session, [bse_only])
    session.commit()
    before = nse.fetches
    assert ingest.catch_up(session, None, tmp_path, sources=[bse, nse], log=lambda *_: None) == 1
    assert nse.fetches == before


def test_sme_non_trading_days_are_not_sent_to_yahoo(session):
    sme = Ipo(**dict(IPOS[1], segment="sme", exchanges="BSE"))
    main = Ipo(**IPOS[1])
    listing, quiet, unloaded = date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 12)
    loaded = {"bse_bhavcopy": {listing, quiet}, "nse_bhavcopy": {listing, quiet, unloaded}}
    assert ingest.yahoo_gaps(main, [quiet, unloaded], loaded) == [quiet, unloaded]  # mainboard trades daily
    assert ingest.yahoo_gaps(sme, [quiet, unloaded], loaded) == [unloaded]  # BSE file for that day never loaded
    assert ingest.yahoo_gaps(sme, [listing, quiet], loaded) == [listing, quiet]  # no listing-day price: ask for everything


def test_validate_does_not_warn_about_quiet_sme_days(session, bse_text, tmp_path: Path):
    sme = dict(IPOS[1], segment="sme", exchanges="BSE")
    upsert_ipos(session, [sme])
    session.commit()
    src = FakeSource("bse_bhavcopy", "BSE", bse_text)
    for day in (date(2026, 10, 8), date(2026, 9, 28), date(2026, 10, 28)):
        _load_day(session, src, day, tmp_path, ingest.wanted_isins(session))
    session.execute(Price.__table__.delete().where(Price.trade_date == date(2026, 10, 28)))
    session.commit()
    rep = validate.run(session)
    assert rep.errors == [] and rep.warnings == []
    assert "1 SME IPOs" in rep.notes[0]


def test_collect_master_keeps_going_when_one_source_fails(tmp_path, monkeypatch, capsys):
    import pipeline.__main__ as cli

    def boom(client, start, end):
        raise FetchError("NSE blocked the request")

    record = {
        "isin": "INE15Z101013",
        "company": "Antala Industries Limited",
        "segment": "sme",
        "exchanges": "BSE",
        "bse_code": "545024",
        "listing_date": date(2026, 11, 11),
        "issue_price": 66.0,
        "lot_size": 2000,
        "source": "bse_api",
    }
    monkeypatch.setattr(cli, "MASTER_CSV", tmp_path / "m.csv")
    monkeypatch.setattr(cli, "COLLECTORS", {"nse": ("NSE", boom), "bse": ("BSE SME", lambda c, s, e: [record])})
    assert cli.main(["collect-master"]) == 0
    out = capsys.readouterr().out
    assert "nse: failed" in out and "bse: collected 1 IPOs" in out
    assert [r["isin"] for r in cli.master_csv.read(tmp_path / "m.csv")] == ["INE15Z101013"]

    monkeypatch.setattr(cli, "COLLECTORS", {"nse": ("NSE", boom)})
    assert cli.main(["collect-master", "--source", "nse"]) == 1  # nothing collected: say so with the exit code
