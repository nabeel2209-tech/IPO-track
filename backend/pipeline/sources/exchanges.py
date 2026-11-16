"""Daily bhavcopy downloads from NSE and BSE.

Each source knows its URL pattern and how to fetch it. Downloaded files are saved under
``data/raw/<source>/<year>/`` before parsing, so a day can be re-processed without downloading
again, and so a bad day can be inspected later.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from pipeline.http import NoFile, get_bytes


def looks_like_bhavcopy(payload: bytes) -> bool:
    """A real file is a zip (NSE) or a CSV starting with the UDiFF header (BSE).

    On market holidays BSE doesn't return a 404: it answers 200 with its website's HTML page. Without
    this check that page would be saved as the day's file and reported as a parsing failure.
    """
    head = payload[:16].lstrip(b"\xef\xbb\xbf").lstrip()
    return head.startswith(b"PK") or head.startswith(b"TradDt")


@dataclass
class BhavcopySource:
    name: str  # "nse_bhavcopy" | "bse_bhavcopy"
    exchange: str
    url_template: str
    filename_template: str
    referer: str | None = None
    warmup_url: str | None = None

    def url(self, day: date) -> str:
        return self.url_template.format(ymd=day.strftime("%Y%m%d"))

    def raw_path(self, raw_dir: Path, day: date) -> Path:
        return raw_dir / self.name / str(day.year) / self.filename_template.format(ymd=day.strftime("%Y%m%d"))

    def fetch(self, client: httpx.Client, day: date, raw_dir: Path, *, use_cache: bool = True, sleep=None) -> bytes:
        path = self.raw_path(raw_dir, day)
        if use_cache and path.exists():
            cached = path.read_bytes()
            if looks_like_bhavcopy(cached):
                return cached
            path.unlink()  # an older run saved a web page here; fetch again
        if self.warmup_url and not client.cookies:
            try:  # sets the cookies NSE checks for; failure here is not fatal
                client.get(self.warmup_url)
            except httpx.HTTPError:
                pass
        headers = {"Referer": self.referer} if self.referer else None
        kwargs = {"headers": headers}
        if sleep is not None:
            kwargs["sleep"] = sleep
        data = get_bytes(client, self.url(day), **kwargs)
        if not looks_like_bhavcopy(data):
            raise NoFile(f"{self.exchange} returned a web page instead of a file for {day} (market holiday?)")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return data


NSE = BhavcopySource(
    name="nse_bhavcopy",
    exchange="NSE",
    url_template="https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip",
    filename_template="BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip",
    referer="https://www.nseindia.com/all-reports",
    warmup_url="https://www.nseindia.com/",
)

BSE = BhavcopySource(
    name="bse_bhavcopy",
    exchange="BSE",
    url_template="https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{ymd}_F_0000.CSV",
    filename_template="BhavCopy_BSE_CM_0_0_0_{ymd}_F_0000.CSV",
    referer="https://www.bseindia.com/markets/MarketInfo/BhavCopy.aspx",
)

SOURCES = {s.name: s for s in (NSE, BSE)}
