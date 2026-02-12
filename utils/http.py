"""HTTP client helpers with retries and backoff."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

try:
    import httpx
except ModuleNotFoundError:  # pragma: no cover
    httpx = None


@dataclass
class HttpConfig:
    timeout_seconds: float = 15.0
    max_retries: int = 4
    backoff_base: float = 0.8


class HttpError(RuntimeError):
    pass


def request_json(
    method: str,
    url: str,
    *,
    client: httpx.Client | None = None,
    config: HttpConfig | None = None,
    **kwargs: Any,
) -> Any:
    cfg = config or HttpConfig()
    attempt = 0
    owned_client = client is None
    if httpx is None:
        raise HttpError("httpx is required for HTTP requests")
    session = client or httpx.Client(timeout=cfg.timeout_seconds, follow_redirects=True)

    try:
        while True:
            attempt += 1
            try:
                resp = session.request(method, url, **kwargs)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise HttpError(f"retryable_status:{resp.status_code}")
                resp.raise_for_status()
                return resp.json()
            except tuple([e for e in ((httpx.RequestError if httpx else Exception), (httpx.TimeoutException if httpx else Exception), HttpError) if e]) as exc:
                if attempt > cfg.max_retries:
                    raise HttpError(f"Request failed after retries for {url}: {exc}") from exc
                sleep_for = cfg.backoff_base * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
                time.sleep(sleep_for)
    finally:
        if owned_client:
            session.close()
