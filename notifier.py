"""
notifier.py — Sends signal alerts to a Telegram channel via Bot API.

Simple direct approach:
  POST https://api.telegram.org/bot{TOKEN}/sendMessage
  → message appears in your channel instantly

No third-party services. One HTTP request per signal.
"""

import logging
import requests
from typing import List

import config
from detector import Signal

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# Event emojis
EVENT_EMOJI = {
    "BOS":   "🔵",
    "CHOCH": "🟡",
    "CRT":   "🟣",
}

DIRECTION_EMOJI = {
    "bullish": "📈",
    "bearish": "📉",
}


def _build_message(sig: Signal) -> str:
    """Build a structured HTML Telegram message for one signal."""
    event_emoji = EVENT_EMOJI.get(sig.event, "🔔")
    dir_emoji   = DIRECTION_EMOJI.get(sig.direction, "")
    tf_label    = config.TF_LABELS.get(sig.timeframe, sig.timeframe)
    price_fmt   = f"${sig.price:,.2f}"
    time_fmt    = sig.candle_time.strftime("%Y-%m-%d %H:%M UTC")
    session     = sig.session or "—"
    direction   = sig.direction.capitalize()

    return (
        f"{event_emoji} <b>SIGNAL | {sig.symbol}</b>\n"
        f"\n"
        f"📊 <b>Pattern</b>    : {sig.event} {direction}\n"
        f"⏱ <b>Timeframe</b>  : {tf_label}\n"
        f"💰 <b>Price</b>      : {price_fmt}\n"
        f"🕐 <b>Session</b>    : {session}\n"
        f"📅 <b>Time</b>       : {time_fmt}\n"
        f"{dir_emoji} <b>Detail</b>     : {sig.description}\n"
    )


def send_signal(sig: Signal) -> bool:
    """
    Send one signal to the Telegram channel.
    Returns True on success, False on failure.
    """
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHANNEL:
        logger.warning("Telegram credentials not set — skipping notification.")
        return False

    url     = TELEGRAM_API.format(token=config.TELEGRAM_TOKEN)
    message = _build_message(sig)

    payload = {
        "chat_id":    config.TELEGRAM_CHANNEL,
        "text":       message,
        "parse_mode": "HTML",
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("ok"):
            logger.error(f"Telegram API error: {data.get('description')}")
            return False

        tf_label = config.TF_LABELS.get(sig.timeframe, sig.timeframe)
        logger.info(
            f"Telegram sent | {sig.symbol} {tf_label} | "
            f"{sig.event} {sig.direction}"
        )
        return True

    except requests.exceptions.RequestException as e:
        logger.error(f"Telegram request failed: {e}")
        return False


def send_signals(signals: List[Signal]):
    """Send Telegram notifications for a list of signals."""
    for sig in signals:
        send_signal(sig)
