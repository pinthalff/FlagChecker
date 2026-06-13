from __future__ import annotations
import asyncio, logging, os, sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import discord
from discord.ext import commands

import config
from storage import BotStorage
from database import setup_databases, DatabaseLayer
from detection import DetectionService
from renderer import CardRenderer
from embeds import build_bot_ready_embed, build_status_control_embed
from cogs import EventsCog, CheckCog, LookupCog
from dashboard import DashboardCog

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("bot")

_STATUS_MAP = {
    "online":    (discord.Status.online,    "Online"),
    "idle":      (discord.Status.idle,      "Idle"),
    "dnd":       (discord.Status.dnd,       "Do Not Disturb"),
    "invisible": (discord.Status.invisible, "Invisible"),
}


class StatusControlView(discord.ui.View):
    def __init__(self) -> None: super().__init__(timeout=None)

    async def _set(self, interaction: discord.Interaction, key: str) -> None:
        if not await interaction.client.is_owner(interaction.user):
            return await interaction.response.send_message("Owner only.", ephemeral=True)
        status, label = _STATUS_MAP[key]
        await interaction.client.change_presence(status=status)
        await interaction.response.edit_message(embed=build_status_control_embed(label))
        if config.LOG_CHANNEL_ID:
            ch = interaction.client.get_channel(int(config.LOG_CHANNEL_ID))
            if ch:
                e = discord.Embed(title="Bot Status Changed")
                e.description = (f"Status changed to **{label}**\n"
                                 f"Changed by: {interaction.user} (`{interaction.user.id}`)")
                e.timestamp = datetime.now(timezone.utc)
                try: await ch.send(embed=e)
                except Exception: pass

    @discord.ui.button(label="Online",    style=discord.ButtonStyle.success,   custom_id="status_online")
    async def btn_online(self, i, _):    await self._set(i, "online")
    @discord.ui.button(label="Idle",      style=discord.ButtonStyle.secondary,  custom_id="status_idle")
    async def btn_idle(self, i, _):      await self._set(i, "idle")
    @discord.ui.button(label="DND",       style=discord.ButtonStyle.danger,     custom_id="status_dnd")
    async def btn_dnd(self, i, _):       await self._set(i, "dnd")
    @discord.ui.button(label="Invisible", style=discord.ButtonStyle.secondary,  custom_id="status_invisible")
    async def btn_invisible(self, i, _): await self._set(i, "invisible")


class DetectorBot(commands.Bot):
    def __init__(self) -> None:
        intents         = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.storage   = BotStorage()
        self.detection = DetectionService(self.storage)
        self.renderer  = CardRenderer()

    async def setup_hook(self) -> None:
        self.add_view(StatusControlView())
        await self.renderer._ensure_started()

        # Connect databases (MySQL + MongoDB)
        try:
            db_status = setup_databases()
            if db_status.get("mysql") and db_status.get("mongodb"):
                db = DatabaseLayer()
                self.storage.set_database(db)
                log.info("Database layer connected (MySQL + MongoDB)")
            else:
                log.warning("Database partially connected: %s", db_status)
        except Exception as exc:
            log.error("Database setup failed: %s", exc)

        for cog in [EventsCog, DashboardCog, CheckCog, LookupCog]:
            await self.add_cog(cog(self))
            log.info("Loaded: %s", cog.__name__)

        async def _mode_check(interaction: discord.Interaction) -> bool:
            if self.storage.has_role("blacklisted", interaction.user.id):
                await interaction.response.send_message("You are blacklisted.", ephemeral=True)
                return False
            return True

        self.tree.interaction_check = _mode_check

        # Always sync globally so commands work in DMs and every server
        try:
            synced = await self.tree.sync()
            log.info("Synced %d commands globally", len(synced))
        except Exception as exc:
            log.error("Global sync failed: %s", exc)

        # Also sync to dev guild if set (instant update for testing)
        if config.DEV_GUILD_ID:
            try:
                guild  = discord.Object(id=int(config.DEV_GUILD_ID))
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info("Synced %d commands to dev guild %s", len(synced), config.DEV_GUILD_ID)
            except Exception as exc:
                log.error("Dev guild sync failed: %s", exc)

    async def on_ready(self) -> None:
        log.info("Ready — %s | MOCK_MODE=%s", self.user, config.MOCK_MODE)
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Activity(type=discord.ActivityType.watching,
                                      name="FlagChecker | /search | /search2"))
        if config.STATUS_CHANNEL_ID:
            ch = self.get_channel(int(config.STATUS_CHANNEL_ID))
            if ch:
                try:
                    await ch.send(embed=build_bot_ready_embed(self))
                    await ch.send(embed=build_status_control_embed("Online"),
                                  view=StatusControlView())
                except discord.HTTPException: pass

    async def close(self) -> None:
        await self.renderer.close()
        await self.detection.close()
        await super().close()

    @commands.command(name="sync", hidden=True)
    @commands.is_owner()
    async def sync_commands(self, ctx, guild_id: str = None) -> None:
        if guild_id:
            guild  = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            await ctx.send(f"Synced {len(synced)} commands to `{guild_id}`.")
        else:
            synced = await self.tree.sync()
            await ctx.send(f"Synced {len(synced)} commands globally.")


async def main() -> None:
    if not config.DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN not set — copy .env.example to .env and fill it in.")
    async with DetectorBot() as bot:
        await bot.start(config.DISCORD_TOKEN)

if __name__ == "__main__":
    try:        asyncio.run(main())
    except KeyboardInterrupt: log.info("Shutting down.")
