from __future__ import annotations
import json
import logging
import math
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config
from models import AggregateResult
from detection import correlate_condo_servers, correlate_exploit_servers
from embeds import (
    build_command_used_embed, build_overview_embed,
    build_guild_join_embed, build_guild_remove_embed,
    build_dm_embed, build_user_install_embed, build_command_error_embed,
)
from v2 import (
    send_v2, edit_v2,
    build_check_overview, build_check_condos, build_check_exploits,
    build_check_accounts, build_check_profile, build_check_details,
    build_lookup_main, build_lookup_exploit, build_lookup_profile, build_lookup_accounts,
    PAGE_SIZE_CONDOS, PAGE_SIZE_EXPLOITS,
)

log = logging.getLogger("bot.cogs")


async def _is_admin(bot, user) -> bool:
    if await bot.is_owner(user): return True
    return bot.storage.has_role("developers", user.id)


def _auto_add_db(bot, user_id: str, user, agg: AggregateResult) -> None:
    condos   = correlate_condo_servers(agg)
    exploits = correlate_exploit_servers(agg)
    if not (condos or exploits): return
    servers = [{"name": s["name"], "sources": s.get("sources", [])}
               for s in (condos + exploits)[:20]]
    bot.storage.add_flagged_user(
        user_id, str(user) if user else f"User {user_id}",
        agg.sources_flagged, servers,
    )


async def send_command_log(bot, interaction, command_name, options, agg, target_label, target_id):
    if hasattr(bot, "storage"):
        bot.storage.add_command_log({
            "command": command_name, "user_id": str(interaction.user.id),
            "username": str(interaction.user), "target_id": str(target_id),
            "target_label": target_label,
            "guild": interaction.guild.name if interaction.guild else "DM",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        for err in (agg.errors if agg else []):
            bot.storage.add_api_error({
                "error": err, "command": command_name,
                "source": err.split(":")[0] if ":" in err else "Unknown",
                "user_id": str(interaction.user.id),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    if not config.LOG_CHANNEL_ID: return
    ch = bot.get_channel(int(config.LOG_CHANNEL_ID))
    if not ch: return
    try:
        embeds = [
            build_command_used_embed(interaction, command_name, options),
            build_overview_embed(interaction, agg, target_label, target_id),
        ]
        if agg and agg.errors:
            from embeds import build_api_error_log_embed
            embeds.append(build_api_error_log_embed(command_name, str(interaction.user), agg.errors))
        await ch.send(embeds=embeds)
    except discord.HTTPException: pass


async def _fetch_user(bot, user_id: str):
    try:    return await bot.fetch_user(int(user_id))
    except (ValueError, discord.NotFound, discord.HTTPException): return None


# ─────────────────────────────────────────────
# Role formatter — handles both dict and plain string
# ─────────────────────────────────────────────

def _fmt_role(r) -> str:
    if isinstance(r, dict):
        name = r.get("name", f"Unknown ({r.get('id', '?')})")
        rid  = r.get("id", "?")
        return f"`{name}` (`{rid}`)"
    return f"`{r}`"


# ─────────────────────────────────────────────
# Selfbot embed builders — V2 compatible
# ─────────────────────────────────────────────

def _build_selfbot_roles_embed(gd: dict) -> discord.Embed:
    guild_name    = gd.get("guild_name", "Unknown")
    roles         = gd.get("roles", [])
    still_present = gd.get("still_in_server") is True
    join_date     = gd.get("join_date", "unknown")
    username      = gd.get("username", "Unknown")
    guild_id      = gd.get("guild_id", "?")

    embed = discord.Embed(
        title=f"Roles — {guild_name}",
        color=0x57F287 if still_present else 0xFFA500,
    )
    embed.add_field(name="User",     value=f"`{username}`",                            inline=True)
    embed.add_field(name="Status",   value="Current" if still_present else "Previous", inline=True)
    embed.add_field(name="Joined",   value=f"`{join_date}`",                           inline=True)
    embed.add_field(name="Guild ID", value=f"`{guild_id}`",                            inline=False)

    if roles:
        lines      = [_fmt_role(r) for r in roles]
        chunk_size = 20
        for i in range(0, len(lines), chunk_size):
            chunk = lines[i:i + chunk_size]
            embed.add_field(
                name=f"Roles ({len(roles)})" if i == 0 else "Roles (cont.)",
                value="\n".join(chunk),
                inline=False
            )
    else:
        embed.add_field(name="Roles", value="*No roles recorded*", inline=False)

    return embed


def _build_selfbot_messages_embed(gd: dict) -> discord.Embed:
    guild_name    = gd.get("guild_name", "Unknown")
    recent_msgs   = gd.get("recent_messages", [])
    msg_count     = gd.get("message_count", 0)
    still_present = gd.get("still_in_server") is True
    username      = gd.get("username", "Unknown")
    guild_id      = gd.get("guild_id", "?")

    embed = discord.Embed(
        title=f"Messages — {guild_name}",
        color=0x57F287 if still_present else 0xFFA500,
    )
    embed.add_field(name="User",     value=f"`{username}`",                            inline=True)
    embed.add_field(name="Total",    value=f"`{msg_count}`",                           inline=True)
    embed.add_field(name="Status",   value="Current" if still_present else "Previous", inline=True)
    embed.add_field(name="Guild ID", value=f"`{guild_id}`",                            inline=False)

    if recent_msgs:
        lines = []
        for m in recent_msgs[:10]:
            content = (m.get("content") or "[no text]")[:80]
            channel = m.get("channel", "unknown")
            sent_at = (m.get("sent_at") or "?")[:10]
            lines.append(f"`#{channel}` [{sent_at}]: {content}")
        embed.add_field(name="Recent Messages", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Recent Messages", value="*No messages recorded*", inline=False)

    return embed


def _build_scraped_section_embed(agg: AggregateResult) -> discord.Embed:
    guilds = getattr(agg, "selfbot_guilds", []) or []
    active = getattr(agg, "selfbot_active_guilds", []) or []
    prev   = getattr(agg, "selfbot_prev_guilds", []) or []

    embed = discord.Embed(title="Scraped Server Presence", color=0x5865F2)
    embed.add_field(
        name="Summary",
        value=(
            f"Current: **{len(active)}** server(s)\n"
            f"Previous: **{len(prev)}** server(s)\n"
            f"Total: **{len(guilds)}**"
        ),
        inline=False,
    )

    if active:
        lines = []
        for g in active[:10]:
            name  = g.get("guild_name", "Unknown")
            gid   = g.get("guild_id", "?")
            roles = g.get("roles", [])
            # Show first 2 role names if available
            rnames = []
            for r in roles[:2]:
                rnames.append(r.get("name", str(r)) if isinstance(r, dict) else str(r))
            rstr = f" — {', '.join(rnames)}" if rnames else ""
            lines.append(f"**{name}** (`{gid}`){rstr}")
        embed.add_field(name=f"Current Servers ({len(active)})", value="\n".join(lines), inline=False)

    if prev:
        lines = []
        for g in prev[:10]:
            name = g.get("guild_name", "Unknown")
            gid  = g.get("guild_id", "?")
            lines.append(f"**{name}** (`{gid}`)")
        embed.add_field(name=f"Previous Servers ({len(prev)})", value="\n".join(lines), inline=False)

    if not guilds:
        embed.description = "*Not found in any scraped server.*"

    embed.set_footer(text="Use Roles / Messages buttons for per-server details.")
    return embed


# ─────────────────────────────────────────────
# Selfbot dropdowns — Roles
# ─────────────────────────────────────────────

class _SelfbotRolesSelect(discord.ui.Select):
    def __init__(self, guilds: list, invoker_id: int, row: int = 2):
        self.invoker_id  = invoker_id
        self._guilds_map = {str(g.get("guild_id", i)): g for i, g in enumerate(guilds)}
        options = []
        for g in guilds[:25]:
            label         = g.get("guild_name", "Unknown")[:100]
            value         = str(g.get("guild_id", "0"))[:100]
            still_present = g.get("still_in_server") is True
            desc          = "Current" if still_present else "Previous"
            options.append(discord.SelectOption(label=label, value=value, description=desc))
        if not options:
            options.append(discord.SelectOption(label="No servers found", value="none"))
        super().__init__(placeholder="Roles — pick a server", options=options, row=row)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message("Not your lookup.", ephemeral=True)
        gd = self._guilds_map.get(self.values[0])
        if not gd:
            return await interaction.response.send_message("No data.", ephemeral=True)
        await interaction.response.send_message(
            embed=_build_selfbot_roles_embed(gd), ephemeral=True
        )


# ─────────────────────────────────────────────
# Selfbot dropdowns — Messages
# ─────────────────────────────────────────────

class _SelfbotMessagesSelect(discord.ui.Select):
    def __init__(self, guilds: list, invoker_id: int, row: int = 3):
        self.invoker_id  = invoker_id
        self._guilds_map = {str(g.get("guild_id", i)): g for i, g in enumerate(guilds)}
        options = []
        for g in guilds[:25]:
            label     = g.get("guild_name", "Unknown")[:100]
            value     = str(g.get("guild_id", "0"))[:100]
            msg_count = g.get("message_count", 0)
            still     = g.get("still_in_server") is True
            desc      = f"{'Current' if still else 'Previous'} — {msg_count} msg(s)"
            options.append(discord.SelectOption(label=label, value=value, description=desc[:100]))
        if not options:
            options.append(discord.SelectOption(label="No servers found", value="none"))
        super().__init__(placeholder="Messages — pick a server", options=options, row=row)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message("Not your lookup.", ephemeral=True)
        gd = self._guilds_map.get(self.values[0])
        if not gd:
            return await interaction.response.send_message("No data.", ephemeral=True)
        await interaction.response.send_message(
            embed=_build_selfbot_messages_embed(gd), ephemeral=True
        )


# ── Events ─────────────────────────────────────────────────────────────────────

class EventsCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        bot.tree.on_error = self._on_app_command_error

    async def _log(self, embed):
        if not config.LOG_CHANNEL_ID: return
        ch = self.bot.get_channel(int(config.LOG_CHANNEL_ID))
        if not ch: return
        try:    await ch.send(embed=embed)
        except discord.HTTPException: pass

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self._log(build_guild_join_embed(guild))

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        await self._log(build_guild_remove_embed(guild))

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        if not isinstance(message.channel, discord.DMChannel): return
        await self._log(build_dm_embed(message))

    @commands.Cog.listener()
    async def on_socket_raw_receive(self, msg):
        try:
            if isinstance(msg, bytes): msg = msg.decode("utf-8")
            data = json.loads(msg)
            if data.get("t") != "APPLICATION_AUTHORIZED": return
            d = data.get("d") or {}; user = d.get("user") or {}; uid = user.get("id")
            await self._log(build_user_install_embed(d))
            if uid and hasattr(self.bot, "storage"):
                try:
                    user_id = int(uid)
                    mutual  = [{"id": str(g.id), "name": g.name}
                                for g in self.bot.guilds if g.get_member(user_id)]
                    self.bot.storage.store_user_servers(user_id, mutual)
                except Exception: pass
        except Exception: pass

    async def _on_app_command_error(self, interaction, error):
        log.error("Command error: %s", error)
        await self._log(build_command_error_embed(interaction, error))
        msg = "Something went wrong. The error has been logged."
        try:
            if interaction.response.is_done(): await interaction.followup.send(msg, ephemeral=True)
            else:                              await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException: pass


# ── Nav buttons ────────────────────────────────────────────────────────────────

class _NavBtn(discord.ui.Button):
    def __init__(self, label, invoker_id, view_ref, delta, row):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=row, disabled=True)
        self.invoker_id = invoker_id; self.view_ref = view_ref; self.delta = delta

    async def callback(self, interaction):
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message("Not your lookup.", ephemeral=True)
        self.view_ref.page += self.delta
        self.view_ref.refresh_nav()
        await self.view_ref.do_edit(interaction)


class _PageLabel(discord.ui.Button):
    def __init__(self, row):
        super().__init__(label="1/1", style=discord.ButtonStyle.secondary, disabled=True, row=row)

    async def callback(self, interaction): pass


# ═══════════════ /search ═══════════════

class CheckCog(commands.Cog):
    def __init__(self, bot) -> None: self.bot = bot

    @app_commands.command(name="search",
        description="Checks if a user is flagged. (Dropdown)")
    @app_commands.describe(
        user_id="Discord user ID (roblox=False) or Roblox user ID (roblox=True).",
        roblox="True = Roblox lookup (Rotector + Moco-co). False = all Discord APIs.",
        extra="Show which API detected each server.",
        private="Send privately. Default True.",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def search(self, interaction, user_id: str, roblox: bool = False,
                     extra: bool = False, private: bool = True):
        await interaction.response.defer(ephemeral=private, thinking=True)
        disabled = self.bot.storage.get_disabled_apis()
        agg = await self.bot.detection.lookup(
            user_id=user_id, roblox_only=roblox, disabled_apis=disabled
        )

        if agg.is_empty() and agg.errors and not config.MOCK_MODE:
            warn = discord.Embed(title="Lookup Incomplete")
            warn.description = "All APIs failed.\n\n" + "\n".join(f"• {e}" for e in agg.errors[:5])
            return await interaction.followup.send(embed=warn, ephemeral=True)

        user = await _fetch_user(self.bot, user_id)
        _auto_add_db(self.bot, user_id, user, agg)

        view = _CheckView(user, agg, extra, roblox, interaction.user.id)
        await send_v2(interaction, view.build(), view=view, ephemeral=private)
        await send_command_log(self.bot, interaction, "search",
            {"user_id": user_id, "roblox": roblox, "extra": extra},
            agg, str(user) if user else f"User {user_id}", user_id)


class _CheckView(discord.ui.View):
    def __init__(self, user, agg, extra, roblox, invoker_id):
        super().__init__(timeout=300)
        self.user, self.agg, self.extra = user, agg, extra
        self.roblox     = roblox
        self.invoker_id = invoker_id
        self.section    = "overview"
        self.page       = 0

        # Row 0 — section select
        self.add_item(_CheckSelect(self))

        # Row 1 — nav
        self._prev = _NavBtn("◀", invoker_id, self, -1, row=1)
        self._lbl  = _PageLabel(row=1)
        self._next = _NavBtn("▶", invoker_id, self, +1, row=1)
        self.add_item(self._prev); self.add_item(self._lbl); self.add_item(self._next)

        # Rows 2 & 3 — selfbot dropdowns (Discord mode only, data must exist)
        selfbot_guilds = getattr(agg, "selfbot_guilds", []) or []
        if selfbot_guilds and not roblox:
            self.add_item(_SelfbotRolesSelect(selfbot_guilds,    invoker_id, row=2))
            self.add_item(_SelfbotMessagesSelect(selfbot_guilds, invoker_id, row=3))

        self.refresh_nav()

    def _max_pages(self) -> int:
        if self.section == "condos":
            return max(1, math.ceil(len(correlate_condo_servers(self.agg)) / PAGE_SIZE_CONDOS))
        if self.section == "exploits":
            return max(1, math.ceil(len(correlate_exploit_servers(self.agg)) / PAGE_SIZE_EXPLOITS))
        return 1

    def refresh_nav(self):
        mp = self._max_pages()
        self._prev.disabled = self.page <= 0
        self._next.disabled = self.page >= mp - 1
        self._lbl.label     = f"{self.page+1}/{mp}"

    def build(self) -> dict:
        s = self.section
        if s == "overview":  return build_check_overview(self.user, self.agg, self.extra)
        if s == "condos":    return build_check_condos(self.agg, self.extra, self.page)
        if s == "exploits":  return build_check_exploits(self.agg, self.extra, self.page)
        if s == "accounts":  return build_check_accounts(self.agg)
        if s == "profile":   return build_check_profile(self.agg)
        if s == "details":   return build_check_details(self.agg)
        if s == "scraped":   return {"embeds": [_build_scraped_section_embed(self.agg)]}
        return build_check_overview(self.user, self.agg, self.extra)

    async def do_edit(self, interaction):
        await edit_v2(interaction, self.build(), view=self)


class _CheckSelect(discord.ui.Select):
    def __init__(self, view_ref):
        roblox      = getattr(view_ref, "roblox", False)
        has_selfbot = bool(getattr(view_ref.agg, "selfbot_guilds", None))

        if roblox:
            options = [
                discord.SelectOption(label="Overview",  value="overview"),
                discord.SelectOption(label="Accounts",  value="accounts"),
                discord.SelectOption(label="Details",   value="details"),
                discord.SelectOption(label="Profile",   value="profile"),
            ]
        else:
            options = [
                discord.SelectOption(label="Overview",  value="overview"),
                discord.SelectOption(label="Condos",    value="condos"),
                discord.SelectOption(label="Exploits",  value="exploits"),
                discord.SelectOption(label="Accounts",  value="accounts"),
                discord.SelectOption(label="Profile",   value="profile"),
                discord.SelectOption(label="Details",   value="details"),
            ]
            if has_selfbot:
                active = len(getattr(view_ref.agg, "selfbot_active_guilds", []) or [])
                prev   = len(getattr(view_ref.agg, "selfbot_prev_guilds",   []) or [])
                options.append(discord.SelectOption(
                    label="Scraped Servers",
                    value="scraped",
                    description=f"Current: {active} | Previous: {prev}",
                ))

        super().__init__(placeholder="Select section", options=options, row=0)
        self.view_ref = view_ref

    async def callback(self, interaction):
        vr = self.view_ref
        if interaction.user.id != vr.invoker_id:
            return await interaction.response.send_message("Not your lookup.", ephemeral=True)
        vr.section = self.values[0]; vr.page = 0; vr.refresh_nav()
        await vr.do_edit(interaction)


# ═══════════════ /search2 ═══════════════

class LookupCog(commands.Cog):
    def __init__(self, bot) -> None: self.bot = bot

    @app_commands.command(name="search2",
        description="Checks if a user is flagged. (Card)")
    @app_commands.describe(
        user_id="Discord user ID (roblox=False) or Roblox user ID (roblox=True).",
        roblox="True = Roblox lookup (Rotector + Moco-co). False = all Discord APIs.",
        extra="Show which API detected each server.",
        private="Send privately. Default True.",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def search2(self, interaction, user_id: str, roblox: bool = False,
                      extra: bool = False, private: bool = True):
        await interaction.response.defer(ephemeral=private, thinking=True)
        disabled = self.bot.storage.get_disabled_apis()
        agg = await self.bot.detection.lookup(
            user_id=user_id, roblox_only=roblox, disabled_apis=disabled
        )

        if agg.is_empty() and agg.errors and not config.MOCK_MODE:
            warn = discord.Embed(title="Lookup Incomplete")
            warn.description = "All APIs failed.\n\n" + "\n".join(f"• {e}" for e in agg.errors[:5])
            return await interaction.followup.send(embed=warn, ephemeral=True)

        user = await _fetch_user(self.bot, user_id)
        _auto_add_db(self.bot, user_id, user, agg)

        view  = _LookupView(user, agg, extra, roblox, interaction.user.id)
        cards = view.build()
        await send_v2(interaction, *cards, view=view, ephemeral=private)
        await send_command_log(self.bot, interaction, "search2",
            {"user_id": user_id, "roblox": roblox, "extra": extra},
            agg, str(user) if user else f"User {user_id}", user_id)


class _LookupView(discord.ui.View):
    def __init__(self, user, agg, extra, roblox, invoker_id):
        super().__init__(timeout=300)
        self.user, self.agg, self.extra = user, agg, extra
        self.roblox     = roblox
        self.invoker_id = invoker_id
        self.page       = 0

        self._prev = _NavBtn("◀", invoker_id, self, -1, row=0)
        self._lbl  = _PageLabel(row=0)
        self._next = _NavBtn("▶", invoker_id, self, +1, row=0)
        self.add_item(self._prev); self.add_item(self._lbl); self.add_item(self._next)

        selfbot_guilds = getattr(agg, "selfbot_guilds", []) or []
        if selfbot_guilds and not roblox:
            self.add_item(_SelfbotRolesSelect(selfbot_guilds,    invoker_id, row=1))
            self.add_item(_SelfbotMessagesSelect(selfbot_guilds, invoker_id, row=2))

        self.refresh_nav()

    def _max_pages(self) -> int:
        return max(1, math.ceil(len(correlate_condo_servers(self.agg)) / PAGE_SIZE_CONDOS))

    def refresh_nav(self):
        mp = self._max_pages()
        self._prev.disabled = self.page <= 0
        self._next.disabled = self.page >= mp - 1
        self._lbl.label     = f"{self.page+1}/{mp}"

    def build(self) -> list:
        cards = [
            build_lookup_main(self.user, self.agg, self.extra, self.page),
            build_lookup_exploit(self.user, self.agg, self.extra),
            build_lookup_accounts(self.user, self.agg),
            build_lookup_profile(self.user, self.agg),
        ]
        return [c for c in cards if c is not None]

    async def do_edit(self, interaction):
        await edit_v2(interaction, *self.build(), view=self)
