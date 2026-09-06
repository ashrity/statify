"""The only module that talks to The Odds API.

Separate from nflverse.py on purpose: that one wraps a data library, this one
wraps a metered HTTP API where every request costs money and carries a secret.

Two rules this module exists to enforce:

1. The API key never appears in an exception, a log line, or printed output.
   httpx puts the full request URL in its error messages, and the key is a query
   parameter, so every failure is caught and re-raised with a sanitized message.
2. Every response reports the remaining credit balance back to the caller, so
   the CLI can show it without spending a request to ask.
"""

from __future__ import annotations

from typing import Any

import httpx

from statify.config import settings

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"

# Restricting to a single book costs the same as asking for the whole region,
# measured against the live API, so there is no reason to take fewer books.
REGION = "us"

TIMEOUT = httpx.Timeout(60.0)


def _require_key() -> str:
    if not settings.odds_api_key:
        raise RuntimeError(
            "ODDS_API_KEY is not set. Copy .env.example to .env and add the key "
            "from the-odds-api.com."
        )
    return settings.odds_api_key


def _get(path: str, **params: Any) -> tuple[Any, int | None]:
    """GET one endpoint. Returns (body, credits remaining)."""
    params["apiKey"] = _require_key()
    try:
        response = httpx.get(f"{BASE_URL}{path}", params=params, timeout=TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # exc carries the full URL including the key, so only the status and the
        # API's own message body are safe to surface.
        raise RuntimeError(
            f"odds api {path} failed: HTTP {exc.response.status_code} "
            f"{exc.response.text[:200]}"
        ) from None
    except httpx.HTTPError as exc:
        raise RuntimeError(f"odds api {path} failed: {type(exc).__name__}") from None

    remaining = response.headers.get("x-requests-remaining")
    return response.json(), int(remaining) if remaining is not None else None


def events() -> tuple[list[dict], int | None]:
    """Upcoming NFL events. Free: this endpoint costs no credits."""
    body, remaining = _get(f"/sports/{SPORT}/events")
    if not isinstance(body, list):
        raise RuntimeError("odds api events returned an unexpected shape")
    return body, remaining


def event_odds(event_id: str, markets: list[str]) -> tuple[dict, int | None]:
    """Player props for one event.

    Costs one credit per market. Player props are not available on the bulk odds
    endpoint, so there is no cheaper way to cover a slate than one call per game.
    """
    return _get(
        f"/sports/{SPORT}/events/{event_id}/odds",
        regions=REGION,
        markets=",".join(markets),
        oddsFormat="american",
    )
