# bot.py

# bot.py

from __future__ import annotations

import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv

import config
from FlagCheckerDB import FlagCheckerDB
from detection import DetectionService
from cogs import EventsCog, CheckCog, LookupCog
from cogs_dbmanage import DBManageCog

load_dotenv()
log = logging.getLogger("bot")


def setup_logging():
    logging.basicConfig(
        level   = logging.INFO,
        format  = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers = [logging.StreamHandler(sys.stdout)],
    )


class FlagCheckerBot(commands.Bot):
    def __init__(self):
        intents                 = discord.Intents.default()
        intents.members         = True
        intents.message_content = True
        super().__init__(
            command_prefix = "!",
            intents        = intents,
            help_command   = None,
        )
        self.storage:   FlagCheckerDB   = None
        self.detection: DetectionService = None

    async def setup_hook(self):
        # ── Storage ──
        self.storage   = FlagCheckerDB()
        self.detection = DetectionService(storage=self.storage)

        # ── Cogs ──
        await self.add_cog(EventsCog(self))
        await self.add_cog(CheckCog(self))
        await self.add_cog(LookupCog(self))
        await self.add_cog(DBManageCog(self))

        log.info("[Bot] All cogs loaded")

        # ── Sync slash commands ──
        try:
            synced = await self.tree.sync()
            log.info("[Bot] Synced %d slash command(s)", len(synced))
        except Exception as e:
            log.error("[Bot] Failed to sync commands: %s", e)

    async def on_ready(self):
        log.info("[Bot] Logged in as %s (ID: %s)", self.user, self.user.id)
        log.info("[Bot] Guilds: %d", len(self.guilds))

        # DB status on boot
        for s in self.storage.db_status():
            tag = " ACTIVE" if s["active"] else ""
            tag += " FULL"   if s["full"]   else ""
            log.info(
                "[DB %d] %s — %.1fMB (%.1f%%)%s",
                s["slot"], s["db_name"], s["size_mb"], s["pct"], tag
            )

        await self.change_presence(
            activity = discord.Activity(
                type = discord.ActivityType.watching,
                name = "for exploiters"
            )
        )

    async def on_disconnect(self):
        log.warning("[Bot] Disconnected — will reconnect automatically")

    async def on_resumed(self):
        log.info("[Bot] Resumed session")

    async def close(self):
        log.info("[Bot] Shutting down...")
        if self.detection:
            await self.detection.close()
        if self.storage:
            self.storage.close()
        await super().close()


async def main():
    setup_logging()

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        log.error("[Bot] DISCORD_TOKEN not set")
        sys.exit(1)

    bot = FlagCheckerBot()

    # ── Auto reconnect loop ──
    while True:
        try:
            await bot.start(token)
        except discord.LoginFailure:
            log.error("[Bot] Invalid token — check DISCORD_TOKEN")
            sys.exit(1)
        except Exception as e:
            log.error("[Bot] Crashed: %s — restarting in 30s", e)
            await asyncio.sleep(30)
            bot = FlagCheckerBot()


if __name__ == "__main__":
    asyncio.run(main())
