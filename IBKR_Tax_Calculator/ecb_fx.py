"""
ecb_fx.py
----------
Fetch official ECB daily reference exchange rates for any currency against EUR.
Uses the ECB Data Portal REST API:
  https://data.ecb.europa.eu/help/api/data

The key series format is:  EXR / D.{CURRENCY}.EUR.SP00.A
  - D     = daily frequency
  - CURRENCY = target currency (e.g. USD, GBP, JPY)
  - EUR   = Euro (denominator)
  - SP00  = foreign exchange reference rate
  - A     = average / standardised measure

The API returns OBS_VALUE which is the number of CURRENCY per 1 EUR.
We return this directly as "{CURRENCY} per EUR" (i.e. a rate > 1 means 1 EUR buys more than 1 unit of CURRENCY).
"""

import datetime
import io

import pandas as pd
import requests


_ECB_API_BASE = "https://data-api.ecb.europa.eu/service/data"
_MAX_LOOKBACK_DAYS = 10


def _build_series_key(currency: str) -> str:
    """Build the ECB series key for a given currency against EUR."""
    return f"EXR/D.{currency.upper()}.EUR.SP00.A"


def fetch_ecb_rate_for_date(currency: str, target_date: datetime.date) -> tuple[float | None, datetime.date | None]:
    """Fetch the ECB reference exchange rate for `currency` against EUR on `target_date`.

    Because markets are closed on weekends and some holidays, the ECB does not
    publish rates for every calendar day.  If no rate is found for `target_date`
    this function walks backwards up to _MAX_LOOKBACK_DAYS days to find the most
    recent available rate.

    Parameters
    ----------
    currency : str
        Three-letter currency code (e.g. "USD", "GBP", "JPY").
    target_date : datetime.date
        The date for which to fetch the rate.

    Returns
    -------
    (rate: float, actual_date: datetime.date)
        rate        – number of `currency` per 1 EUR (e.g. 1.0321 for USD/EUR)
        actual_date – the date for which the rate was actually published
                      (may differ from target_date if it fell on a weekend/holiday)

    Returns (None, None) on network error or if no data is found.
    """
    if currency.upper() == "EUR":
        return 1.0, target_date

    start = target_date - datetime.timedelta(days=_MAX_LOOKBACK_DAYS)
    end = target_date

    series_key = _build_series_key(currency)
    url = (
        f"{_ECB_API_BASE}/{series_key}"
        f"?startPeriod={start.isoformat()}"
        f"&endPeriod={end.isoformat()}"
        f"&format=csvdata"
    )

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        return None, None

    content = resp.text.strip()
    if not content:
        return None, None

    try:
        df = pd.read_csv(io.StringIO(content))
    except Exception:
        return None, None

    if df.empty or "TIME_PERIOD" not in df.columns or "OBS_VALUE" not in df.columns:
        return None, None

    df["TIME_PERIOD"] = pd.to_datetime(df["TIME_PERIOD"]).dt.date
    df = df.sort_values("TIME_PERIOD", ascending=False)

    eligible = df[df["TIME_PERIOD"] <= target_date]
    if eligible.empty:
        return None, None

    row = eligible.iloc[0]
    rate = float(row["OBS_VALUE"])
    actual_date = row["TIME_PERIOD"]
    return rate, actual_date


def fetch_ecb_rate_range(currency: str, start_date: datetime.date, end_date: datetime.date) -> dict[datetime.date, float]:
    """Fetch all ECB reference rates for `currency` against EUR between start_date and end_date (inclusive).

    Returns a dict mapping date -> rate (currency per EUR).
    This is much more efficient than calling fetch_ecb_rate_for_date() for every date,
    as it makes a single API call per currency.
    """
    if currency.upper() == "EUR":
        return {}

    series_key = _build_series_key(currency)
    url = (
        f"{_ECB_API_BASE}/{series_key}"
        f"?startPeriod={start_date.isoformat()}"
        f"&endPeriod={end_date.isoformat()}"
        f"&format=csvdata"
    )

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        return {}

    content = resp.text.strip()
    if not content:
        return {}

    try:
        df = pd.read_csv(io.StringIO(content))
    except Exception:
        return {}

    if df.empty or "TIME_PERIOD" not in df.columns or "OBS_VALUE" not in df.columns:
        return {}

    df["TIME_PERIOD"] = pd.to_datetime(df["TIME_PERIOD"]).dt.date
    return dict(zip(df["TIME_PERIOD"], df["OBS_VALUE"].astype(float)))


def fetch_ecb_rates_batch(currencies: list[str], start_date: datetime.date, end_date: datetime.date) -> dict[str, dict[datetime.date, float]]:
    """Fetch ECB reference rates for multiple currencies in a single batch per currency.

    Returns a dict: currency_code -> {date: rate} (currency per EUR).
    This is more efficient than calling fetch_ecb_rate_range() in a loop when
    multiple currencies need to be converted.
    """
    result: dict[str, dict[datetime.date, float]] = {}
    for ccy in currencies:
        upper = ccy.upper()
        if upper == "EUR":
            continue
        result[upper] = fetch_ecb_rate_range(upper, start_date, end_date)
    return result


# ─── Deprecated backward-compatible wrappers ────────────────────────────────

def fetch_usdeur_for_date(target_date: datetime.date) -> tuple[float | None, datetime.date | None]:
    """Deprecated: use fetch_ecb_rate_for_date('USD', target_date) instead."""
    return fetch_ecb_rate_for_date("USD", target_date)


def fetch_usdeur_range(start_date: datetime.date, end_date: datetime.date) -> dict[datetime.date, float]:
    """Deprecated: use fetch_ecb_rate_range('USD', start_date, end_date) instead."""
    return fetch_ecb_rate_range("USD", start_date, end_date)
