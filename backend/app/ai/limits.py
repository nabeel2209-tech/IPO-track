"""A small daily usage limit for the AI endpoint, so a public demo can't run up a large bill.

Kept in memory on purpose: it is enough for a single-instance demo. With several API instances you
would move the counters to Redis (or the database) so every instance shares them.
"""

import threading
from datetime import date


class DailyLimiter:
    def __init__(self, per_key: int, global_limit: int):
        self.per_key = per_key
        self.global_limit = global_limit
        self._day = date.today()
        self._counts: dict[str, int] = {}
        self._total = 0
        self._lock = threading.Lock()

    def _roll(self) -> None:
        today = date.today()
        if today != self._day:
            self._day, self._counts, self._total = today, {}, 0

    def allow(self, key: str) -> tuple[bool, str | None]:
        with self._lock:
            self._roll()
            if self._total >= self.global_limit:
                return False, "The daily question limit for this demo has been reached. Try again tomorrow."
            if self._counts.get(key, 0) >= self.per_key:
                return False, "You've reached today's question limit. Try again tomorrow."
            self._counts[key] = self._counts.get(key, 0) + 1
            self._total += 1
            return True, None
