import math
import os
import secrets
import threading
import time
from collections import deque
from typing import Optional

from fastapi import HTTPException, Request, Security, status
from fastapi.security.api_key import APIKeyHeader

from .config import ConfigError

API_KEY_NAME = "X-API-Key"

# Overrides security.api_key, so the key can stay out of the config file.
API_KEY_ENV_VAR = "AUTOCRUD_API_KEY"

# Keys that were once committed as examples; a server must never accept them.
REJECTED_API_KEYS = ("test-secret",)

RATE_LIMIT_WINDOW_SECONDS = 60

# auto_error=False so a request without a key still counts against the rate limit.
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

def resolve_api_key(config):
    """
    Returns the API key from AUTOCRUD_API_KEY, or else security.api_key.
    Raises ConfigError if there is none or it is a known example key.
    """
    api_key = os.environ.get(API_KEY_ENV_VAR) or (config.get('security') or {}).get('api_key')
    if not isinstance(api_key, str) or not api_key:
        raise ConfigError(
            f"No API key configured. Set the {API_KEY_ENV_VAR} environment variable "
            "or security.api_key in the config ('autocrud init' generates one)."
        )
    if api_key in REJECTED_API_KEYS:
        raise ConfigError(
            f"Refusing to start with the published example API key '{api_key}'. "
            f"Set {API_KEY_ENV_VAR} or security.api_key to a secret value."
        )
    return api_key

class SlidingWindowRateLimiter:
    """
    Allows each client `limit` requests in any `window`-second span.

    Counts live in this object, so the limit is per process: an app served by
    several workers or replicas allows up to `limit` requests per client in each.
    """
    def __init__(self, limit, window=RATE_LIMIT_WINDOW_SECONDS, clock=time.monotonic):
        self.limit = limit
        self.window = window
        self.clock = clock
        self._hits = {}
        self._lock = threading.Lock()
        self._last_prune = clock()

    def hit(self, client):
        """Records a request from client. Returns 0 if it is allowed, otherwise
        the whole seconds until the client may send the next one."""
        now = self.clock()
        cutoff = now - self.window
        with self._lock:
            if now - self._last_prune >= self.window:
                self._prune(cutoff)
                self._last_prune = now
            hits = self._hits.setdefault(client, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1, math.ceil(hits[0] - cutoff))
            hits.append(now)
            return 0

    def _prune(self, cutoff):
        # Forget clients with no request in the window, so memory stays bounded.
        idle = [client for client, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for client in idle:
            del self._hits[client]

def make_rate_limiter(config):
    """Returns a limiter for rate_limit.requests_per_minute, or None if it is not set."""
    requests_per_minute = (config.get('rate_limit') or {}).get('requests_per_minute')
    if not requests_per_minute:
        return None
    return SlidingWindowRateLimiter(requests_per_minute)

def make_api_key_dependency(expected_api_key, rate_limiter=None):
    """
    Returns a dependency that counts the request against the client IP's rate
    limit, then checks the X-API-Key header against a key resolved once at
    startup. Wrong-key guesses are rate limited like any other request.
    """
    def check_api_key(request: Request, api_key: Optional[str] = Security(api_key_header)):
        if rate_limiter is not None:
            client = request.client.host if request.client else "unknown"
            retry_after = rate_limiter.hit(client)
            if retry_after:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded.",
                    headers={"Retry-After": str(retry_after)},
                )
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing API Key",
            )
        if not secrets.compare_digest(api_key.encode(), expected_api_key.encode()):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API Key",
            )
        return api_key

    return check_api_key
