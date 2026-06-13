from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

import config
from storage import BotStorage
from embeds import (
    build_dashboard_home, build_settings_embed, build_api_errors_embed,
    build_command_logs_embed, build_user_mgmt_embed, build_server_info_embed,
    build_database_embed,
    build_apis_embed,
)

SECTIONS = [
    ("Home",         "home"),
    ("Settings",     "settings"),
    ("API Errors",   "api_errors"),
    ("Command Logs", "command_logs"),
    ("User Mgmt",    "user_mgmt"),
    ("Server Info",  "server_info"),
    ("Database",     "database"),
    ("Status",       "status"),
    ("APIs",          "apis"),
]


# ── Modals ─────────────────────────────────────────────────────────────────────

class UserIDModal(discord.ui.Modal):
    uid = discord.ui.TextInput(label="Discord User ID",
                               placeholder="e.g. 123456789012345678",
                               min_length=17, max_length=20)

    def __init__(self, action: str, storage: BotStorage) -> None:
        super().__init__(title=f"{action} — Enter User ID")
        self.action = action; self.storage = storage

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:   user_id = int(self.uid.value.strip())
        except ValueError:
            return await interaction.response.send_message("Invalid user ID.", ephemeral=True)
        a, s = self.action.lower(), self.storage
        actions = {
            "authorize":        lambda: (s.add_role("authorized",  user_id), f"`{user_id}` authorized.",        f"`{user_id}` already authorized."),
            "deauthorize":      lambda: (s.remove_role("authorized",  user_id), f"`{user_id}` deauthorized.",   f"`{user_id}` was not authorized."),
            "blacklist":        lambda: (s.add_role("blacklisted", user_id), f"`{user_id}` blacklisted.",        None),
            "unblacklist":      lambda: (s.remove_role("blacklisted", user_id), f"`{user_id}` unblacklisted.",  f"`{user_id}` not blacklisted."),
            "add_developer":    lambda: (s.add_role("developers",  user_id), f"`{user_id}` added as dev.",       None),
            "remove_developer": lambda: (s.remove_role("developers",  user_id), f"`{user_id}` removed from devs.", f"`{user_id}` was not a dev."),
            "add_moderator":    lambda: (s.add_role("moderators",  user_id), f"`{user_id}` added as mod.",       None),
            "remove_moderator": lambda: (s.remove_role("moderators",  user_id), f"`{user_id}` removed from mods.", f"`{user_id}` was not a mod."),
            "add_tester":       lambda: (s.add_role("testers",    user_id), f"`{user_id}` added as tester.",     None),
            "remove_tester":    lambda: (s.remove_role("testers",    user_id), f"`{user_id}` removed from testers.", f"`{user_id}` was not a tester."),
        }
        if a in actions:
            ok, ok_msg, fail_msg = actions[a]()
            msg = ok_msg if (ok or fail_msg is None) else fail_msg
        else:
            msg = "Unknown action."
        await interaction.response.send_message(msg, ephemeral=True)


class ServerLookupModal(discord.ui.Modal):
    uid = discord.ui.TextInput(label="Discord User ID",
                               placeholder="e.g. 123456789012345678",
                               min_length=17, max_length=20)

    def __init__(self, bot) -> None:
        super().__init__(title="Server Info — Enter User ID"); self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:   uid = int(self.uid.value.strip())
        except ValueError:
            return await interaction.followup.send("Invalid user ID.", ephemeral=True)
        try:   user = await self.bot.fetch_user(uid)
        except discord.NotFound: user = None
        mutual = [g for g in self.bot.guilds if g.get_member(uid)]
        stored = self.bot.storage.get_user_servers(uid)
        await interaction.followup.send(embed=build_server_info_embed(user, mutual, stored), ephemeral=True)


class DatabaseUserModal(discord.ui.Modal):
    uid = discord.ui.TextInput(label="Discord User ID",
                               placeholder="e.g. 123456789012345678",
                               min_length=5, max_length=25)

    def __init__(self, action: str, storage: BotStorage) -> None:
        super().__init__(title=f"Database — {action.title()} User")
        self.action = action; self.storage = storage

    async def on_submit(self, interaction: discord.Interaction) -> None:
        uid = self.uid.value.strip()
        if self.action == "add":
            self.storage.add_flagged_user(uid, f"User {uid}", ["Manual"], [])
            msg = f"`{uid}` added to the database."
        else:
            ok  = self.storage.remove_flagged_user(uid)
            msg = f"`{uid}` removed." if ok else f"`{uid}` was not in the database."
        await interaction.response.send_message(msg, ephemeral=True)


class ActivityModal(discord.ui.Modal):
    text = discord.ui.TextInput(label="Activity Text",
                                placeholder="e.g. /check | /lookup",
                                max_length=128)

    def __init__(self, bot) -> None:
        super().__init__(title="Change Bot Activity"); self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.bot.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name=self.text.value))
        # Log the change
        if config.LOG_CHANNEL_ID:
            ch = self.bot.get_channel(int(config.LOG_CHANNEL_ID))
            if ch:
                e = discord.Embed(title="Bot Activity Changed")
                e.description = (f"Activity set to: **{self.text.value}**\n"
                                 f"Changed by: {interaction.user} (`{interaction.user.id}`)")
                e.timestamp = datetime.now(timezone.utc)
                try: await ch.send(embed=e)
                except Exception: pass
        await interaction.response.send_message(f"Activity updated to: **{self.text.value}**", ephemeral=True)


# ── Buttons ────────────────────────────────────────────────────────────────────

class _ToggleBtn(discord.ui.Button):
    def __init__(self, key, label, storage, invoker_id, row):
        on = storage.get_settings().get(key, False)
        super().__init__(label=label,
                         style=discord.ButtonStyle.success if on else discord.ButtonStyle.secondary,
                         row=row)
        self.key = key; self.storage = storage; self.invoker_id = invoker_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message("Not your dashboard.", ephemeral=True)
        self.storage.toggle_setting(self.key)
        await interaction.response.edit_message(
            embed=build_settings_embed(self.storage),
            view=build_dash_view(self.storage, self.invoker_id, "settings"))


class _UserMgmtBtn(discord.ui.Button):
    def __init__(self, action, label, style, storage, invoker_id, row):
        super().__init__(label=label, style=style, row=row)
        self.action = action; self.storage = storage; self.invoker_id = invoker_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message("Not your dashboard.", ephemeral=True)
        await interaction.response.send_modal(UserIDModal(self.action, self.storage))


class _ClearErrorsBtn(discord.ui.Button):
    def __init__(self, storage, invoker_id):
        super().__init__(label="Clear Errors", style=discord.ButtonStyle.danger, row=1)
        self.storage = storage; self.invoker_id = invoker_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message("Not your dashboard.", ephemeral=True)
        self.storage.clear_api_errors()
        await interaction.response.edit_message(
            embed=build_api_errors_embed(self.storage),
            view=build_dash_view(self.storage, self.invoker_id, "api_errors"))


class _ServerInfoBtn(discord.ui.Button):
    def __init__(self, bot, invoker_id):
        super().__init__(label="Lookup User Servers", style=discord.ButtonStyle.primary, row=1)
        self.bot = bot; self.invoker_id = invoker_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message("Not your dashboard.", ephemeral=True)
        await interaction.response.send_modal(ServerLookupModal(self.bot))


class _DatabaseBtn(discord.ui.Button):
    def __init__(self, action, label, style, storage, invoker_id):
        super().__init__(label=label, style=style, row=1)
        self.action = action; self.storage = storage; self.invoker_id = invoker_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message("Not your dashboard.", ephemeral=True)
        await interaction.response.send_modal(DatabaseUserModal(self.action, self.storage))


class _StatusBtn(discord.ui.Button):
    def __init__(self, label, status_key, style, bot, invoker_id, row):
        super().__init__(label=label, style=style, row=row)
        self.status_key = status_key; self.bot = bot; self.invoker_id = invoker_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message("Not your dashboard.", ephemeral=True)
        status_map = {
            "online": discord.Status.online, "idle": discord.Status.idle,
            "dnd": discord.Status.dnd, "invisible": discord.Status.invisible,
        }
        status = status_map[self.status_key]
        await self.bot.change_presence(status=status)
        # Log change
        if config.LOG_CHANNEL_ID:
            ch = self.bot.get_channel(int(config.LOG_CHANNEL_ID))
            if ch:
                e = discord.Embed(title="Bot Status Changed")
                e.description = (f"Status changed to **{self.label}**\n"
                                 f"Changed by: {interaction.user} (`{interaction.user.id}`)")
                e.timestamp = datetime.now(timezone.utc)
                try: await ch.send(embed=e)
                except Exception: pass
        await interaction.response.send_message(f"Status set to **{self.label}**.", ephemeral=True)


class _ActivityBtn(discord.ui.Button):
    def __init__(self, bot, invoker_id):
        super().__init__(label="Change Activity Text", style=discord.ButtonStyle.primary, row=2)
        self.bot = bot; self.invoker_id = invoker_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message("Not your dashboard.", ephemeral=True)
        await interaction.response.send_modal(ActivityModal(self.bot))



class _ApiToggleBtn(discord.ui.Button):
    API_LABELS = {
        "TASE":         "TASE",
        "BLOXYCLEANER": "BloxyCleaner",
        "ROBLOXWATCHER":"RobloxWatcher",
        "ROTECTOR":     "Rotector",
        "MOCO":         "Moco-co",
    }

    def __init__(self, api_key: str, storage, invoker_id, row):
        enabled = storage.is_api_enabled(api_key)
        label   = self.API_LABELS.get(api_key, api_key)
        super().__init__(
            label=f"{'Disable' if enabled else 'Enable'} {label}",
            style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
            row=row,
        )
        self.api_key = api_key; self.storage = storage; self.invoker_id = invoker_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message("Not your dashboard.", ephemeral=True)
        new_state = self.storage.toggle_api(self.api_key)
        label = self.API_LABELS.get(self.api_key, self.api_key)
        await interaction.response.edit_message(
            embed=build_apis_embed(self.storage),
            view=build_dash_view(self.storage, self.invoker_id, "apis"))
        # Log the change
        import config as _cfg
        if _cfg.LOG_CHANNEL_ID:
            ch = interaction.client.get_channel(int(_cfg.LOG_CHANNEL_ID))
            if ch:
                import discord as _d
                from datetime import datetime, timezone
                e = _d.Embed(title="API Setting Changed")
                e.description = (f"**{label}** {'enabled' if new_state else 'disabled'} by "
                                 f"{interaction.user} (`{interaction.user.id}`)")
                e.timestamp = datetime.now(timezone.utc)
                try: await ch.send(embed=e)
                except Exception: pass


# ── Section select ─────────────────────────────────────────────────────────────

class SectionSelect(discord.ui.Select):
    def __init__(self, invoker_id: int, current: str) -> None:
        options = [discord.SelectOption(label=l, value=v, default=(v == current))
                   for l, v in SECTIONS]
        super().__init__(placeholder="Select a section", options=options, row=0)
        self.invoker_id = invoker_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message("Not your dashboard.", ephemeral=True)
        section = self.values[0]
        bot     = interaction.client
        embed   = build_dash_embed(bot, bot.storage, section)
        view    = build_dash_view(bot.storage, self.invoker_id, section, bot)
        await interaction.response.edit_message(embed=embed, view=view)


# ── Factories ──────────────────────────────────────────────────────────────────

def build_dash_embed(bot, storage: BotStorage, section: str) -> discord.Embed:
    if section == "settings":     return build_settings_embed(storage)
    if section == "api_errors":   return build_api_errors_embed(storage)
    if section == "command_logs": return build_command_logs_embed(storage)
    if section == "user_mgmt":    return build_user_mgmt_embed(storage)
    if section == "database":     return build_database_embed(storage)
    if section == "server_info":
        from embeds import EMBED_BG
        e = discord.Embed(color=EMBED_BG, title="Server Info")
        e.description = "Click **Lookup User Servers** and enter a Discord user ID."; return e
    if section == "apis":      return build_apis_embed(storage)
    if section == "status":
        from embeds import EMBED_BG
        e = discord.Embed(color=EMBED_BG, title="Status & Activity")
        e.description = "Change the bot's online status or activity text."
        return e
    return build_dashboard_home(bot, storage)


def build_dash_view(storage: BotStorage, invoker_id: int,
                    section: str, bot=None) -> discord.ui.View:
    view = discord.ui.View(timeout=300)
    view.add_item(SectionSelect(invoker_id, section))
    BTN = discord.ButtonStyle
    if section == "settings":
        view.add_item(_ToggleBtn("private",        "Private Mode", storage, invoker_id, 1))
        view.add_item(_ToggleBtn("testing",        "Testing Mode", storage, invoker_id, 1))
        view.add_item(_ToggleBtn("moderator_only", "Mod Only",     storage, invoker_id, 2))
        view.add_item(_ToggleBtn("developer_only", "Dev Only",     storage, invoker_id, 2))
    elif section == "api_errors":
        view.add_item(_ClearErrorsBtn(storage, invoker_id))
    elif section == "user_mgmt":
        view.add_item(_UserMgmtBtn("authorize",        "Authorize",   BTN.success,   storage, invoker_id, 1))
        view.add_item(_UserMgmtBtn("deauthorize",      "Deauthorize", BTN.secondary, storage, invoker_id, 1))
        view.add_item(_UserMgmtBtn("blacklist",        "Blacklist",   BTN.danger,    storage, invoker_id, 1))
        view.add_item(_UserMgmtBtn("unblacklist",      "Unblacklist", BTN.secondary, storage, invoker_id, 1))
        view.add_item(_UserMgmtBtn("add_developer",    "Add Dev",     BTN.primary,   storage, invoker_id, 2))
        view.add_item(_UserMgmtBtn("remove_developer", "Rem Dev",     BTN.secondary, storage, invoker_id, 2))
        view.add_item(_UserMgmtBtn("add_moderator",    "Add Mod",     BTN.primary,   storage, invoker_id, 3))
        view.add_item(_UserMgmtBtn("remove_moderator", "Rem Mod",     BTN.secondary, storage, invoker_id, 3))
        view.add_item(_UserMgmtBtn("add_tester",       "Add Tester",  BTN.primary,   storage, invoker_id, 4))
        view.add_item(_UserMgmtBtn("remove_tester",    "Rem Tester",  BTN.secondary, storage, invoker_id, 4))
    elif section == "server_info" and bot:
        view.add_item(_ServerInfoBtn(bot, invoker_id))
    elif section == "database":
        view.add_item(_DatabaseBtn("add",    "Add User",    BTN.success, storage, invoker_id))
        view.add_item(_DatabaseBtn("remove", "Remove User", BTN.danger,  storage, invoker_id))
    elif section == "apis":
        keys = ["TASE", "BLOXYCLEANER", "ROBLOXWATCHER", "ROTECTOR", "MOCO"]
        for i, key in enumerate(keys):
            view.add_item(_ApiToggleBtn(key, storage, invoker_id, row=1 + (i // 3)))
    elif section == "status" and bot:
        view.add_item(_StatusBtn("Online",    "online",    BTN.success,   bot, invoker_id, 1))
        view.add_item(_StatusBtn("Idle",      "idle",      BTN.secondary, bot, invoker_id, 1))
        view.add_item(_StatusBtn("DND",       "dnd",       BTN.danger,    bot, invoker_id, 1))
        view.add_item(_StatusBtn("Invisible", "invisible", BTN.secondary, bot, invoker_id, 1))
        view.add_item(_ActivityBtn(bot, invoker_id))
    return view


# ── Cog ────────────────────────────────────────────────────────────────────────

class DashboardCog(commands.Cog):
    def __init__(self, bot) -> None: self.bot = bot

    @app_commands.command(name="dashboard", description="FlagChecker admin dashboard.")
    async def dashboard(self, interaction: discord.Interaction) -> None:
        is_owner = await self.bot.is_owner(interaction.user)
        is_dev   = self.bot.storage.has_role("developers", interaction.user.id)
        if not (is_owner or is_dev):
            return await interaction.response.send_message(
                "You don't have permission to use the dashboard.", ephemeral=True)
        embed = build_dashboard_home(self.bot, self.bot.storage)
        view  = build_dash_view(self.bot.storage, interaction.user.id, "home", self.bot)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(DashboardCog(bot))
