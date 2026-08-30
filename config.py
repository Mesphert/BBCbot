"""
config.py — All settings for the signal bot.
Secrets are loaded from Render environment variables — never hardcoded.
"""

import os

# ------------------------------------------------------------------
# Telegram Bot API
# Set on Render: TELEGRAM_TOKEN, TELEGRAM_CHANNEL
# ------------------------------------------------------------------
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL")

# ------------------------------------------------------------------
# MongoDB Atlas
# Set on Render: MONGO_URI
# ------------------------------------------------------------------
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB  = "bybit_bot"

# ------------------------------------------------------------------
# Bybit API keys — reserved for trading bot phase (private endpoints)
# Set on Render: BYBIT_API_KEY, BYBIT_API_SECRET
# ------------------------------------------------------------------
BYBIT_API_KEY    = os.getenv("BYBIT_API_KEY")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET")

# ------------------------------------------------------------------
# Market data — Binance Futures (no API key needed for kline data)
# ------------------------------------------------------------------
SYMBOL     = "BTCUSDT"

# Binance interval strings
TIMEFRAMES = ["3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]

# Human-readable labels
TF_LABELS = {
    "3m":  "3m",
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",
    "1h":  "1h",
    "4h":  "4h",
    "1d":  "1D",
    "1w":  "1W",
}

# Minutes per timeframe (used by scheduler)
TF_MINUTES = {
    "3m":  3,
    "5m":  5,
    "15m": 15,
    "30m": 30,
    "1h":  60,
    "4h":  240,
    "1d":  1440,
    "1w":  10080,
}

# Candles to fetch on first run (backfill)
CANDLE_LIMIT = 100

# ------------------------------------------------------------------
# Structure detection tuning
# ------------------------------------------------------------------
SWING_LOOKBACK = 5
SWING_RIGHT    = 2

# ------------------------------------------------------------------
# Sessions (America/New_York time)
# ------------------------------------------------------------------
BROKER_TIMEZONE = "Etc/UTC"   # Binance uses UTC

SESSIONS = {
    "Asia": {
        "start": "20:00",
        "end":   "00:00",
    },
    "London": {
        "start": "03:00",
        "end":   "12:00",
    },
    "New York": {
        "start": "08:00",
        "end":   "17:00",
    },
}
