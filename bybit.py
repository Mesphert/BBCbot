"""
bybit.py — Bybit V5 REST API client.

Public endpoints (kline data) — no auth needed.
Private endpoints (orders, balance) — HMAC signed headers required.

Currently only public endpoints are used (signal bot phase).
Private endpoint auth is ready for the trading bot phase.
"""

import hmac
import hashlib
import logging
import time
import requests
import pandas as pd
from datetime import datetime
from typing import Optional

import config

logger = logging.getLogger(__name__)

BYBIT_BASE_URL  = "https://api.bybit.com"
KLINE_ENDPOINT  = "/v5/market/kline"


# ------------------------------------------------------------------
# HMAC Authentication (private endpoints — trading bot phase)
# ------------------------------------------------------------------

def _auth_headers(params: str = "") -> dict:
    """
    Build HMAC-signed headers for private Bybit V5 endpoints.

    Args:
        params: query string or JSON body as a plain string

    Returns:
        Dict of headers to include in the request.

    Usage (future trading bot):
        headers = _auth_headers("symbol=BTCUSDT&qty=0.001")
        requests.post(url, headers=headers, json=payload)
    """
    if not config.BYBIT_API_KEY or not config.BYBIT_API_SECRET:
        raise ValueError(
            "BYBIT_API_KEY and BYBIT_API_SECRET must be set "
            "in Render environment variables."
        )

    timestamp  = str(int(time.time() * 1000))
    recv_window = "5000"

    # Bybit V5 signature string: timestamp + api_key + recv_window + params
    sign_str  = f"{timestamp}{config.BYBIT_API_KEY}{recv_window}{params}"
    signature = hmac.new(
        config.BYBIT_API_SECRET.encode("utf-8"),
        sign_str.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return {
        "X-BAPI-API-KEY":   config.BYBIT_API_KEY,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-SIGN":      signature,
        "X-BAPI-RECV-WINDOW": recv_window,
        "Content-Type":     "application/json",
    }


# ------------------------------------------------------------------
# Public endpoints (current — signal bot)
# ------------------------------------------------------------------

def fetch_candles(symbol: str, interval: str,
                  limit: int = 100) -> Optional[pd.DataFrame]:
    """
    Fetch closed kline candles from Bybit V5 public endpoint.
    No API key required.

    Args:
        symbol:   e.g. "BTCUSDT"
        interval: Bybit interval string — "3","5","15","30","60","240","D","W"
        limit:    number of candles to fetch (max 200)

    Returns:
        DataFrame with columns [open, high, low, close, volume]
        indexed by UTC-aware datetime, sorted ascending.
        Last (unclosed) candle is always dropped.
        Returns None on any error.
    """
    try:
        params = {
            "category": "linear",
            "symbol":   symbol,
            "interval": interval,
            "limit":    limit + 1,  # +1 to drop the unclosed candle
        }
        resp = requests.get(
            BYBIT_BASE_URL + KLINE_ENDPOINT,
            params=params,
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("retCode") != 0:
            logger.error(
                f"Bybit API error [{interval}]: "
                f"{data.get('retMsg')} (code {data.get('retCode')})"
            )
            return None

        raw = data["result"]["list"]
        if not raw:
            logger.warning(
                f"Bybit returned empty kline list for {symbol} {interval}"
            )
            return None

        # Bybit returns newest candle first — reverse to ascending
        raw = list(reversed(raw))

        df = pd.DataFrame(raw, columns=[
            "time", "open", "high", "low", "close", "volume", "turnover"
        ])

        # Convert ms timestamp to UTC datetime
        df["time"] = pd.to_datetime(
            df["time"].astype(float), unit="ms", utc=True
        )
        df.set_index("time", inplace=True)

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        df = df[["open", "high", "low", "close", "volume"]]

        # Drop last row — currently open candle
        df = df.iloc[:-1]

        logger.debug(
            f"Fetched {len(df)} closed candles | {symbol} {interval} | "
            f"last={df.index[-1]}"
        )
        return df

    except requests.exceptions.Timeout:
        logger.error(f"Bybit request timed out for {symbol} {interval}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Bybit request failed for {symbol} {interval}: {e}")
        return None
    except Exception as e:
        logger.error(
            f"Unexpected error fetching {symbol} {interval}: {e}",
            exc_info=True
        )
        return None


def get_new_candles(symbol: str, interval: str,
                    last_candle_time) -> Optional[pd.DataFrame]:
    """
    Fetch candles and return only rows newer than last_candle_time.
    If last_candle_time is None (first run), returns all fetched candles.

    Args:
        last_candle_time: UTC-aware datetime or None

    Returns:
        DataFrame of new closed candles only, or None on error.
    """
    df = fetch_candles(symbol, interval, limit=config.CANDLE_LIMIT)
    if df is None:
        return None

    if last_candle_time is not None:
        df = df[df.index > last_candle_time]

    if df.empty:
        logger.debug(f"No new candles for {symbol} {interval}")
        return None

    return df
