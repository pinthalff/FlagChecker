# v2.py

# v2.py

# v2.py

# v2.py

from __future__ import annotations
import math
from typing import Optional

import discord

import config
from models import AggregateResult
from detection import correlate_condo_servers, correlate_exploit_servers, format_last_seen

FLAG_V2        = 1 << 15
FLAG_EPHEMERAL = 1 << 6
PAGE_SIZE_CONDOS   = 6
PAGE_SIZE_EXPLOITS = 8


def c_text(content: str) -> dict:
    return {"type": 10, "content": content}

def c_sep(spacing: int = 1) -> dict:
    return {"type": 14, "divider": True, "spacing": spacing}

def c_section(content: str, thumbnail_url: Optional[str] = None) -> dict:
    s: dict = {"type": 9, "components": [c_text(content)]}
    if thumbnail_url:
        s["accessory"] = {"type": 11, "media": {"url": thumbnail_url}}
    return s

def c_container(*components) -> dict:
    return {"type": 17, "components": list(components)}


async def send_v2(interaction, *components, view=None, ephemeral=False):
    flags = FLAG_V2 | (FLAG_EPHEMERAL if ephemeral else 0)
    parts = list(components)
    if view: parts.extend(view.to_components())
    route = discord.http.Route(
        "POST", "/webhooks/{application_id}/{interaction_token}",
        application_id=interaction.application_id,
        interaction_token=interaction.token,
    )
    data = await interaction.client.http.request(route, json={"flags": flags, "components": parts})
    if view and isinstance(data, dict) and data.get("id"):
        try: interaction.client._connection.store_view(view, int(data["id"]))
        except Exception: pass
    return data


async def edit_v2(interaction, *components, view=None):
    parts = list(components)
    if view: parts.extend(view.to_components())
    route = discord.http.Route(
        "POST", "/interactions/{interaction_id}/{interaction_token}/callback",
        interaction_id=interaction.id, interaction_token=interaction.token,
    )
    await interaction.client.http.request(route, json={
        "type": 7, "data": {"flags": FLAG_V2, "components": parts},
    })
    try:
        interaction.response._responded = True
    except AttributeError:
        pass


_BADGE_ICONS = {
    "booster": "💎", "staff": "🔨", "moderator": "🛡️", "partner": "🤝",
    "early_supporter": "⭐", "messages": "💬", "typing": "⌨️",
    "reactions": "⚡", "nsfw_content": "🔞", "exploiting": "💥",
    "scam": "⚠️", "spam": "📢",
}
_TIER1 = {"booster", "staff", "moderator", "partner", "early_supporter"}

def _score_badges(breakdown: dict) -> str:
    if not breakdown: return ""
    t1, t2 = [], []
    for key, val in breakdown.items():
        if not val: continue
        icon  = _BADGE_ICONS.get(key, "")
        label = key.replace("_", " ").title()
        sign  = "+" if val >= 0 else ""
        badge = f"{icon} {label} `{sign}{val}`".strip()
        (t1 if key in _TIER1 else t2).append(badge)
    lines = []
    if t1: lines.append(" | ".join(t1))
    if t2: lines.append(" · ".join(t2))
    return "\n".join(lines)


def _server_line(s: dict, extra: bool) -> str:
    still_in = s.get("still_in")
    status   = ""
    if still_in is True:
        status = " — `Current`"
    elif still_in is False:
        status = " — `Previous`"

    line = f"• **{s['name']}**"
    if s.get("id"):      line += f" (`{s['id']}`)"
    line += status
    if extra and s.get("sources"): line += f" — `{', '.join(s['sources'])}`"

    # Always show type and activity — not gated on extra
    if s.get("guild_types"):
        line += f"\n  ↳ Type: `{', '.join(s['guild_types'])}`"
    if s.get("guild_flags"):
        line += f"\n  ↳ Flags: `{', '.join(s['guild_flags'])}`"
    if s.get("score"):
        line += f"\n  ↳ Score: `{s['score']}`"
    act = s.get("activity", {})
    if act and any(act.values()):
        parts = []
        if act.get("messages"):  parts.append(f"{act['messages']} msgs")
        if act.get("reactions"): parts.append(f"{act['reactions']} reactions")
        if act.get("vc_joins"):  parts.append(f"{act['vc_joins']} vc joins")
        if act.get("boosts"):    parts.append(f"{act['boosts']} boosts")
        if parts:
            line += f"\n  ↳ Activity: `{', '.join(parts)}`"
    return line


def _display_name(user, agg: AggregateResult) -> str:
    if user:
        return str(user)
    if agg.roblox_username:
        return agg.roblox_username
    return f"User {agg.discord_id or agg.roblox_id}"


def _avatar_url(user, agg: AggregateResult) -> Optional[str]:
    if user and user.display_avatar:
        return str(user.display_avatar.url)
    return None


def _merge_selfbot_into_exploits(exploits: list, agg: AggregateResult) -> list:
    selfbot_active = getattr(agg, "selfbot_active_guilds", []) or []
    selfbot_prev   = getattr(agg, "selfbot_prev_guilds",   []) or []
    existing_names = {s["name"].lower() for s in exploits}

    for g in selfbot_active:
        name = g.get("guild_name", "Unknown")
        if name.lower() not in existing_names:
            exploits.append({
                "name":        name,
                "id":          str(g.get("guild_id", "")),
                "sources":     ["Selfbot"],
                "last_seen":   None,
                "score":       0,
                "guild_types": [],
                "guild_flags": [],
                "activity":    {},
                "still_in":    True,
            })
            existing_names.add(name.lower())

    for g in selfbot_prev:
        name = g.get("guild_name", "Unknown")
        if name.lower() not in existing_names:
            exploits.append({
                "name":        f"(Previous Server) {name}",
                "id":          str(g.get("guild_id", "")),
                "sources":     ["Selfbot"],
                "last_seen":   None,
                "score":       0,
                "guild_types": [],
                "guild_flags": [],
                "activity":    {},
                "still_in":    False,
            })
            existing_names.add(name.lower())

    return exploits


def build_check_overview(user, agg: AggregateResult, extra: bool = False) -> dict:
    condos   = correlate_condo_servers(agg)
    exploits = correlate_exploit_servers(agg)
    exploits = _merge_selfbot_into_exploits(exploits, agg)

    name   = _display_name(user, agg)
    avatar = _avatar_url(user, agg)

    if user:
        uid_line = f"Discord: `{user.id}`\nUser: <@{user.id}>"
    elif agg.roblox_id:
        uid_line = f"Roblox ID: `{agg.roblox_id}`"
        if agg.roblox_username:
            uid_line += f"\nUsername: **{agg.roblox_username}**"
    else:
        uid_line = f"ID: `{agg.discord_id}`"

    header = f"## {name}\n{uid_line}"

    stats  = f"Total Records: `{len(condos) + len(exploits)}`\n"
    stats += f"Condo Records: `{len(condos)}`\n"
    stats += f"Exploit Records: `{len(exploits)}`\n"
    stats += f"\nFlagged: {'Yes' if agg.sources_flagged else 'No'}"
    if extra and agg.sources_flagged:
        stats += f" — {', '.join(agg.sources_flagged)}"

    if agg.rotector_flag_type is not None:
        flag = config.ROTECTOR_FLAG_LABELS.get(agg.rotector_flag_type, "Unknown")
        conf = agg.rotector_confidence or 0
        stats += f"\nRotector: {flag} · Confidence: `{conf:.1f}%`"
    if agg.rotector_discord_servers:
        stats += f"\nRotector: `{len(agg.rotector_discord_servers)}` tracked server(s)"
    if agg.tase_score is not None:
        stats += f"\nTASE Score: `{agg.tase_score}`"
    if agg.moco_group_count:
        stats += f"\nMoco-co Groups: `{agg.moco_group_count}`"
    if extra and agg.sources_checked:
        stats += f"\nAPIs Checked: `{', '.join(agg.sources_checked)}`"

    roblox_ids = list({*agg.rw_roblox_ids, *agg.ew_roblox_ids})
    if roblox_ids:
        stats += f"\nLinked Roblox IDs: `{'`, `'.join(roblox_ids)}`"

    head_comp = c_section(header, avatar) if avatar else c_text(header)
    inner = [head_comp, c_sep(), c_text(stats)]
    badges = _score_badges(agg.tase_score_breakdown)
    if badges: inner += [c_sep(), c_text(badges)]
    return c_container(*inner)


def build_check_condos(agg: AggregateResult, extra: bool = False, page: int = 0) -> dict:
    condos      = correlate_condo_servers(agg)
    total       = len(condos)
    total_pages = max(1, math.ceil(total / PAGE_SIZE_CONDOS))
    page_data   = condos[page * PAGE_SIZE_CONDOS:(page + 1) * PAGE_SIZE_CONDOS]
    timestamps  = [s["last_seen"] for s in condos if s.get("last_seen")]

    header  = f"First Seen: `{format_last_seen(min(timestamps)) if timestamps else 'n/a'}`"
    header += f" · Last Seen: `{format_last_seen(max(timestamps)) if timestamps else 'n/a'}`\n"
    header += f"Total Records: `{total}`"

    if page_data:
        lines = []
        for s in page_data:
            line = _server_line(s, extra)
            if s.get("last_seen"): line += f"\n  ↳ Last seen: `{format_last_seen(s['last_seen'])}`"
            lines.append(line)
        body  = "\n\n".join(lines) + f"\n\n-# Page {page+1}/{total_pages} · Servers: {total}"
        inner = [c_text(header), c_sep(), c_text(body)]
    else:
        inner = [c_text(header), c_sep(), c_text("No condo records detected.")]
    return c_container(*inner)


def build_check_exploits(agg: AggregateResult, extra: bool = False, page: int = 0) -> dict:
    exploits    = correlate_exploit_servers(agg)
    exploits    = _merge_selfbot_into_exploits(exploits, agg)
    total       = len(exploits)
    total_pages = max(1, math.ceil(total / PAGE_SIZE_EXPLOITS))
    page_data   = exploits[page * PAGE_SIZE_EXPLOITS:(page + 1) * PAGE_SIZE_EXPLOITS]

    ew_note = ""
    if agg.ew_flagged:
        ew_note = f" · ExploitWatcher Score: `{agg.ew_total_score}`"

    header = f"Total Records: `{total}`{ew_note}"
    if page_data:
        lines = [_server_line(s, extra) for s in page_data]
        body  = "\n\n".join(lines) + f"\n\n-# Page {page+1}/{total_pages} · Servers: {total}"
        inner = [c_text(header), c_sep(), c_text(body)]
    else:
        inner = [c_text(header), c_sep(), c_text("No exploit records detected.")]
    return c_container(*inner)


def build_check_accounts(agg: AggregateResult) -> dict:
    accounts = []

    roblox_ids = list({*agg.rw_roblox_ids, *agg.ew_roblox_ids})
    if roblox_ids:
        accounts.append("**Linked Roblox IDs (RW/EW)**")
        for rid in roblox_ids:
            accounts.append(f"• `{rid}`")
        accounts.append("")

    if agg.rotector_connections:
        accounts.append("**Linked Roblox Accounts**")
        for conn in agg.rotector_connections:
            u   = conn.get('robloxUsername', '?')
            uid = conn.get('robloxUserId', '?')
            accounts.append(f"• {u} (`{uid}`)")
            detected = conn.get('detectedAt')
            if detected: accounts.append(f"  ↳ Detected: {detected[:10]}")
    if agg.rotector_alt_accounts:
        if accounts: accounts.append("")
        accounts.append("**Roblox Alt Accounts**")
        for alt in agg.rotector_alt_accounts:
            u   = alt.get('robloxUsername', '?')
            uid = alt.get('robloxUserId', '?')
            accounts.append(f"• {u} (`{uid}`)")
            detected = alt.get('detectedAt')
            if detected: accounts.append(f"  ↳ Detected: {detected[:10]}")
    if not accounts:
        return c_container(c_text("No linked accounts."))
    body = "\n".join(accounts)
    return c_container(c_text("## Accounts"), c_sep(), c_text(body))


def build_lookup_main(user, agg: AggregateResult, extra: bool = False, page: int = 0) -> dict:
    name   = _display_name(user, agg)
    avatar = _avatar_url(user, agg)

    if user:
        uid_line = f"User: <@{user.id}>\nUser ID: `{user.id}`"
    elif agg.roblox_id:
        uid_line = f"Roblox ID: `{agg.roblox_id}`"
        if agg.roblox_username:
            uid_line += f"\nUsername: **{agg.roblox_username}**"
    else:
        uid_line = f"User ID: `{agg.discord_id}`"

    condos      = correlate_condo_servers(agg)
    total       = len(condos)
    total_pages = max(1, math.ceil(total / PAGE_SIZE_CONDOS)) if total else 1
    page_data   = condos[page * PAGE_SIZE_CONDOS:(page + 1) * PAGE_SIZE_CONDOS]
    timestamps  = [s["last_seen"] for s in condos if s.get("last_seen")]
    last_seen   = format_last_seen(max(timestamps)) if timestamps else "n/a"

    rotector_line = ""
    if agg.rotector_flag_type is not None:
        flag = config.ROTECTOR_FLAG_LABELS.get(agg.rotector_flag_type, "Unknown")
        conf = agg.rotector_confidence or 0
        rotector_line = f"\nRotector: {flag} · Confidence: `{conf:.1f}%`"

    header = f"## {name}\n{uid_line}\nLast Seen: `{last_seen}`{rotector_line}"
    badges = _score_badges(agg.tase_score_breakdown)
    if badges: header += f"\n\n{badges}"

    head_comp = c_section(header, avatar) if avatar else c_text(header)
    inner = [head_comp, c_sep()]

    if total:
        status = f"Flagged: {'Yes' if agg.sources_flagged else 'No'} · Condo Records: `{total}`"
        if extra and agg.sources_flagged:
            status += f"\nFlagged by: {', '.join(agg.sources_flagged)}"
        if agg.tase_score is not None: status += f" · TASE: `{agg.tase_score}`"
        inner.append(c_text(status))
        inner.append(c_sep())
        lines = []
        for s in page_data:
            line = _server_line(s, extra)
            if s.get("last_seen"): line += f"\n  ↳ Last: `{format_last_seen(s['last_seen'])}`"
            lines.append(line)
        body = "\n".join(lines) + f"\n\n-# Page {page+1}/{total_pages} · Servers: {total}"
        inner.append(c_text(body))
    else:
        inner.append(c_text("The user is not flagged."))
    return c_container(*inner)


def build_lookup_accounts(user, agg: AggregateResult) -> Optional[dict]:
    name     = _display_name(user, agg)
    accounts = [f"## Accounts — {name}", ""]

    roblox_ids = list({*agg.rw_roblox_ids, *agg.ew_roblox_ids})
    if roblox_ids:
        accounts.append("**Linked Roblox IDs (RW/EW)**")
        for rid in roblox_ids:
            accounts.append(f"• `{rid}`")
        accounts.append("")

    if agg.rotector_connections:
        accounts.append("**Linked Roblox Accounts**")
        for conn in agg.rotector_connections:
            u   = conn.get('robloxUsername', '?')
            uid = conn.get('robloxUserId', '?')
            accounts.append(f"• {u} (`{uid}`)")
            detected = conn.get('detectedAt')
            if detected:
                d_str = str(detected)[:10] if isinstance(detected, (int, str)) else detected
                accounts.append(f"  ↳ Detected: {d_str}")
            updated = conn.get('updatedAt')
            if updated:
                u_str = str(updated)[:10] if isinstance(updated, (int, str)) else updated
                accounts.append(f"  ↳ Updated: {u_str}")
        accounts.append("")
    if agg.rotector_alt_accounts:
        accounts.append("**Roblox Alt Accounts**")
        for alt in agg.rotector_alt_accounts:
            u   = alt.get('robloxUsername', '?')
            uid = alt.get('robloxUserId', '?')
            accounts.append(f"• {u} (`{uid}`)")
            detected = alt.get('detectedAt')
            if detected:
                d_str = str(detected)[:10] if isinstance(detected, (int, str)) else detected
                accounts.append(f"  ↳ Detected: {d_str}")
            updated = alt.get('updatedAt')
            if updated:
                u_str = str(updated)[:10] if isinstance(updated, (int, str)) else updated
                accounts.append(f"  ↳ Updated: {u_str}")
        accounts.append("")
    if len(accounts) <= 2:
        return None
    body = "\n".join(accounts).strip()
    return c_container(c_text(body))


def build_lookup_exploit(user, agg: AggregateResult, extra: bool = False) -> dict:
    exploits = correlate_exploit_servers(agg)
    exploits = _merge_selfbot_into_exploits(exploits, agg)
    total    = len(exploits)
    if total:
        sources = sorted({src for s in exploits for src in s.get("sources", [])})
        head    = f"## Detected in {' / '.join(sources)}:"
        if agg.ew_flagged:
            head += f"\n-# ExploitWatcher: {agg.ew_exploit_count} server(s) · Score: {agg.ew_total_score}"
        lines   = [_server_line(s, extra) for s in exploits]
        note    = f"\n\n-# Data is a snapshot, not live.\n-# Page 1/1 · Servers: {total}"
        inner   = [c_text(head), c_sep(), c_text("\n".join(lines) + note)]
    else:
        inner = [c_text("## Exploiting Records"), c_sep(),
                 c_text("This user has not been flagged for exploiting.")]
    return c_container(*inner)
