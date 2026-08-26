"""
mongo.py — All MongoDB Atlas read/write operations.

Replaces neon.py. Every piece of state that must survive a Render
restart lives here. No state is ever stored in Python variables.

Collections:
    signals        — every detected BOS/CHOCH/CRT event (full history)
    swing_state    — fresh/used swing points per symbol/TF
    candle_cursor  — last processed candle timestamp per symbol/TF
    structure_state — last confirmed structure direction/type per symbol/TF
"""

import logging
from datetime import datetime
from typing import Optional

from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

import config

logger = logging.getLogger(__name__)

_client = None
_db     = None


# ------------------------------------------------------------------
# Connection
# ------------------------------------------------------------------

def get_db():
    """Return the MongoDB database instance (lazy singleton)."""
    global _client, _db
    if _db is None:
        _client = MongoClient(config.MONGO_URI)
        _db     = _client[config.MONGO_DB]
    return _db


# ------------------------------------------------------------------
# Schema bootstrap — run once on startup
# ------------------------------------------------------------------

def init_schema():
    """
    Create collections and indexes if they don't exist.
    Safe to call on every startup.
    """
    db = get_db()

    # signals — unique on (symbol, timeframe, event, direction, candle_time)
    db.signals.create_index(
        [("symbol", ASCENDING), ("timeframe", ASCENDING),
         ("event", ASCENDING), ("direction", ASCENDING),
         ("candle_time", ASCENDING)],
        unique=True, name="idx_signal_unique"
    )
    db.signals.create_index(
        [("symbol", ASCENDING), ("timeframe", ASCENDING),
         ("candle_time", DESCENDING)],
        name="idx_signal_query"
    )

    # swing_state — unique on (symbol, timeframe, kind, candle_time)
    db.swing_state.create_index(
        [("symbol", ASCENDING), ("timeframe", ASCENDING),
         ("kind", ASCENDING), ("candle_time", ASCENDING)],
        unique=True, name="idx_swing_unique"
    )
    db.swing_state.create_index(
        [("symbol", ASCENDING), ("timeframe", ASCENDING),
         ("fresh", ASCENDING)],
        name="idx_swing_fresh"
    )

    # candle_cursor — unique on (symbol, timeframe)
    db.candle_cursor.create_index(
        [("symbol", ASCENDING), ("timeframe", ASCENDING)],
        unique=True, name="idx_cursor_unique"
    )

    # structure_state — unique on (symbol, timeframe)
    db.structure_state.create_index(
        [("symbol", ASCENDING), ("timeframe", ASCENDING)],
        unique=True, name="idx_struct_unique"
    )

    logger.info("MongoDB schema ready.")


# ------------------------------------------------------------------
# Candle cursor
# ------------------------------------------------------------------

def get_cursor(symbol: str, timeframe: str) -> Optional[datetime]:
    """Return the last processed candle close time, or None on first run."""
    doc = get_db().candle_cursor.find_one(
        {"symbol": symbol, "timeframe": timeframe}
    )
    return doc["last_candle"] if doc else None


def set_cursor(symbol: str, timeframe: str, last_candle: datetime):
    """Upsert the last processed candle timestamp."""
    get_db().candle_cursor.update_one(
        {"symbol": symbol, "timeframe": timeframe},
        {"$set": {
            "last_candle": last_candle,
            "updated_at":  datetime.utcnow()
        }},
        upsert=True
    )


# ------------------------------------------------------------------
# Structure state
# ------------------------------------------------------------------

def get_structure_state(symbol: str, timeframe: str) -> dict:
    """Return last confirmed structure state. Returns None values on first run."""
    doc = get_db().structure_state.find_one(
        {"symbol": symbol, "timeframe": timeframe}
    )
    if doc:
        return {"direction": doc.get("last_direction"),
                "type":      doc.get("last_type")}
    return {"direction": None, "type": None}


def set_structure_state(symbol: str, timeframe: str,
                        direction: str, kind: str):
    """Upsert the last confirmed structure direction and type."""
    get_db().structure_state.update_one(
        {"symbol": symbol, "timeframe": timeframe},
        {"$set": {
            "last_direction": direction,
            "last_type":      kind,
            "updated_at":     datetime.utcnow()
        }},
        upsert=True
    )


# ------------------------------------------------------------------
# Swing state
# ------------------------------------------------------------------

def get_fresh_swings(symbol: str, timeframe: str) -> dict:
    """Return all fresh swing points for this symbol/TF."""
    docs = list(get_db().swing_state.find(
        {"symbol": symbol, "timeframe": timeframe, "fresh": True},
        sort=[("candle_time", ASCENDING)]
    ))
    highs = [{"price": d["price"], "candle_time": d["candle_time"]}
             for d in docs if d["kind"] == "high"]
    lows  = [{"price": d["price"], "candle_time": d["candle_time"]}
             for d in docs if d["kind"] == "low"]
    return {"highs": highs, "lows": lows}


def upsert_swing(symbol: str, timeframe: str, kind: str,
                 price: float, candle_time: datetime, fresh: bool = True):
    """Insert or update a swing point."""
    try:
        get_db().swing_state.update_one(
            {"symbol": symbol, "timeframe": timeframe,
             "kind": kind, "candle_time": candle_time},
            {"$set": {
                "price":      price,
                "fresh":      fresh,
                "updated_at": datetime.utcnow()
            }},
            upsert=True
        )
    except DuplicateKeyError:
        pass   # already exists — safe to ignore


def retire_swing(symbol: str, timeframe: str,
                 kind: str, candle_time: datetime):
    """Mark a swing point as used (fresh=False)."""
    get_db().swing_state.update_one(
        {"symbol": symbol, "timeframe": timeframe,
         "kind": kind, "candle_time": candle_time},
        {"$set": {"fresh": False, "updated_at": datetime.utcnow()}}
    )


# ------------------------------------------------------------------
# Signals
# ------------------------------------------------------------------

def save_signal(symbol: str, timeframe: str, event: str,
                direction: str, price: float, candle_time: datetime,
                session: str = None, description: str = None):
    """
    Insert a detected signal. Duplicates silently ignored
    via the unique index on (symbol, timeframe, event, direction, candle_time).
    """
    try:
        get_db().signals.insert_one({
            "symbol":      symbol,
            "timeframe":   timeframe,
            "event":       event,
            "direction":   direction,
            "price":       price,
            "candle_time": candle_time,
            "session":     session,
            "description": description,
            "logged_at":   datetime.utcnow(),
        })
        logger.info(
            f"SIGNAL SAVED | {symbol} {timeframe} | "
            f"{event} {direction} | price={price} | {candle_time}"
        )
    except DuplicateKeyError:
        logger.debug(f"Duplicate signal ignored: {symbol} {timeframe} {event} {candle_time}")


def get_recent_signals(symbol: str, timeframe: str = None,
                       limit: int = 50) -> list:
    """Fetch recent signals, optionally filtered by timeframe."""
    query = {"symbol": symbol}
    if timeframe:
        query["timeframe"] = timeframe

    docs = list(get_db().signals.find(
        query,
        sort=[("candle_time", DESCENDING)],
        limit=limit
    ))

    # Remove MongoDB internal _id before returning
    for d in docs:
        d.pop("_id", None)
        if isinstance(d.get("candle_time"), datetime):
            d["candle_time"] = d["candle_time"].isoformat()
        if isinstance(d.get("logged_at"), datetime):
            d["logged_at"] = d["logged_at"].isoformat()
    return docs
