"""
scheduler.py — 3-minute heartbeat scheduler.

The 3m candle is the heartbeat — the bot wakes every 3 minutes and checks
which higher timeframes are also closing at that moment.

Binance interval strings: "3m","5m","15m","30m","1h","4h","1d","1w"
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
    """Calculate the next 3-minute candle close time (UTC)."""
    if now is None:
        now = _now_utc()

    total_seconds  = now.minute * 60 + now.second
    period_seconds = 3 * 60
    elapsed        = total_seconds % period_seconds
    remaining      = period_seconds - elapsed

    return now + timedelta(seconds=remaining + 1)


def which_tfs_closing(now: datetime) -> List[str]:
    """
    Return which configured timeframes are closing at this UTC datetime.
    Uses TF_MINUTES from config — works with any interval string format.
    """
    closing        = []
    minute_of_day  = now.hour * 60 + now.minute
    day_of_week    = now.weekday()   # 0=Monday

    for interval in config.TIMEFRAMES:
        tf_mins = config.TF_MINUTES.get(interval)
        if tf_mins is None:
            continue

        if interval == "1d":
            if now.hour == 0 and now.minute == 0:
                closing.append(interval)

        elif interval == "1w":
            if day_of_week == 0 and now.hour == 0 and now.minute == 0:
                closing.append(interval)

        else:
            if tf_mins > 0 and minute_of_day % tf_mins == 0:
                closing.append(interval)

    return closing


def sleep_until_next_close():
    """Block until the next 3m candle close. Returns wake UTC datetime."""
    now       = _now_utc()
    wake_time = next_3m_close(now)
    sleep_secs = (wake_time - now).total_seconds()

    logger.info(
        f"Sleeping {sleep_secs:.0f}s until next 3m close "
        f"at {wake_time.strftime('%H:%M:%S')} UTC"
    )
    time.sleep(max(0, sleep_secs))

    woke_at = _now_utc()
    logger.info(f"Woke up at {woke_at.strftime('%H:%M:%S')} UTC")
    return woke_at
