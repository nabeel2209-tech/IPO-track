"""Command line for the data pipeline.  Run from the ``backend`` folder:

python -m pipeline collect-master --from 2026-01-01      # IPO details from NSE → data/ipo_master.csv
python -m pipeline load                                   # CSVs → database (master + corporate actions)
python -m pipeline prices --from 2026-01-01               # backfill daily prices from NSE and BSE
python -m pipeline daily                                  # last 10 days (what the scheduler runs)
python -m pipeline yahoo-gaps                             # fill days both exchanges missed
python -m pipeline validate                               # data checks; exit code 1 on errors
"""

import argparse
import sys
from datetime import date, timedelta

from app.config import DATA_DIR
from app.db import SessionLocal, init_db
from pipeline import actions, ingest, validate
from pipeline.http import make_client
from pipeline.load import replace_corporate_actions, upsert_ipos
from pipeline.master import master_csv
from pipeline.master.nse_collector import NseClient, collect

MASTER_CSV = DATA_DIR / "ipo_master.csv"
ACTIONS_CSV = DATA_DIR / "corporate_actions.csv"
RAW_DIR = DATA_DIR / "raw"


def _date(s: str) -> date:
    return date.fromisoformat(s)


def cmd_collect_master(a) -> int:
    with make_client() as client:
        records = collect(NseClient(client), a.from_date, a.to_date)
    merged, added, updated = master_csv.merge(master_csv.read(MASTER_CSV), records)
    master_csv.write(MASTER_CSV, merged)
    print(f"collected {len(records)} IPOs from NSE: {added} new, {updated} updated → {MASTER_CSV}")
    issues = master_csv.problems(merged)
    for p in issues:
        print("  check:", p)
    return 0


def cmd_load(_a) -> int:
    init_db()
    records = master_csv.read(MASTER_CSV)
    issues = [p for p in master_csv.problems(records) if "outside band" not in p]
    if issues:
        print("master CSV has problems, fix them first:\n  " + "\n  ".join(issues))
        return 1
    with SessionLocal() as s:
        n = upsert_ipos(s, records)
        m = replace_corporate_actions(s, actions.read_csv(ACTIONS_CSV))
        s.commit()
    print(f"loaded {n} IPOs and {m} corporate actions")
    return 0


def cmd_prices(a) -> int:
    init_db()
    with SessionLocal() as s, make_client() as client:
        ingest.backfill(s, client, a.from_date, a.to_date, RAW_DIR, force=a.force)
    return 0


def cmd_daily(a) -> int:
    a.from_date, a.to_date = date.today() - timedelta(days=a.days), date.today()
    return cmd_prices(a)


def cmd_yahoo(_a) -> int:
    with SessionLocal() as s:
        n = ingest.fill_gaps_with_yahoo(s)
    print(f"filled {n} price rows from Yahoo")
    return 0


def cmd_validate(_a) -> int:
    with SessionLocal() as s:
        rep = validate.run(s)
    for w in rep.warnings:
        print("warning:", w)
    for e in rep.errors:
        print("ERROR:  ", e)
    print(f"{len(rep.errors)} errors, {len(rep.warnings)} warnings")
    return 0 if rep.ok else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pipeline", description="IPO tracker data pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect-master", help="fetch IPO details from NSE into data/ipo_master.csv")
    c.add_argument("--from", dest="from_date", type=_date, default=date(date.today().year, 1, 1))
    c.add_argument("--to", dest="to_date", type=_date, default=date.today())
    c.set_defaults(fn=cmd_collect_master)

    sub.add_parser("load", help="load the master and corporate-action CSVs into the database").set_defaults(fn=cmd_load)

    c = sub.add_parser("prices", help="download and load daily prices for a date range")
    c.add_argument("--from", dest="from_date", type=_date, required=True)
    c.add_argument("--to", dest="to_date", type=_date, default=date.today())
    c.add_argument("--force", action="store_true", help="re-load days already loaded")
    c.set_defaults(fn=cmd_prices)

    c = sub.add_parser("daily", help="load the last few days (for the scheduler)")
    c.add_argument("--days", type=int, default=10)
    c.add_argument("--force", action="store_true")
    c.set_defaults(fn=cmd_daily)

    sub.add_parser("yahoo-gaps", help="fill missing days from Yahoo Finance").set_defaults(fn=cmd_yahoo)
    sub.add_parser("validate", help="run data checks").set_defaults(fn=cmd_validate)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
