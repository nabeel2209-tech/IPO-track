"""HTTP helpers: browser-like headers, retries with backoff, and clear error types.

NSE in particular sits behind bot protection. It expects browser-like headers, sets cookies on
its home page, rate-limits, and often rejects requests from cloud servers. We handle that by:
- warming up a session on the home page before calling its API,
- retrying with growing waits on 403/429/5xx and timeouts,
- treating 404 as "no file" (a market holiday), which is not retried.
"""

import time
from collections.abc import Callable

import httpx

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-IN,en;q=0.9",
}

RETRY_STATUSES = {403, 408, 429, 500, 502, 503, 504}


class FetchError(Exception):
    """The download failed after every retry."""


class NoFile(FetchError):
    """The server says the file does not exist (usually a market holiday)."""


def make_client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(headers=BROWSER_HEADERS, timeout=timeout, follow_redirects=True)


def get_bytes(
    client: httpx.Client,
    url: str,
    *,
    tries: int = 4,
    base_delay: float = 2.0,
    headers: dict | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    """GET ``url`` and return the body, retrying transient failures with exponential backoff."""
    last: str = ""
    for attempt in range(tries):
        try:
            resp = client.get(url, headers=headers)
        except httpx.TransportError as e:  # timeouts, connection resets, DNS
            last = f"{type(e).__name__}: {e}"
        else:
            if resp.status_code == 200 and resp.content:
                return resp.content
            if resp.status_code == 404:
                raise NoFile(f"404 for {url}")
            last = f"HTTP {resp.status_code}"
            if resp.status_code not in RETRY_STATUSES:
                break
        if attempt < tries - 1:
            sleep(base_delay * (2**attempt))
    raise FetchError(f"{url} failed after {tries} tries ({last})")
