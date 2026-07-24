# runtime.py — FlagChecker bot
# Keeps the flagchecker alive on Railway
# Auto restarts, health checks, crash recovery

# runtime.py — FlagChecker bot

from __future__ import annotations

import asyncio
import os
import sys
import gc
import random
import time
import traceback
from datetime import datetime, timezone
import aiohttp


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip().strip('"').strip("'")

AUDIT_WEBHOOK = _env("AUDIT_WEBHOOK")
BOT_NAME      = "FlagChecker"

RESTART_INTERVAL_MIN = int(_env("RESTART_INTERVAL_MIN", "12"))
RESTART_INTERVAL_MAX = int(_env("RESTART_INTERVAL_MAX", "24"))
RECONNECT_DELAY_MIN  = int(_env("RECONNECT_DELAY_MIN",  "15"))
RECONNECT_DELAY_MAX  = int(_env("RECONNECT_DELAY_MAX",  "60"))

MAX_FAST_CRASHES = 5

# ─────────────────────────────────────────────
# Runtime state
# ─────────────────────────────────────────────

_start_time    = time.monotonic()
_restart_count = 0
_crash_count   = 0
_last_crash    = 0.0


def _log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[Runtime] [{ts}] {msg}")


def _uptime() -> str:
    elapsed = int(time.monotonic() - _start_time)
    h = elapsed // 3600
    m = (elapsed % 3600) // 60
    s = elapsed % 60
    return f"{h:02d}h {m:02d}m {s:02d}s"


# ─────────────────────────────────────────────
# Webhook
# ─────────────────────────────────────────────

async def _post_webhook(payload: dict, _retry: int = 0):
    if not AUDIT_WEBHOOK or _retry > 3:
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(AUDIT_WEBHOOK, json=payload) as r:
                if r.status == 429:
                    data  = await r.json()
                    retry = float(data.get("retry_after", 2))
                    await asyncio.sleep(retry)
                    await _post_webhook(payload, _retry + 1)
    except Exception as e:
        _log(f"Webhook error: {e}")


async def _send_health_webhook(uptime: str, restart_count: int, crash_count: int):
    await _post_webhook({
        "embeds": [{
            "title": f"[{BOT_NAME}] Health Check",
            "color": 0x57F287,
            "fields": [
                {"name": "Uptime",   "value": f"`{uptime}`",        "inline": True},
                {"name": "Restarts", "value": f"`{restart_count}`", "inline": True},
                {"name": "Crashes",  "value": f"`{crash_count}`",   "inline": True},
            ],
            "footer":    {"text": f"Runtime Monitor • {BOT_NAME}"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }]
    })


async def _send_status_webhook(status: str, color: int, extra: str = ""):
    fields = [
        {"name": "Status",   "value": f"`{status}`",         "inline": True},
        {"name": "Uptime",   "value": f"`{_uptime()}`",      "inline": True},
        {"name": "Restarts", "value": f"`{_restart_count}`", "inline": True},
    ]
    if extra:
        fields.append({"name": "Info", "value": extra, "inline": False})

    await _post_webhook({
        "embeds": [{
            "title":     f"[{BOT_NAME}] Runtime Status",
            "color":     color,
            "fields":    fields,
            "footer":    {"text": f"Runtime Monitor • {BOT_NAME}"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }]
    })


# ─────────────────────────────────────────────
# Health loop — every hour
# ─────────────────────────────────────────────

async def _health_loop():
    while True:
        await asyncio.sleep(3600)
        uptime = _uptime()
        _log(f"Health — uptime: {uptime} | restarts: {_restart_count} | crashes: {_crash_count}")
        await _send_health_webhook(uptime, _restart_count, _crash_count)


# ─────────────────────────────────────────────
# Planned restart loop
# ─────────────────────────────────────────────

async def _restart_loop(bot):
    while True:
        hours = random.uniform(RESTART_INTERVAL_MIN, RESTART_INTERVAL_MAX)
        secs  = int(hours * 3600)
        _log(f"Next planned restart in {hours:.1f}h")
        await asyncio.sleep(secs)

        _log("Planned restart — closing bot...")
        await _send_status_webhook(
            status = "Planned Restart",
            color  = 0xFEE75C,
            extra  = f"Restarting after {hours:.1f}h cycle"
        )
        try:
            await bot.close()
        except Exception as e:
            _log(f"Close error: {e}")


# ─────────────────────────────────────────────
# Main runtime loop
# ─────────────────────────────────────────────

async def run():
    global _restart_count, _crash_count, _last_crash

    _log(f"{BOT_NAME} runtime starting...")
    _log(f"Restart interval: {RESTART_INTERVAL_MIN}-{RESTART_INTERVAL_MAX}h")
    _log(f"Reconnect delay:  {RECONNECT_DELAY_MIN}-{RECONNECT_DELAY_MAX}s")

    asyncio.ensure_future(_health_loop())

    await _send_status_webhook(
        status = "Online",
        color  = 0x57F287,
        extra  = f"Runtime started — restart interval: {RESTART_INTERVAL_MIN}-{RESTART_INTERVAL_MAX}h"
    )

    while True:
        bot          = None
        restart_task = None

        try:
            if "bot" in sys.modules:
                del sys.modules["bot"]

            from bot import FlagCheckerBot
            import config
            DISCORD_TOKEN = config.DISCORD_TOKEN

            _log(f"Starting {BOT_NAME} (restart #{_restart_count})")

            await _send_status_webhook(
                status = "Connecting",
                color  = 0x5865F2,
                extra  = f"Starting bot instance #{_restart_count}"
            )

            bot          = FlagCheckerBot()
            restart_task = asyncio.ensure_future(_restart_loop(bot))

            await bot.start(DISCORD_TOKEN)

            _log("Bot disconnected cleanly")

        except SystemExit as e:
            _log(f"SystemExit: {e.code} — stopping")
            await _send_status_webhook(
                status = "Stopped",
                color  = 0xED4245,
                extra  = f"SystemExit: {e.code}"
            )
            sys.exit(e.code)

        except Exception as e:
            _crash_count += 1
            now = time.monotonic()

            _log(f"Crash: {e}")
            traceback.print_exc()

            await _send_status_webhook(
                status = "Crashed",
                color  = 0xED4245,
                extra  = f"Error: {str(e)[:200]}\nCrash #{_crash_count}"
            )

            if now - _last_crash < 60:
                if _crash_count >= MAX_FAST_CRASHES:
                    backoff = random.randint(300, 600)
                    _log(f"Crash loop — backing off {backoff}s")
                    await _send_status_webhook(
                        status = "Crash Loop",
                        color  = 0xED4245,
                        extra  = f"Backing off {backoff}s"
                    )
                    await asyncio.sleep(backoff)
                    _crash_count = 0

            _last_crash = now

        finally:
            if restart_task and not restart_task.done():
                restart_task.cancel()

            if bot:
                try:
                    if not bot.is_closed():
                        await bot.close()
                except Exception:
                    pass

            collected = gc.collect()
            _log(f"Memory cleaned — {collected} objects collected")

        _restart_count += 1
        delay = random.randint(RECONNECT_DELAY_MIN, RECONNECT_DELAY_MAX)
        _log(f"Reconnecting in {delay}s (restart #{_restart_count})")

        await _send_status_webhook(
            status = "Reconnecting",
            color  = 0xFEE75C,
            extra  = f"Waiting {delay}s (restart #{_restart_count})"
        )

        await asyncio.sleep(delay)


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(run())
