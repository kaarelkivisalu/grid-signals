"""Thread-safe token-bucket rate limiter for ENTSO-E API calls."""

import threading
import time


class RateLimiter:
    """Serialises access so that at most *max_per_second* calls proceed per second.

    Safe to use from multiple threads.  Callers block in :meth:`acquire`
    until they are allowed to proceed.
    """

    def __init__(self, max_per_second: float) -> None:
        self._interval = 1.0 / max_per_second
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        """Block until the next request slot is available."""
        with self._lock:
            now = time.monotonic()
            if now < self._next_allowed:
                wait = self._next_allowed - now
                self._next_allowed += self._interval
            else:
                wait = 0.0
                self._next_allowed = now + self._interval
        if wait > 0:
            time.sleep(wait)
