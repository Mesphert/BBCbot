"""
main.py — Entry point for the Bybit signal bot.

Two threads run concurrently:
  Thread 1: FastAPI web app
    - Keeps an HTTP port open (required by Render)
    - Responds to cron-job.org health pings every 10 minutes
    - Exposes /signals endpoint for quick status checks

  Thread 2: Bot loop
    - Wakes every 3 minutes (3m candle heartbeat)
    - Checks which TFs are closing at that moment
    - Fetches new candles from Bybit for closing TFs only
    - Runs BOS/CHOCH/CRT detection (state loaded from Neon)
    - Saves signals to Neon
    - Sends Telegram notifications via Graspil

Run locally:
    uvicorn main:app --host 0.0.0.0 --port 8000

On Render:
    Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
"""

import logging
import threading
import time
from datetime import timezone
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

import config
import mongo as neon
import binance as bybit
import detector
import notifier
import scheduler
from session import SessionDetector

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

# ------------------------------------------------------------------
# Bot loop — Thread 2
# ------------------------------------------------------------------

session_det = SessionDetector()

# Shared status for the /status endpoint (in-memory only — non-critical)
_bot_status = {
    "last_cycle":    None,
    "cycles_run":    0,
    "signals_fired": 0,
}


def bot_loop():
    """
    Main bot loop. Runs in a background thread.
    Wakes every 3 minutes, processes closing TFs, detects patterns.
    All state read from / written to MongoDB — no in-memory state.
    """
    logger.info("Bot loop started.")

    # Give FastAPI a moment to start before the first cycle
    time.sleep(3)
    logger.info("Bot loop ready — entering main cycle.")



    while True:
        try:
            # Sleep until next 3m candle close
            woke_at = scheduler.sleep_until_next_close()

            # Which TFs are closing right now?
            closing_tfs = scheduler.which_tfs_closing(woke_at)

            if not closing_tfs:
                logger.debug("No TFs closing this cycle — skipping.")
                continue

            logger.info(f"Cycle | closing TFs: {closing_tfs}")

            # Detect active session at this timestamp
            active_sessions = session_det.active_sessions(woke_at)
            session_label   = ", ".join(active_sessions) if active_sessions else "Off-session"

            cycle_signals = []

            for interval in closing_tfs:
                tf_label = config.TF_LABELS.get(interval, interval)

                # Load last processed candle from Neon
                last_candle = neon.get_cursor(config.SYMBOL, interval)

                # Fetch only new closed candles from Bybit
                df = bybit.get_new_candles(
                    config.SYMBOL, interval, last_candle
                )

                if df is None or df.empty:
                    logger.debug(f"No new candles for {interval}")
                    continue

                # Run detection — reads/writes swing + structure state to Neon
                signals = detector.process_candles(
                    df       = df,
                    symbol   = config.SYMBOL,
                    timeframe= interval,
                    session  = session_label,
                )

                if signals:
                    logger.info(
                        f"{len(signals)} signal(s) on {tf_label}: "
                        f"{[(s.event, s.direction) for s in signals]}"
                    )
                    cycle_signals.extend(signals)

                # Update candle cursor in Neon
                last_ts = df.index[-1].to_pydatetime()
                neon.set_cursor(config.SYMBOL, interval, last_ts)

            # Send Telegram notifications for all signals this cycle
            if cycle_signals:
                notifier.send_signals(cycle_signals)
                _bot_status["signals_fired"] += len(cycle_signals)

            _bot_status["last_cycle"]  = woke_at.isoformat()
            _bot_status["cycles_run"] += 1

        except Exception as e:
            logger.error(f"Bot loop error: {e}", exc_info=True)
            logger.error("Bot loop sleeping 60s after error before retrying...")
            time.sleep(60)
            logger.info("Bot loop resuming after error sleep.")


# ------------------------------------------------------------------
# FastAPI app — Thread 1
# ------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init Neon schema and launch bot thread."""
    logger.info("Starting up...")

    # Init Neon tables (safe to call every startup)
    neon.init_schema()

    # Launch bot in background thread
    bot_thread = threading.Thread(target=bot_loop, daemon=True, name="bot")
    bot_thread.start()
    logger.info("Bot thread started.")

    yield

    logger.info("Shutting down.")


app = FastAPI(
    title="Bybit Signal Bot",
    lifespan=lifespan,
)


@app.get("/")
@app.head("/")
def health():
    """
    Health check endpoint.
    Handles both GET and HEAD requests — Render uses HEAD for health checks.
    Cron-job.org pings this every 10 minutes to keep Render alive.
    """
    return {"status": "ok", "symbol": config.SYMBOL}


@app.get("/status")
def status():
    """Bot status — last cycle time, signals fired etc."""
    return JSONResponse({
        "symbol":        config.SYMBOL,
        "timeframes":    config.TIMEFRAMES,
        "last_cycle":    _bot_status["last_cycle"],
        "cycles_run":    _bot_status["cycles_run"],
        "signals_fired": _bot_status["signals_fired"],
    })


@app.get("/signals")
def recent_signals(timeframe: str = None, limit: int = 20):
    """Return recent signals from Neon for quick inspection."""
    try:
        signals = neon.get_recent_signals(
            config.SYMBOL, timeframe, limit
        )
        return signals
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ------------------------------------------------------------------
# Local run
# ------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
