"""The only module that talks to Open-Meteo.

Free and keyless, so unlike `odds_api.py` there is no secret here and no
balance to watch. The single request path is kept anyway: a later provider may
need a key, and the boundary is far easier to add now than to retrofit around
scattered calls.

Two endpoints, because the forecast API needs coordinates and nothing in
nflverse publishes them. The geocoder resolves places but not venues, which is
why `forecast.py` maps each stadium to a city rather than to a point.
"""

from __future__ import annotations

from typing import Any

import httpx

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

TIMEOUT = httpx.Timeout(30.0)

# Fahrenheit and miles per hour are requested from the provider rather than
# converted here, so the stored column names cannot drift from their units.
HOURLY_FIELDS = "temperature_2m,wind_speed_10m,precipitation_probability"
TEMPERATURE_UNIT = "fahrenheit"
WIND_SPEED_UNIT = "mph"

# The provider's horizon, not a choice of ours. Games beyond it have no
# forecast to fetch and the loader reports them rather than failing.
FORECAST_DAYS = 16


def _get(url: str, **params: Any) -> Any:
    """GET one endpoint, with failures reduced to a short message."""
    try:
        response = httpx.get(url, params=params, timeout=TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"open-meteo request failed: HTTP {exc.response.status_code} "
            f"{exc.response.text[:200]}"
        ) from None
    except httpx.HTTPError as exc:
        raise RuntimeError(f"open-meteo request failed: {type(exc).__name__}") from None
    return response.json()


def geocode_many(place: str, count: int) -> list[dict]:
    """Up to `count` matches for a place name, best first.

    Several are needed because the best match is not always the right one:
    "Santa Clara" leads with Cuba and "Saint-Denis" with Reunion, so the caller
    filters by country and state rather than taking the top hit.
    """
    body = _get(GEOCODING_URL, name=place, count=count)
    return body.get("results") or []


def hourly_forecast(latitude: float, longitude: float) -> dict:
    """Sixteen days of hourly temperature, wind and precipitation probability.

    Returns the provider's `hourly` block: parallel lists keyed by `time`.
    """
    body = _get(
        FORECAST_URL,
        latitude=latitude,
        longitude=longitude,
        hourly=HOURLY_FIELDS,
        temperature_unit=TEMPERATURE_UNIT,
        wind_speed_unit=WIND_SPEED_UNIT,
        forecast_days=FORECAST_DAYS,
        timezone="UTC",
    )
    hourly = body.get("hourly")
    if not isinstance(hourly, dict) or "time" not in hourly:
        raise RuntimeError("open-meteo forecast returned an unexpected shape")
    return hourly
