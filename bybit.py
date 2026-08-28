"""
bybit.py — Bybit V5 kline fetcher via Supabase Edge Function proxy.

Render's IPs are blocked by Bybit directly, so all kline requests
are routed through a Supabase Edge Function which has unblocked IPs.

Flow:
  Render bot → POST to Supabase Edge Function → GET to Bybit → data back

The Supabase function URL is stored as SUPABASE_FUNCTION_URL env var on Render.
Bybit API keys are passed in the request body (stored on Render, never on Supabase).

Public endpoints (kline data) don't require API keys — they are passed
as placeholders for future private endpoint support.
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


# ------------------------------------------------------------------
# HMAC Authentication (private endpoints — trading bot phase)
# ------------------------------------------------------------------

def _auth_headers(params: str = "") -> dict:
    """
    Build HMAC-signed headers for private Bybit V5 endpoints.
    Used in the trading bot phase for placing orders etc.
    """
    if not config.BYBIT_API_KEY or not config.BYBIT_API_SECRET:
        raise ValueError(
            "BYBIT_API_KEY and BYBIT_API_SECRET must be set "
            "in Render environment variables."
        )

    timestamp   = str(int(time.time() * 1000))
    recv_window = "5000"
    sign_str    = f"{timestamp}{config.BYBIT_API_KEY}{recv_window}{params}"
    signature   = hmac.new(
        config.BYBIT_API_SECRET.encode("utf-8"),
        sign_str.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return {
        "X-BAPI-API-KEY":     config.BYBIT_API_KEY,
        "X-BAPI-TIMESTAMP":   timestamp,
        "X-BAPI-SIGN":        signature,
        "X-BAPI-RECV-WINDOW": recv_window,
        "Content-Type":       "application/json",
    }


# ------------------------------------------------------------------
# Proxy request to Supabase Edge Function
# ------------------------------------------------------------------

def _fetch_via_proxy(symbol: str, interval: str,
                     limit: int) -> Optional[dict]:
    """
    POST to the Supabase Edge Function which forwards to Bybit.
    Returns the raw Bybit JSON dict, or None on any error.
    """
    if not config.SUPABASE_FUNCTION_URL:
        logger.error("SUPABASE_FUNCTION_URL is not set in environment variables.")
        return None

    payload = {
        "symbol":     symbol,
        "interval":   interval,
        "limit":      limit,
        "api_key":    config.BYBIT_API_KEY    or "",
        "api_secret": config.BYBIT_API_SECRET or "",
    }

    try:
        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {config.SUPABASE_ANON_KEY}",
        }
        resp = requests.post(
            config.SUPABASE_FUNCTION_URL,
            json=payload,
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    except requests.exceptions.Timeout:
        logger.error(f"Supabase proxy timed out for {symbol} {interval}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Supabase proxy request failed for {symbol} {interval}: {e}")
        return None


# ------------------------------------------------------------------
# Public interface
# ------------------------------------------------------------------

def fetch_candles(symbol: str, interval: str,
                  limit: int = 100) -> Optional[pd.DataFrame]:
    """
    Fetch closed kline candles via Supabase proxy → Bybit V5.

    Args:
        symbol:   e.g. "BTCUSDT"
        interval: Bybit interval string — "3","5","15","30","60","240","D","W"
        limit:    number of candles (max 100 per Bybit limit)

    Returns:
        DataFrame with columns [open, high, low, close, volume]
        indexed by UTC-aware datetime, sorted ascending.
        Last (unclosed) candle is always dropped.
        Returns None on any error.
    """
    # Fetch limit+1 so we can drop the currently open candle
    data = _fetch_via_proxy(symbol, interval, limit + 1)

    if data is None:
        return None

    if data.get("retCode") != 0:
        logger.error(
            f"Bybit API error [{interval}]: "
            f"{data.get('retMsg')} (code {data.get('retCode')})"
        )
        return None

    raw = data.get("result", {}).get("list", [])
    if not raw:
        logger.warning(f"Empty kline list for {symbol} {interval}")
        return None

    # Bybit returns newest candle first — reverse to ascending order
    raw = list(reversed(raw))

    df = pd.DataFrame(raw, columns=[
        "time", "open", "high", "low", "close", "volume", "turnover"
    ])

    # Convert ms timestamp → UTC datetime
    df["time"] = pd.to_datetime(
        df["time"].astype(float), unit="ms", utc=True
    )
    df.set_index("time", inplace=True)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    df = df[["open", "high", "low", "close", "volume"]]

    # Drop last row — currently open (unclosed) candle
    df = df.iloc[:-1]

    logger.debug(
        f"Fetched {len(df)} closed candles | {symbol} {interval} | "
        f"last={df.index[-1]}"
    )
    return df


def get_new_candles(symbol: str, interval: str,
                    last_candle_time) -> Optional[pd.DataFrame]:
    """
    Fetch candles and return only rows newer than last_candle_time.

    First run (last_candle_time is None):
        Fetches full CANDLE_LIMIT (100) for backfill and swing seeding.

    Live run (last_candle_time is set):
        Fetches only 10 candles — enough to confirm new swing pivots
        (n_right=2 bars needed) while keeping proxy requests minimal.
        Duplicate signals are prevented by MongoDB unique index on
        (symbol, timeframe, event, direction, candle_time).

    Args:
        last_candle_time: UTC-aware datetime or None

    Returns:
        DataFrame of new closed candles only, or None on error.
    """
    if last_candle_time is None:
        # First run — fetch full history for backfill + swing detection
        limit = config.CANDLE_LIMIT
    else:
        # Live run — fetch small window, enough for swing confirmation
        limit = 10

    df = fetch_candles(symbol, interval, limit=limit)
    if df is None:
        return None

    if last_candle_time is not None:
        df = df[df.index > last_candle_time]

    if df.empty:
        logger.debug(f"No new candles for {symbol} {interval}")
        return None

    return df
