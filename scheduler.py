"""
scheduler.py — 3-minute heartbeat scheduler.

The 3m candle is the heartbeat — the bot wakes every 3 minutes and checks
which higher timeframes are also closing at that moment. All timeframes
that are multiples of 3 minutes close simultaneously at predictable times.

Logic:
  - Sleep until the next 3m candle close (aligned to UTC clock)
  - On wake, check which configured TFs are closing right now
  - Return the list of TF interval strings to process this cycle

Bybit interval strings: "3","5","15","30","60","240","D","W"
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import List

import config

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def next_3m_close(now: datetime = None) -> datetime:
    """
    Calculate the next 3-minute candle close time (UTC).
    3m candles close at :00, :03, :06, :09 ... of every hour.
    """
    if now is None:
        now = _now_utc()

    # How many seconds into the current 3m period are we?
    total_seconds = now.minute * 60 + now.second
    period_seconds = 3 * 60
    elapsed = total_seconds % period_seconds
    remaining = period_seconds - elapsed

    # Add a 1-second buffer to ensure the candle is fully closed
    return now + timedelta(seconds=remaining + 1)


def which_tfs_closing(now: datetime) -> List[str]:
    """
    Given a UTC datetime, return which configured timeframes are
    closing at this exact minute.

    A TF closes when the current minute (from midnight UTC) is a
    multiple of its duration in minutes.

    Special handling:
      - "D" (daily)  closes at 00:00 UTC
      - "W" (weekly) closes at 00:00 UTC on Monday
    """
    closing = []

    minute_of_day  = now.hour * 60 + now.minute
    day_of_week    = now.weekday()   # 0=Monday ... 6=Sunday

    for interval in config.TIMEFRAMES:
        tf_mins = config.TF_MINUTES.get(interval)
        if tf_mins is None:
            continue

        if interval == "D":
            # Daily closes at exactly midnight UTC
            if now.hour == 0 and now.minute == 0:
                closing.append(interval)

        elif interval == "W":
            # Weekly closes at midnight UTC on Monday (start of new week)
            if day_of_week == 0 and now.hour == 0 and now.minute == 0:
                closing.append(interval)

        else:
            # Intraday: closes when minute_of_day is a multiple of tf_mins
            if tf_mins > 0 and minute_of_day % tf_mins == 0:
                closing.append(interval)

    return closing


def sleep_until_next_close():
    """
    Block until the next 3m candle close.
    Returns the UTC datetime when we woke up.
    """
    now        = _now_utc()
    wake_time  = next_3m_close(now)
    sleep_secs = (wake_time - now).total_seconds()

    logger.info(
        f"Sleeping {sleep_secs:.0f}s until next 3m close "
        f"at {wake_time.strftime('%H:%M:%S')} UTC"
    )
    time.sleep(max(0, sleep_secs))

    woke_at = _now_utc()
    logger.info(f"Woke up at {woke_at.strftime('%H:%M:%S')} UTC")
    return woke_at
