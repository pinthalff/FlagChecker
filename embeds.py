from __future__ import annotations
from datetime import datetime, timezone

import discord

import config
from models import AggregateResult
from storage import BotStorage


# Thin gray separator (subtext + strikethrough trick)
EMBED_BG  = 0x1e1f22   # matches Discord embed background — hides left border
GRAY_LINE = "-# ~~" + "\u00a0" * 80 + "~~"


def _now() -> datetime: return datetime.now(timezone.utc)
def _dot(on: bool) -> str: return "🟢" if on else "🔴"


# ── Bot / status ──────────────────────────────────────────────────────────────

def build_bot_ready_embed(bot) -> discord.Embed:
    e = discord.Embed(color=EMBED_BG, title="FlagChecker — Online",
                      description=f"**FlagChecker** ({bot.user}) is now online.")
    e.add_field(name="Servers",   value=str(len(bot.guilds)), inline=True)
    e.add_field(name="Mock Mode", value="✅ ON" if config.MOCK_MODE else "❌ OFF", inline=True)
    e.timestamp = _now(); return e

def build_status_control_embed(label: str) -> discord.Embed:
    e = discord.Embed(color=EMBED_BG, title="FlagChecker — Status",
                      description=f"Current status: **{label}**")
    e.set_footer(text="Owner only"); e.timestamp = _now(); return e


# ── Command logging ──────────────────────────────────────────────────────────

def build_command_used_embed(interaction: discord.Interaction, command: str, options: dict) -> discord.Embed:
    e = discord.Embed(color=EMBED_BG, title="✅ Command Used")
    e.add_field(name="User",    value=f"{interaction.user} (`{interaction.user.id}`)", inline=True)
    e.add_field(name="Command", value=f"`/{command}`",                                 inline=True)
    e.add_field(name="Server",  value=interaction.guild.name if interaction.guild else "DM", inline=True)
    if options:
        e.add_field(name="Options",
                    value="\n".join(f"`{k}`: {v}" for k, v in options.items()), inline=False)
    e.timestamp = _now(); return e

def build_overview_embed(interaction, agg: AggregateResult,
                         target_label: str, target_id) -> discord.Embed:
    e = discord.Embed(color=EMBED_BG, title="📋 Detection Overview")
    e.add_field(name="Target", value=f"{target_label} (`{target_id}`)", inline=False)
    e.add_field(name="Sources", value=(
        f"{_dot(bool(agg.tase_guilds_count))} TASE ({agg.tase_guilds_count} guilds)\n"
        f"{_dot(bool(agg.rw_condo_count))} RW Condos ({agg.rw_condo_count})\n"
        f"{_dot(bool(agg.rw_exploit_count))} RW Exploits ({agg.rw_exploit_count})\n"
        f"{_dot(bool(agg.rotector_flag_type))} Rotector\n"
        f"{_dot(bool(agg.moco_group_count))} Moco-co\n"
        f"{_dot(agg.bloxycleaner_flagged or agg.bloxycleaner_exploit_flagged)} BloxyCleaner"
    ), inline=True)
    e.add_field(name="Flagged By",
                value=", ".join(agg.sources_flagged) if agg.sources_flagged else "✅ None",
                inline=True)
    if agg.errors:
        e.add_field(name="⚠️ API Errors", value="\n".join(agg.errors[:5]), inline=False)
    e.timestamp = _now(); return e


# ── Event embeds (keep colors) ────────────────────────────────────────────────

def build_guild_join_embed(guild: discord.Guild) -> discord.Embed:
    e = discord.Embed(color=EMBED_BG, title="➕ Bot Added to Server")
    e.add_field(name="Server",    value=guild.name,                     inline=True)
    e.add_field(name="Server ID", value=f"`{guild.id}`",                inline=True)
    e.add_field(name="Members",   value=str(guild.member_count or "?"), inline=True)
    e.add_field(name="Owner",     value=f"<@{guild.owner_id}>",         inline=True)
    if guild.icon: e.set_thumbnail(url=guild.icon.url)
    e.timestamp = _now(); return e

def build_guild_remove_embed(guild: discord.Guild) -> discord.Embed:
    e = discord.Embed(color=EMBED_BG, title="➖ Bot Removed from Server")
    e.add_field(name="Server",    value=guild.name,      inline=True)
    e.add_field(name="Server ID", value=f"`{guild.id}`", inline=True)
    if guild.icon: e.set_thumbnail(url=guild.icon.url)
    e.timestamp = _now(); return e

def build_dm_embed(message: discord.Message) -> discord.Embed:
    e = discord.Embed(color=EMBED_BG, title="💬 Direct Message Received")
    e.add_field(name="From", value=f"{message.author} (`{message.author.id}`)", inline=False)
    content = (message.content[:500] + "…") if len(message.content) > 500 else message.content
    e.add_field(name="Message", value=content or "*No text content*", inline=False)
    if message.attachments:
        e.add_field(name=f"Attachments ({len(message.attachments)})",
                    value="\n".join(a.filename for a in message.attachments[:5]), inline=False)
    e.set_thumbnail(url=message.author.display_avatar.url)
    e.timestamp = message.created_at; return e

def build_user_install_embed(data: dict) -> discord.Embed:
    e = discord.Embed(color=EMBED_BG, title="👤 User Installed Bot")
    user = data.get("user") or {}
    e.add_field(name="User",
                value=f"{user.get('username', 'Unknown')} (`{user.get('id', '?')}`)", inline=False)
    e.add_field(name="Integration Type", value=str(data.get("integration_type", "?")), inline=True)
    e.add_field(name="Scopes", value=f"`{', '.join(data.get('scopes', [])) or 'n/a'}`", inline=True)
    e.timestamp = _now(); return e

def build_command_error_embed(interaction: discord.Interaction, error: Exception) -> discord.Embed:
    e = discord.Embed(color=EMBED_BG, title="❌ Command Error")
    e.add_field(name="User",    value=f"{interaction.user} (`{interaction.user.id}`)", inline=True)
    e.add_field(name="Command", value=f"`/{interaction.command.name if interaction.command else '?'}`", inline=True)
    e.add_field(name="Server",  value=interaction.guild.name if interaction.guild else "DM", inline=True)
    e.add_field(name="Error",   value=f"```{type(error).__name__}: {str(error)[:300]}```", inline=False)
    e.timestamp = _now(); return e


# ── Dashboard embeds (keep colors) ────────────────────────────────────────────

def build_dashboard_home(bot, storage: BotStorage) -> discord.Embed:
    s = storage.get_settings()
    e = discord.Embed(color=EMBED_BG, title="FlagChecker — Dashboard",
                      description="Admin only Dashboard.")
    e.add_field(name="⚙️ Current Mode", value=(
        f"{_dot(s['private'])} Private Mode\n"
        f"{_dot(s['testing'])} Testing Mode\n"
        f"{_dot(s['moderator_only'])} Moderator Only\n"
        f"{_dot(s['developer_only'])} Developer Only"
    ), inline=True)
    e.add_field(name="📊 Stats", value=(
        f"Servers: `{len(bot.guilds)}`\n"
        f"API Errors: `{len(storage.get_api_errors(100))}`\n"
        f"Command Logs: `{len(storage.get_command_logs(100))}`"
    ), inline=True)
    e.add_field(name="👥 Roles", value=(
        f"Developers: `{len(storage.get_role_list('developers'))}`\n"
        f"Moderators: `{len(storage.get_role_list('moderators'))}`\n"
        f"Testers: `{len(storage.get_role_list('testers'))}`\n"
        f"Authorized: `{len(storage.get_role_list('authorized'))}`\n"
        f"Blacklisted: `{len(storage.get_role_list('blacklisted'))}`"
    ), inline=True)
    e.set_footer(text="Only the bot owner and developers can use this dashboard.")
    e.timestamp = _now(); return e

def build_settings_embed(storage: BotStorage) -> discord.Embed:
    s = storage.get_settings()
    e = discord.Embed(color=EMBED_BG, title="⚙️ Bot Settings",
                      description="Toggle bot access modes using the buttons below.")
    e.add_field(name="Access Modes", value=(
        f"{_dot(s['private'])} **Private Mode** — only authorized users\n"
        f"{_dot(s['testing'])} **Testing Mode** — only testers, mods & devs\n"
        f"{_dot(s['moderator_only'])} **Moderator Only** — only mods & devs\n"
        f"{_dot(s['developer_only'])} **Developer Only** — only devs"
    ), inline=False)
    e.timestamp = _now(); return e

def build_api_errors_embed(storage: BotStorage) -> discord.Embed:
    errors = storage.get_api_errors(15)
    e = discord.Embed(color=EMBED_BG, title="⚠️ Recent API Errors")
    if not errors:
        e.description = "✅ No API errors recorded."; e.timestamp = _now(); return e
    e.description = "\n\n".join(
        f"`{err.get('timestamp','?')[:19].replace('T',' ')}` **{err.get('source','?')}** "
        f"via `/{err.get('command','?')}`\n┕ {err.get('error','Unknown')[:80]}"
        for err in errors
    )
    e.timestamp = _now(); return e

def build_command_logs_embed(storage: BotStorage) -> discord.Embed:
    logs = storage.get_command_logs(15)
    e = discord.Embed(color=EMBED_BG, title="📋 Recent Command Logs")
    if not logs:
        e.description = "No commands logged yet."; e.timestamp = _now(); return e
    e.description = "\n\n".join(
        f"`{en.get('timestamp','?')[:19].replace('T',' ')}` `/{en.get('command','?')}` "
        f"— **{en.get('username','?')}** (`{en.get('user_id','?')}`)\n┕ Target: {en.get('target_label','?')}"
        for en in logs
    )
    e.timestamp = _now(); return e

def build_user_mgmt_embed(storage: BotStorage) -> discord.Embed:
    e = discord.Embed(color=EMBED_BG, title="👥 User Management")
    def fmt(role): return ", ".join(f"`{u}`" for u in storage.get_role_list(role)[:10]) or "*None*"
    e.add_field(name=f"👨‍💻 Developers ({len(storage.get_role_list('developers'))})",  value=fmt("developers"),  inline=False)
    e.add_field(name=f"🛡️ Moderators ({len(storage.get_role_list('moderators'))})",   value=fmt("moderators"),  inline=False)
    e.add_field(name=f"🧪 Testers ({len(storage.get_role_list('testers'))})",          value=fmt("testers"),     inline=False)
    e.add_field(name=f"✅ Authorized ({len(storage.get_role_list('authorized'))})",    value=fmt("authorized"),  inline=False)
    e.add_field(name=f"🚫 Blacklisted ({len(storage.get_role_list('blacklisted'))})",  value=fmt("blacklisted"), inline=False)
    e.timestamp = _now(); return e

def build_server_info_embed(user, guilds: list, stored: list) -> discord.Embed:
    if user is None:
        e = discord.Embed(color=EMBED_BG, title="🌐 Server Info")
        e.description = "User not found."; return e
    e = discord.Embed(color=EMBED_BG, title=f"🌐 Server Info — {user}")
    e.set_thumbnail(url=user.display_avatar.url)
    e.add_field(name="User ID", value=f"`{user.id}`", inline=True)
    if guilds:
        lines = [f"🔹 **{g.name}** · `{g.id}`" for g in guilds[:20]]
        if len(guilds) > 20: lines.append(f"*…and {len(guilds)-20} more*")
        e.add_field(name=f"Mutual Servers ({len(guilds)})", value="\n".join(lines), inline=False)
    else:
        e.add_field(name="Mutual Servers", value="*None — no shared servers.*", inline=False)
    if stored:
        e.add_field(name=f"Servers at Install ({len(stored)})",
                    value="\n".join(f"🔸 **{s['name']}** · `{s['id']}`" for s in stored[:10]),
                    inline=False)
    e.timestamp = _now(); return e


# ═══════════════════════════════════════════════════════════════════════════
#  /check dropdown — Data Overview, Condos, Exploits
# ═══════════════════════════════════════════════════════════════════════════

def build_database_embed(storage: BotStorage) -> discord.Embed:
    users = storage.list_flagged_users(15)
    e = discord.Embed(color=EMBED_BG, title="📁 Flagged User Database")
    if not users:
        e.description = "*No users in the database yet.*"
    else:
        lines = []
        for u in users:
            uid     = u.get("discord_id", "?")
            uname   = u.get("username", "Unknown")
            sources = ", ".join(u.get("sources", [])) or "Unknown"
            added   = u.get("added_at", "?")[:10]
            lines.append(f"**{uname}** (`{uid}`)\n\u2515 Flagged by: `{sources}` \u00b7 `{added}`")
        e.description = "\n\n".join(lines)
        total = len(storage.list_flagged_users(99999))
        e.set_footer(text=f"Total: {total} flagged users")
    e.timestamp = _now()
    return e


def build_api_error_log_embed(command: str, user: str, errors: list) -> discord.Embed:
    e = discord.Embed(color=EMBED_BG, title="API Errors Detected")
    e.add_field(name="Command", value=f"`/{command}`", inline=True)
    e.add_field(name="Run by",  value=user,            inline=True)
    e.description = "\n".join(f"• `{err}`" for err in errors[:10])
    e.timestamp = _now()
    return e


def build_apis_embed(storage) -> discord.Embed:
    e = discord.Embed(color=EMBED_BG, title="API Settings")
    api_labels = {
        "TASE":         "TASE",
        "BLOXYCLEANER": "BloxyCleaner",
        "ROBLOXWATCHER":"RobloxWatcher",
        "ROTECTOR":     "Rotector",
        "MOCO":         "Moco-co",
    }
    lines = []
    for key, label in api_labels.items():
        on = storage.is_api_enabled(key)
        lines.append(f"{'🟢' if on else '🔴'} **{label}** — {'Enabled' if on else 'Disabled'}")
    e.description = "\n".join(lines)
    e.set_footer(text="Toggle APIs using the buttons below.")
    e.timestamp = _now()
    return e



from detection import correlate_condo_servers, correlate_exploit_servers, format_last_seen


def _badge_row(breakdown: dict) -> str:
    """Format TASE score breakdown as a one-line badge row."""
    if not breakdown:
        return ""
    parts = []
    for key, val in breakdown.items():
        if val == 0: continue
        label = key.replace("_", " ").title()
        sign  = "+" if val >= 0 else ""
        parts.append(f"**{label}** `{sign}{val}`")
    return " · ".join(parts)


def build_check_overview(user, agg: AggregateResult) -> discord.Embed:
    condos   = correlate_condo_servers(agg)
    exploits = correlate_exploit_servers(agg)
    total    = len(condos) + len(exploits)

    name    = str(user) if user else f"User {agg.discord_id or agg.roblox_id}"
    mention = f"<@{user.id}>" if user else "Unknown"
    uid     = user.id if user else (agg.discord_id or agg.roblox_id)

    desc  = f"**{name}**\n"
    desc += f"User: {mention}\n"
    desc += f"User ID: `{uid}`\n"
    desc += f"\n{GRAY_LINE}\n\n"
    desc += f"**Total Records:** `{total}`\n"
    desc += f"🚨 Condo Records: `{len(condos)}`\n"
    desc += f"💥 Exploit Records: `{len(exploits)}`\n"
    desc += f"\n**Flagged By:** {', '.join(agg.sources_flagged) if agg.sources_flagged else '✅ None'}\n"

    if agg.tase_score is not None:
        desc += f"\n**TASE Score:** `{agg.tase_score}`"
    if agg.rotector_flag_type:
        flag = config.ROTECTOR_FLAG_LABELS.get(agg.rotector_flag_type, "Unknown")
        conf = agg.rotector_confidence or 0
        desc += f"\n**Rotector:** {flag} · {conf:.1f}%"

    badges = _badge_row(agg.tase_score_breakdown)
    if badges:
        desc += f"\n\n{GRAY_LINE}\n\n{badges}"

    e = discord.Embed(color=EMBED_BG, title="📋 Data Overview", description=desc)
    if user and hasattr(user, "display_avatar") and user.display_avatar:
        e.set_thumbnail(url=user.display_avatar.url)
    e.timestamp = _now()
    return e


def build_check_condos(agg: AggregateResult) -> discord.Embed:
    """Condo records — uses ALL APIs (BloxyCleaner, RobloxWatcher, TASE, Rotector, Moco-co)."""
    condos = correlate_condo_servers(agg)
    timestamps = [s["last_seen"] for s in condos if s.get("last_seen")]
    first_seen = format_last_seen(min(timestamps)) if timestamps else "n/a"
    last_seen  = format_last_seen(max(timestamps)) if timestamps else "n/a"

    desc  = f"**First Seen:** `{first_seen}`\n"
    desc += f"**Last Seen:** `{last_seen}`\n"
    desc += f"**Total Records:** `{len(condos)}`\n"

    if condos:
        desc += f"\n{GRAY_LINE}\n\n"
        chunks = []
        for s in condos[:10]:
            line  = f"• **{s['name']}**"
            if s.get("id"): line += f" (`{s['id']}`)"
            line += f"\n   ↳ Sources: `{', '.join(s['sources'])}`"
            if s.get("last_seen"):
                line += f"\n   ↳ Last seen: `{format_last_seen(s['last_seen'])}`"
            chunks.append(line)
        desc += "\n\n".join(chunks)
        if len(condos) > 10:
            desc += f"\n\n*+{len(condos)-10} more not shown*"
    else:
        desc += f"\n{GRAY_LINE}\n\n*No condo records detected.*"

    e = discord.Embed(color=EMBED_BG, title="🚨 Condo Records", description=desc)
    e.timestamp = _now()
    return e


def build_check_exploits(agg: AggregateResult) -> discord.Embed:
    """Exploit records — aggregated from RobloxWatcher and BloxyCleaner (Exploit DB)."""
    exploits = correlate_exploit_servers(agg)
    desc = f"**Total Records:** `{len(exploits)}`\n"

    if exploits:
        desc += f"\n{GRAY_LINE}\n\n"
        lines = []
        for s in exploits[:15]:
            line  = f"• **{s['name']}**"
            if s.get("id"): line += f" (`{s['id']}`)"
            line += f"\n   ↳ Source: `{', '.join(s.get('sources', [])) or 'Unknown'}`"
            lines.append(line)
        desc += "\n\n".join(lines)
        if len(exploits) > 15:
            desc += f"\n\n*+{len(exploits)-15} more not shown*"
    else:
        desc += f"\n{GRAY_LINE}\n\n*No exploit records detected.*"

    e = discord.Embed(color=EMBED_BG, title="💥 Exploit Records", description=desc)
    e.timestamp = _now()
    return e


# ═══════════════════════════════════════════════════════════════════════════
#  /lookup — embed-style card with separate exploit card under it
# ═══════════════════════════════════════════════════════════════════════════

def build_lookup_main_embed(user, agg: AggregateResult) -> discord.Embed:
    name    = str(user) if user else f"User {agg.discord_id or agg.roblox_id}"
    mention = f"<@{user.id}>" if user else "Unknown"
    uid     = user.id if user else (agg.discord_id or agg.roblox_id)

    condos = correlate_condo_servers(agg)
    timestamps = [s["last_seen"] for s in condos if s.get("last_seen")]
    last_seen  = format_last_seen(max(timestamps)) if timestamps else "—"

    desc  = f"**{name}**\n\n"
    desc += f"User: {mention}\n"
    desc += f"User ID: `{uid}`\n"
    desc += f"Last Seen: `{last_seen}`\n"

    badges = _badge_row(agg.tase_score_breakdown)
    if badges:
        desc += f"\n{badges}\n"

    desc += f"\n{GRAY_LINE}\n\n"

    if condos:
        flagged = ", ".join(agg.sources_flagged) if agg.sources_flagged else "—"
        desc += f"🚨 **Flagged by:** {flagged}\n"
        desc += f"📊 **Condo Records:** `{len(condos)}`\n"
        if agg.tase_score is not None:
            desc += f"📈 **TASE Score:** `{agg.tase_score}`\n"
        if agg.rotector_flag_type:
            flag = config.ROTECTOR_FLAG_LABELS.get(agg.rotector_flag_type, "Unknown")
            conf = agg.rotector_confidence or 0
            desc += f"🔍 **Rotector:** {flag} · `{conf:.1f}%`\n"
        desc += f"\n{GRAY_LINE}\n\n"
        for s in condos[:8]:
            desc += f"🔹 **{s['name']}**"
            if s.get("id"): desc += f" (`{s['id']}`)"
            desc += f"\n   ↳ `{', '.join(s['sources'])}`"
            if s.get("last_seen"): desc += f" · Last: `{format_last_seen(s['last_seen'])}`"
            desc += "\n"
        if len(condos) > 8:
            desc += f"\n*+{len(condos)-8} more*"
    else:
        desc += "🦦 This user has not been flagged in any database."

    e = discord.Embed(color=EMBED_BG, description=desc)
    if user and hasattr(user, "display_avatar") and user.display_avatar:
        e.set_thumbnail(url=user.display_avatar.url)
    e.timestamp = _now()
    return e


def build_lookup_exploit_embed(user, agg: AggregateResult) -> discord.Embed:
    """Separate exploit card — sits UNDER the main lookup card."""
    exploits = correlate_exploit_servers(agg)
    name = str(user) if user else f"User {agg.discord_id or agg.roblox_id}"

    desc = f"**Exploiting Records — {name}**\n"
    desc += f"Total: `{len(exploits)}`\n"
    desc += f"\n{GRAY_LINE}\n\n"

    if exploits:
        lines = [f"• **{s['name']}** (`{s.get('id', '?')}`)" for s in exploits[:10]]
        desc += "\n".join(lines)
        sources = sorted({src for s in exploits for src in s.get("sources", [])})
        desc += f"\n\n🚨 Detected via **{' / '.join(sources)}**"
    else:
        desc += "🦦 This user has not been flagged for exploiting."

    e = discord.Embed(color=EMBED_BG, description=desc)
    e.timestamp = _now()
    return e
