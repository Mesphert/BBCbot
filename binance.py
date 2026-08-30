"""
binance.py — Binance Futures V1 kline fetcher.

Replaces bybit.py. Uses Binance USDT-M Futures public REST endpoint.
No API key required for kline data.
No proxy needed — Binance allows requests from all cloud providers.

Binance kline endpoint:
  GET https://fapi.binance.com/fapi/v1/klines
  ?symbol=BTCUSDT&interval=3m&limit=11

Interval format: "3m","5m","15m","30m","1h","4h","1d","1w"
"""

import logging
import requests
import pandas as pd
from typing import Optional

import config

logger = logging.getLogger(__name__)

BINANCE_KLINE_URL = "https://data.binance.com/fapi/v1/klines"


def fetch_candles(symbol: str, interval: str,
                  limit: int = 100) -> Optional[pd.DataFrame]:
    """
    Fetch closed kline candles directly from Binance Futures.

    Args:
        symbol:   e.g. "BTCUSDT"
        interval: Binance interval string — "3m","5m","15m","30m","1h","4h","1d","1w"
        limit:    number of candles (max 1500 on Binance)

    Returns:
        DataFrame with columns [open, high, low, close, volume]
        indexed by UTC-aware datetime, sorted ascending.
        Last (unclosed) candle is always dropped.
        Returns None on any error.
    """
    try:
        params = {
            "symbol":   symbol,
            "interval": interval,
            "limit":    limit + 1,  # +1 to drop the unclosed candle
        }

        resp = requests.get(
            BINANCE_KLINE_URL,
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()

        if not raw:
            logger.warning(f"Binance returned empty kline list for {symbol} {interval}")
            return None

        # Binance returns oldest first — already ascending
        # Each row: [openTime, open, high, low, close, volume, closeTime, ...]
        df = pd.DataFrame(raw, columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_base", "taker_quote", "ignore"
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

    except requests.exceptions.Timeout:
        logger.error(f"Binance request timed out for {symbol} {interval}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Binance request failed for {symbol} {interval}: {e}")
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

    First run (last_candle_time is None):
        Fetches full CANDLE_LIMIT (100) for backfill and swing seeding.

    Live run (last_candle_time is set):
        Fetches only 10 candles — enough for swing confirmation
        while keeping requests minimal.
        Duplicate signals prevented by MongoDB unique index.
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
