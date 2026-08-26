"""
bybit.py — Bybit V5 REST API kline fetcher.

No API key required for public market data.
Returns a pandas DataFrame of closed OHLCV candles.
"""

import logging
import requests
import pandas as pd
from datetime import datetime, timezone
from typing import Optional

import config

logger = logging.getLogger(__name__)

BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"


def fetch_candles(symbol: str, interval: str,
                  limit: int = 100) -> Optional[pd.DataFrame]:
    """
    Fetch closed kline candles from Bybit V5.

    Args:
        symbol:   e.g. "BTCUSDT"
        interval: Bybit interval string — "3","5","15","30","60","240","D","W"
        limit:    number of candles to fetch (max 200)

    Returns:
        DataFrame with columns [open, high, low, close, volume]
        indexed by UTC-aware datetime, sorted ascending.
        The last candle (current unclosed) is always dropped.
        Returns None on error.
    """
    try:
        params = {
            "category": "linear",
            "symbol":   symbol,
            "interval": interval,
            "limit":    limit + 1,   # +1 so we can drop the unclosed candle
        }
        resp = requests.get(BYBIT_KLINE_URL, params=params, timeout=10)
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
            logger.warning(f"Bybit returned empty kline list for {symbol} {interval}")
            return None

        # Bybit returns: [startTime, open, high, low, close, volume, turnover]
        # Newest candle is first — reverse to get ascending order
        raw = list(reversed(raw))

        df = pd.DataFrame(raw, columns=[
            "time", "open", "high", "low", "close", "volume", "turnover"
        ])

        # Convert timestamp (ms) to UTC datetime
        df["time"] = pd.to_datetime(df["time"].astype(float), unit="ms", utc=True)
        df.set_index("time", inplace=True)

        # Cast OHLCV to float
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        df = df[["open", "high", "low", "close", "volume"]]

        # Drop the last row — it's the currently open (unclosed) candle
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
        logger.error(f"Unexpected error fetching {symbol} {interval}: {e}",
                     exc_info=True)
        return None


def get_new_candles(symbol: str, interval: str,
                    last_candle_time) -> Optional[pd.DataFrame]:
    """
    Fetch candles and return only rows newer than last_candle_time.
    If last_candle_time is None (first run), returns all fetched candles.

    Args:
        last_candle_time: datetime (UTC-aware) or None

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
