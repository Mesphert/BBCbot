"""
config.py — All settings for the Bybit signal bot.
Secrets are loaded from Render environment variables — never hardcoded.
"""

import os

# ------------------------------------------------------------------
# Telegram Bot API
# Set on Render: TELEGRAM_TOKEN, TELEGRAM_CHANNEL
# ------------------------------------------------------------------
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")    # from @BotFather
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL")  # e.g. "@yourchannel" or "-1001234567890"

# ------------------------------------------------------------------
# MongoDB Atlas
# Set on Render: MONGO_URI
# Format: mongodb+srv://user:password@cluster.mongodb.net/dbname
# ------------------------------------------------------------------
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB  = "bybit_bot"   # database name inside Atlas

# ------------------------------------------------------------------
# Bybit (public endpoints — no API key needed for kline data)
# BYBIT_API_KEY reserved for future private endpoints (trading bot)
# Set on Render: BYBIT_API_KEY
# ------------------------------------------------------------------
# Supabase Edge Function proxy URL
# Set on Render: SUPABASE_FUNCTION_URL
# Format: https://xxxx.supabase.co/functions/v1/bybit-proxy
SUPABASE_FUNCTION_URL = os.getenv("SUPABASE_FUNCTION_URL")
SUPABASE_ANON_KEY     = os.getenv("SUPABASE_ANON_KEY")

BYBIT_API_KEY    = os.getenv("BYBIT_API_KEY")    # used for private endpoints
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET") # used for HMAC signature

# ------------------------------------------------------------------
# Bybit market data
# ------------------------------------------------------------------
SYMBOL     = "BTCUSDT"
TIMEFRAMES = ["3", "5", "15", "30", "60", "240", "D", "W"]

# Human-readable labels for each Bybit interval string
TF_LABELS = {
    "3":   "3m",
    "5":   "5m",
    "15":  "15m",
    "30":  "30m",
    "60":  "1h",
    "240": "4h",
    "D":   "1D",
    "W":   "1W",
}

# Minutes per timeframe (used by scheduler)
TF_MINUTES = {
    "3":   3,
    "5":   5,
    "15":  15,
    "30":  30,
    "60":  60,
    "240": 240,
    "D":   1440,
    "W":   10080,
}

# Candles to fetch per cycle
CANDLE_LIMIT = 100

# ------------------------------------------------------------------
# Structure detection tuning
# ------------------------------------------------------------------
SWING_LOOKBACK = 5   # bars left of pivot
SWING_RIGHT    = 2   # bars right of pivot

# ------------------------------------------------------------------
# Sessions (America/New_York time)
# ------------------------------------------------------------------
BROKER_TIMEZONE = "Etc/UTC"   # Bybit uses UTC

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
