"""Request throttling with a token bucket, so one client cannot flood the API."""

import time
from dataclasses import dataclass, field


@dataclass
class Bucket:
    tokens: float
    updated_at: float = field(default_factory=time.monotonic)


class RateLimiter:
    """Allows `rate` requests per second per client, with a burst allowance."""

    def __init__(self, rate: float = 5.0, burst: int = 10) -> None:
        self.rate = rate
        self.burst = burst
        self._buckets: dict[str, Bucket] = {}

    def allow_request(self, client_id: str, now: float | None = None) -> bool:
        """Consume one token for this client; False means the caller is throttled."""
        now = now if now is not None else time.monotonic()
        bucket = self._buckets.setdefault(client_id, Bucket(tokens=float(self.burst), updated_at=now))
        bucket.tokens = min(self.burst, bucket.tokens + (now - bucket.updated_at) * self.rate)
        bucket.updated_at = now
        if bucket.tokens < 1.0:
            return False
        bucket.tokens -= 1.0
        return True

    def retry_after(self, client_id: str) -> float:
        """Seconds until the client may send another request."""
        bucket = self._buckets.get(client_id)
        if bucket is None or bucket.tokens >= 1.0:
            return 0.0
        return (1.0 - bucket.tokens) / self.rate
