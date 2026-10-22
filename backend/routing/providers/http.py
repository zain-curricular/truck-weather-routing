import logging
import time
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

import requests

from routing.errors import UpstreamAuth, UpstreamBadResponse, UpstreamUnavailable
from routing.log_redaction import redact

logger = logging.getLogger(__name__)

TIMEOUT = (3.0, 10.0)
RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRY_BACKOFF_SECONDS = 0.5

Params = Mapping[str, str | int | Sequence[str]]

session = requests.Session()


def get_json(
    url: str,
    params: Params,
    *,
    service: str,
    timeout: tuple[float, float] = TIMEOUT,
    exact_decimals: bool = False,
) -> Any:
    """GET with one retry on transient failures.

    `exact_decimals` parses JSON numbers as Decimal, for values compared against thresholds.

    Raised messages never include the request URL, because TomTom's key travels in it.
    """
    response = None
    for attempt in range(2):
        try:
            response = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            logger.warning("%s request failed: %s", service, redact(str(exc)))
            response = None
        if response is not None and response.status_code not in RETRY_STATUSES:
            break
        if attempt == 0:
            time.sleep(RETRY_BACKOFF_SECONDS)

    if response is None:
        raise UpstreamUnavailable(f"{service} is not responding. Try again shortly.")
    if response.status_code in (401, 403):
        logger.error("%s rejected credentials (HTTP %s)", service, response.status_code)
        raise UpstreamAuth(
            f"{service} is not available: access was refused or the quota is used up."
        )
    if response.status_code == 429:
        raise UpstreamUnavailable(f"{service} rate limit reached. Try again in a few minutes.")
    if response.status_code >= 500:
        raise UpstreamUnavailable(f"{service} is having problems (HTTP {response.status_code}).")
    if response.status_code >= 400:
        body = _body(response)
        logger.warning("%s returned HTTP %s: %s", service, response.status_code, redact(str(body)))
        raise ClientError(response.status_code, body)

    try:
        return response.json(parse_float=Decimal) if exact_decimals else response.json()
    except ValueError as exc:
        raise UpstreamBadResponse(f"{service} returned a response that could not be read.") from exc


class ClientError(Exception):
    """A 4xx from the provider; callers decide what it means for their API."""

    def __init__(self, status_code: int, body: Any) -> None:
        super().__init__(status_code)
        self.status_code = status_code
        self.body = body


def _body(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {}
