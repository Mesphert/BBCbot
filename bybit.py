"""
bybit.py — Bybit V5 kline fetcher via Cloudflare Worker proxy.

Render's IPs are blocked by Bybit directly, so all kline requests
are routed through a Cloudflare Worker which runs on Cloudflare's
global edge network — never blocked by exchanges.

Flow:
  Render bot → POST to Cloudflare Worker → GET to Bybit → data back

CLOUDFLARE_WORKER_URL is set as an environment variable on Render.
No auth header needed — Cloudflare Workers are public endpoints.

Public kline endpoints don't require API keys.
BYBIT_API_KEY / BYBIT_API_SECRET are reserved for the trading bot phase
(private endpoints: place orders, check balance etc).
"""

import hmac
import hashlib
import logging
import time
import requests
import pandas as pd
from typing import Optional

import config

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# HMAC Authentication (private endpoints — trading bot phase)
# ------------------------------------------------------------------

def _auth_headers(params: str = "") -> dict:
    """
    Build HMAC-signed headers for private Bybit V5 endpoints.
    Reserved for trading bot phase — not used currently.
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
# Proxy request via Cloudflare Worker
# ------------------------------------------------------------------

def _fetch_via_proxy(symbol: str, interval: str,
                     limit: int) -> Optional[dict]:
    """
    POST to Cloudflare Worker which forwards the GET to Bybit.
    Returns raw Bybit JSON dict, or None on any error.
    """
    if not config.CLOUDFLARE_WORKER_URL:
        logger.error("CLOUDFLARE_WORKER_URL not set in environment variables.")
        return None

    payload = {
        "symbol":   symbol,
        "interval": interval,
        "limit":    limit,
    }

    try:
        resp = requests.post(
            config.CLOUDFLARE_WORKER_URL,
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    except requests.exceptions.Timeout:
        logger.error(f"Cloudflare Worker timed out for {symbol} {interval}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Cloudflare Worker request failed for {symbol} {interval}: {e}")
        return None


# ------------------------------------------------------------------
# Public interface
# ------------------------------------------------------------------

def fetch_candles(symbol: str, interval: str,
                  limit: int = 100) -> Optional[pd.DataFrame]:
    """
    Fetch closed kline candles via Cloudflare Worker → Bybit V5.

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
    # +1 so we can drop the currently open candle
    data = _fetch_via_proxy(symbol, interval, limit + 1)

    if data is None:
        return None

    # Check for proxy-level error (Worker catch block)
    if "error" in data and "retCode" not in data:
        logger.error(f"Cloudflare Worker error [{interval}]: {data.get('error')}")
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

    # Bybit returns newest first — reverse to ascending
    raw = list(reversed(raw))

    df = pd.DataFrame(raw, columns=[
        "time", "open", "high", "low", "close", "volume", "turnover"
    ])

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


def get_new_candles(symbol: str, interval: str,
                    last_candle_time) -> Optional[pd.DataFrame]:
    """
    Fetch candles and return only rows newer than last_candle_time.

    First run (last_candle_time is None):
        Fetches full CANDLE_LIMIT (100) for backfill and swing seeding.

    Live run (last_candle_time is set):
        Fetches only 10 candles — enough to confirm new swing pivots
        while keeping proxy requests minimal.
        Duplicate signals are prevented by MongoDB unique index.
    """
    if last_candle_time is None:
        limit = config.CANDLE_LIMIT   # 100 — full backfill
    else:
        limit = 10                    # live — small window only

    df = fetch_candles(symbol, interval, limit=limit)
    if df is None:
        return None

    if last_candle_time is not None:
        df = df[df.index > last_candle_time]

    if df.empty:
        logger.debug(f"No new candles for {symbol} {interval}")
        return None

    return df
