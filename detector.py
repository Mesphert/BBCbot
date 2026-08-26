"""
detector.py — Stateless BOS/CHOCH/CRT detector.

All state (swing points, structure direction) is read from and written
to Neon Postgres — never stored in Python variables. This means the
detector survives Render restarts with zero data loss.

Detection logic mirrors the local engine:
  - Asymmetric pivot detection (n_left=5, n_right=2)
  - Candle direction gates: bullish candle → only check swing highs
  - Fresh/used swing tracking via Neon swing_state table
  - BOS = break in same direction as last structure
  - CHOCH = break against last structure direction
  - CRT = candle sweeps prev high/low and closes back inside range
"""

import logging
import pandas as pd
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass

import config
import mongo as neon

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    symbol:      str
    timeframe:   str
    event:       str        # "BOS" / "CHOCH" / "CRT"
    direction:   str        # "bullish" / "bearish"
    price:       float
    candle_time: datetime
    session:     str
    description: str


# ------------------------------------------------------------------
# Swing detection (stateless — operates on DataFrame)
# ------------------------------------------------------------------

def detect_swings(df: pd.DataFrame) -> dict:
    """
    Detect confirmed swing highs and lows using asymmetric pivot logic.
    Returns {"highs": [...], "lows": [...]}
    Each entry: {"price": float, "candle_time": datetime}
    """
    n_left  = config.SWING_LOOKBACK
    n_right = config.SWING_RIGHT

    highs, lows = [], []

    for i in range(n_left, len(df) - n_right):
        ts      = df.index[i]
        price_h = df["high"].iloc[i]
        price_l = df["low"].iloc[i]

        left_h  = df["high"].iloc[i - n_left: i]
        right_h = df["high"].iloc[i + 1: i + n_right + 1]
        left_l  = df["low"].iloc[i - n_left: i]
        right_l = df["low"].iloc[i + 1: i + n_right + 1]

        # Swing HIGH: strictly greater left, >= right
        if price_h > left_h.max() and price_h >= right_h.max():
            highs.append({"price": float(price_h),
                          "candle_time": ts.to_pydatetime()})

        # Swing LOW: strictly lower left, <= right (same candle allowed)
        if price_l < left_l.min() and price_l <= right_l.min():
            lows.append({"price": float(price_l),
                         "candle_time": ts.to_pydatetime()})

    return {"highs": highs, "lows": lows}


# ------------------------------------------------------------------
# Main detector
# ------------------------------------------------------------------

def process_candles(df: pd.DataFrame, symbol: str,
                    timeframe: str, session: str) -> List[Signal]:
    """
    Process a DataFrame of new closed candles for one symbol/TF.

    Steps:
      1. Load state from Neon (swing points, structure direction)
      2. Detect new swing points from df and upsert to Neon
      3. For each new candle:
           a. Gate on candle direction
           b. Check BOS/CHOCH against fresh swings
           c. Check CRT against previous candle
      4. Save signals to Neon
      5. Update structure state in Neon

    Returns list of Signal objects fired this cycle.
    """
    if df is None or df.empty:
        return []

    signals: List[Signal] = []

    # 1. Load state from Neon
    swing_state = neon.get_fresh_swings(symbol, timeframe)
    struct_state = neon.get_structure_state(symbol, timeframe)

    last_direction = struct_state["direction"]
    last_type      = struct_state["type"]

    fresh_highs = swing_state["highs"]   # list of {"price", "candle_time"}
    fresh_lows  = swing_state["lows"]

    # 2. Detect new swing points and register unknown ones to Neon
    new_swings = detect_swings(df)

    known_high_times = {s["candle_time"] for s in fresh_highs}
    known_low_times  = {s["candle_time"] for s in fresh_lows}

    for s in new_swings["highs"]:
        if s["candle_time"] not in known_high_times:
            neon.upsert_swing(symbol, timeframe, "high",
                              s["price"], s["candle_time"], fresh=True)
            fresh_highs.append(s)
            known_high_times.add(s["candle_time"])

    for s in new_swings["lows"]:
        if s["candle_time"] not in known_low_times:
            neon.upsert_swing(symbol, timeframe, "low",
                              s["price"], s["candle_time"], fresh=True)
            fresh_lows.append(s)
            known_low_times.add(s["candle_time"])

    # 3. Process each new candle
    for i in range(len(df)):
        candle   = df.iloc[i]
        ts       = df.index[i].to_pydatetime()
        close    = float(candle["close"])
        open_    = float(candle["open"])

        # ── Gate on candle direction ─────────────────────────────────
        if close > open_:
            candle_dir = "bullish"
        elif close < open_:
            candle_dir = "bearish"
        else:
            continue   # doji — skip

        # ── BOS / CHOCH ──────────────────────────────────────────────
        if candle_dir == "bullish":
            broken = [s for s in fresh_highs
                      if close > s["price"] and s["candle_time"] < ts]
            if broken:
                broken.sort(key=lambda s: s["candle_time"])
                nearest    = broken[-1]
                event_type = _classify(candle_dir, last_direction)

                sig = Signal(
                    symbol      = symbol,
                    timeframe   = timeframe,
                    event       = event_type,
                    direction   = "bullish",
                    price       = nearest["price"],
                    candle_time = ts,
                    session     = session,
                    description = (
                        f"{event_type} bullish: close {close:.2f} broke "
                        f"swing high {nearest['price']:.2f} "
                        f"[prev: {last_direction} {last_type}]"
                    )
                )
                signals.append(sig)
                last_direction = "bullish"
                last_type      = event_type

                # Retire all broken highs
                for s in broken:
                    neon.retire_swing(symbol, timeframe, "high",
                                      s["candle_time"])
                fresh_highs = [s for s in fresh_highs
                               if s not in broken]

        else:  # bearish candle
            broken = [s for s in fresh_lows
                      if close < s["price"] and s["candle_time"] < ts]
            if broken:
                broken.sort(key=lambda s: s["candle_time"])
                nearest    = broken[-1]
                event_type = _classify(candle_dir, last_direction)

                sig = Signal(
                    symbol      = symbol,
                    timeframe   = timeframe,
                    event       = event_type,
                    direction   = "bearish",
                    price       = nearest["price"],
                    candle_time = ts,
                    session     = session,
                    description = (
                        f"{event_type} bearish: close {close:.2f} broke "
                        f"swing low {nearest['price']:.2f} "
                        f"[prev: {last_direction} {last_type}]"
                    )
                )
                signals.append(sig)
                last_direction = "bearish"
                last_type      = event_type

                for s in broken:
                    neon.retire_swing(symbol, timeframe, "low",
                                      s["candle_time"])
                fresh_lows = [s for s in fresh_lows
                              if s not in broken]

        # ── CRT ──────────────────────────────────────────────────────
        if i > 0:
            prev      = df.iloc[i - 1]
            crt_sig   = _check_crt(candle, prev, ts, symbol,
                                   timeframe, session)
            if crt_sig:
                signals.append(crt_sig)

    # 4. Save all signals to Neon
    for sig in signals:
        neon.save_signal(
            symbol      = sig.symbol,
            timeframe   = sig.timeframe,
            event       = sig.event,
            direction   = sig.direction,
            price       = sig.price,
            candle_time = sig.candle_time,
            session     = sig.session,
            description = sig.description,
        )

    # 5. Update structure state in Neon
    if last_direction and last_type:
        neon.set_structure_state(symbol, timeframe, last_direction, last_type)

    return signals


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _classify(break_direction: str, last_direction: Optional[str]) -> str:
    if last_direction is None:
        return "BOS"
    if break_direction == last_direction:
        return "BOS"
    return "CHOCH"


def _check_crt(candle, prev, ts: datetime,
               symbol: str, timeframe: str, session: str) -> Optional[Signal]:
    prev_high  = float(prev["high"])
    prev_low   = float(prev["low"])
    curr_open  = float(candle["open"])
    curr_high  = float(candle["high"])
    curr_low   = float(candle["low"])
    curr_close = float(candle["close"])

    # Bullish CRT
    if (curr_close > curr_open
            and curr_low < prev_low
            and prev_low <= curr_close <= prev_high):
        return Signal(
            symbol      = symbol,
            timeframe   = timeframe,
            event       = "CRT",
            direction   = "bullish",
            price       = curr_low,
            candle_time = ts,
            session     = session,
            description = (
                f"Bullish CRT: swept {curr_low:.2f} below prev low "
                f"{prev_low:.2f}, closed {curr_close:.2f} inside range"
            )
        )

    # Bearish CRT
    if (curr_close < curr_open
            and curr_high > prev_high
            and prev_low <= curr_close <= prev_high):
        return Signal(
            symbol      = symbol,
            timeframe   = timeframe,
            event       = "CRT",
            direction   = "bearish",
            price       = curr_high,
            candle_time = ts,
            session     = session,
            description = (
                f"Bearish CRT: swept {curr_high:.2f} above prev high "
                f"{prev_high:.2f}, closed {curr_close:.2f} inside range"
            )
        )

    return None
