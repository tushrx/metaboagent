"""
Shared HTTP helper for live-fetch tools.

- One session per tool module (tcp reuse, polite User-Agent).
- Exponential-backoff retries via tenacity.
- Bounded timeout so a hung endpoint doesn't freeze the ReAct loop.
- JSON + text parsing helpers.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

_DEFAULT_UA = "MetaboAgent/1.0 (hbsubiochemistry@gmail.com; research)"
_DEFAULT_TIMEOUT = 25  # seconds — ReAct loop can't afford longer hangs


def make_session(extra_headers: Optional[dict] = None) -> requests.Session:
    s = requests.Session()
    headers = {"User-Agent": _DEFAULT_UA, "Accept": "application/json,*/*;q=0.9"}
    if extra_headers:
        headers.update(extra_headers)
    s.headers.update(headers)
    return s


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4))
def _get_raw(session: requests.Session, url: str, params: Optional[dict] = None,
             timeout: int = _DEFAULT_TIMEOUT) -> requests.Response:
    resp = session.get(url, params=params, timeout=timeout)
    # 404 is normal "not found"; don't retry.
    if resp.status_code == 404:
        return resp
    resp.raise_for_status()
    return resp


def get_json(session: requests.Session, url: str, params: Optional[dict] = None,
             timeout: int = _DEFAULT_TIMEOUT) -> Optional[dict | list]:
    try:
        resp = _get_raw(session, url, params=params, timeout=timeout)
    except (requests.RequestException, RetryError) as e:
        log.warning("GET %s failed: %s", url, e)
        return None
    if resp.status_code == 404:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def get_text(session: requests.Session, url: str, params: Optional[dict] = None,
             timeout: int = _DEFAULT_TIMEOUT) -> Optional[str]:
    try:
        resp = _get_raw(session, url, params=params, timeout=timeout)
    except (requests.RequestException, RetryError) as e:
        log.warning("GET %s failed: %s", url, e)
        return None
    if resp.status_code == 404:
        return None
    return resp.text
