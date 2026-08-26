"""
session.py — Trading session detector (stateless).

Reuses the same logic as the local engine's session_detector.py.
Converts session windows from America/New_York to broker timezone (UTC for Bybit).
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Any, Optional

import config

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")


class SessionDetector:

    def __init__(self):
        self.broker_tz = ZoneInfo(config.BROKER_TIMEZONE)
        self.sessions  = config.SESSIONS

    def detect(self, candle_ts: datetime) -> List[Dict[str, Any]]:
        """Return session info for all configured sessions."""
        candle_ts = self._ensure_tz(candle_ts)
        results   = []

        for name, window in self.sessions.items():
            start, end = self._resolve_window(candle_ts, window)
            results.append({
                "session": name,
                "start":   start,
                "end":     end,
                "active":  start <= candle_ts < end,
            })

        return results

    def active_sessions(self, candle_ts: datetime) -> List[str]:
        """Return names of currently active sessions."""
        return [s["session"] for s in self.detect(candle_ts) if s["active"]]

    def _ensure_tz(self, ts: datetime) -> datetime:
        if ts.tzinfo is None:
            return ts.replace(tzinfo=self.broker_tz)
        return ts.astimezone(self.broker_tz)

    def _resolve_window(self, candle_ts: datetime, window: dict):
        candle_ny = candle_ts.astimezone(NY_TZ)
        today_ny  = candle_ny.date()

        h_start, m_start = map(int, window["start"].split(":"))
        h_end,   m_end   = map(int, window["end"].split(":"))

        start_ny = datetime(today_ny.year, today_ny.month, today_ny.day,
                            h_start, m_start, tzinfo=NY_TZ)

        crosses_midnight = (
            (h_start, m_start) >= (h_end, m_end) and (h_end, m_end) != (0, 0)
        ) or ((h_end, m_end) == (0, 0) and (h_start, m_start) > (0, 0))

        if crosses_midnight:
            next_day = today_ny + timedelta(days=1)
            end_ny   = datetime(next_day.year, next_day.month, next_day.day,
                                h_end, m_end, tzinfo=NY_TZ)
            if candle_ny < end_ny and candle_ny.time() < datetime(
                    1, 1, 1, h_start, m_start).time():
                prev_day = today_ny - timedelta(days=1)
                start_ny = datetime(prev_day.year, prev_day.month, prev_day.day,
                                    h_start, m_start, tzinfo=NY_TZ)
                end_ny   = datetime(today_ny.year, today_ny.month, today_ny.day,
                                    h_end, m_end, tzinfo=NY_TZ)
        else:
            end_ny = datetime(today_ny.year, today_ny.month, today_ny.day,
                              h_end, m_end, tzinfo=NY_TZ)

        return (start_ny.astimezone(self.broker_tz),
                end_ny.astimezone(self.broker_tz))
