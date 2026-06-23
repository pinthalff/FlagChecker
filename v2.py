"""FlagChecker — Discord Components V2 (no left border)."""
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
    line = f"• **{s['name']}**"
    if s.get("id"):      line += f" (`{s['id']}`)"
    if extra and s.get("sources"): line += f" — `{', '.join(s['sources'])}`"
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


def build_check_overview(user, agg: AggregateResult, extra: bool = False) -> dict:
    condos   = correlate_condo_servers(agg)
    exploits = correlate_exploit_servers(agg)

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
    total       = len(exploits)
    total_pages = max(1, math.ceil(total / PAGE_SIZE_EXPLOITS))
    page_data   = exploits[page * PAGE_SIZE_EXPLOITS:(page + 1) * PAGE_SIZE_EXPLOITS]
    header      = f"Total Records: `{total}`"
    if page_data:
        lines = [_server_line(s, extra) for s in page_data]
        body  = "\n\n".join(lines) + f"\n\n-# Page {page+1}/{total_pages} · Servers: {total}"
        inner = [c_text(header), c_sep(), c_text(body)]
    else:
        inner = [c_text(header), c_sep(), c_text("No exploit records detected.")]
    return c_container(*inner)


def build_check_accounts(agg: AggregateResult) -> dict:
    accounts = []
    if agg.rotector_connections:
        accounts.append("**Linked Roblox Accounts**")
        for conn in agg.rotector_connections:
            u = conn.get('robloxUsername', '?')
            uid = conn.get('robloxUserId', '?')
            accounts.append(f"• {u} (`{uid}`)")
            detected = conn.get('detectedAt')
            if detected: accounts.append(f"  ↳ Detected: {detected[:10]}")
    if agg.rotector_alt_accounts:
        if accounts: accounts.append("")
        accounts.append("**Roblox Alt Accounts**")
        for alt in agg.rotector_alt_accounts:
            u = alt.get('robloxUsername', '?')
            uid = alt.get('robloxUserId', '?')
            accounts.append(f"• {u} (`{uid}`)")
            detected = alt.get('detectedAt')
            if detected: accounts.append(f"  ↳ Detected: {detected[:10]}")
    if not accounts:
        return c_container(c_text("No linked accounts."))
    body = "\n".join(accounts)
    return c_container(c_text("## Accounts"), c_sep(), c_text(body))


def build_check_profile(agg: AggregateResult) -> dict:
    profile = []
    if agg.rotector_flagged_friends:
        profile.append("**Flagged Friends**")
        for f in agg.rotector_flagged_friends:
            profile.append(f"• {f.get('name', '?')} (`{f.get('id', '?')}`)")
        profile.append("")
    if agg.rotector_flagged_groups:
        profile.append("**Flagged Groups**")
        for g in agg.rotector_flagged_groups:
            gline = f"• {g.get('name', '?')} (`{g.get('id', '?')}`)"
            if g.get("type"): gline += f" — {g['type']}"
            profile.append(gline)
        profile.append("")
    if agg.moco_groups:
        profile.append("**Moco-co Groups**")
        for g in agg.moco_groups:
            gline = f"• {g.get('name', '?')} (`{g.get('id', '?')}`)"
            if g.get("type"): gline += f" — {g['type']}"
            profile.append(gline)
        profile.append("")
    if agg.rotector_reasons or agg.rotector_flag_type is not None:
        profile.append("**Violation Details**")
        if agg.rotector_flag_type is not None:
            flag = config.ROTECTOR_FLAG_LABELS.get(agg.rotector_flag_type, "Unknown")
            conf = agg.rotector_confidence or 0
            profile.append(f"Flag: `{flag}` · Confidence: `{conf:.1f}%`")
        if agg.rotector_reasons:
            profile.append("Reasons:")
            for r in agg.rotector_reasons:
                profile.append(f"  • {r}")
        profile.append("")
    if agg.rotector_alt_accounts:
        profile.append("**Alternate Accounts**")
        for alt in agg.rotector_alt_accounts:
            profile.append(f"• {alt.get('robloxUsername', '?')} (`{alt.get('robloxUserId', '?')}`)")
        profile.append("")
    if not profile:
        return c_container(c_text("No profile data detected."))
    body = "\n".join(profile).strip()
    return c_container(c_text("## Profile"), c_sep(), c_text(body))


def build_check_details(agg: AggregateResult) -> dict:
    lines = []

    if agg.rotector_flag_type is not None:
        flag = config.ROTECTOR_FLAG_LABELS.get(agg.rotector_flag_type, "Unknown")
        conf = agg.rotector_confidence or 0
        lines.append("**Rotector (Roblox)**")
        lines.append(f"Flag Type: `{flag}`")
        lines.append(f"Confidence: `{conf:.1f}%`")
        if agg.rotector_is_locked:
            lines.append("Status: 🔒 Locked")
        if agg.rotector_reasons:
            lines.append("Reasons:")
            for r in agg.rotector_reasons:
                lines.append(f"  • {r}")
        lines.append("")

    if agg.rotector_discord_servers:
        lines.append("**Rotector (Discord)**")
        lines.append(f"Tracked Servers: `{len(agg.rotector_discord_servers)}`")
        for s in agg.rotector_discord_servers:
            sname = s.get("serverName") or s.get("name") or "Unknown"
            sid   = s.get("serverId") or s.get("id") or ""
            tase  = " · `TASE`" if s.get("isTase") else ""
            lines.append(f"  • **{sname}**" + (f" (`{sid}`)" if sid else "") + tase)
        if agg.rotector_connections:
            lines.append(f"Linked Roblox Accounts: `{len(agg.rotector_connections)}`")
            for conn in agg.rotector_connections:
                lines.append(f"  • {conn.get('robloxUsername', '?')} (`{conn.get('robloxUserId', '?')}`)")
        if agg.rotector_alt_accounts:
            lines.append(f"Roblox Alt Accounts: `{len(agg.rotector_alt_accounts)}`")
            for alt in agg.rotector_alt_accounts:
                lines.append(f"  • {alt.get('robloxUsername', '?')} (`{alt.get('robloxUserId', '?')}`)")
        lines.append("")

    if agg.tase_score is not None and agg.tase_score > 0:
        lines.append(f"**TASE**")
        lines.append(f"Score: `{agg.tase_score}`")
        if agg.tase_score_breakdown:
            for k, v in agg.tase_score_breakdown.items():
                if v:
                    sign = "+" if v >= 0 else ""
                    lines.append(f"  • {k.replace('_', ' ').title()}: `{sign}{v}`")
        lines.append("")

    if agg.bloxycleaner_flagged:
        lines.append(f"**BloxyCleaner (ERP)**")
        lines.append(f"Flagged: Yes")
        if agg.bloxycleaner_servers:
            lines.append(f"Servers: `{len(agg.bloxycleaner_servers)}`")
        lines.append("")

    if agg.bloxycleaner_exploit_flagged:
        lines.append(f"**BloxyCleaner (Exploit)**")
        lines.append(f"Flagged: Yes")
        if agg.bloxycleaner_exploit_servers:
            lines.append(f"Servers: `{len(agg.bloxycleaner_exploit_servers)}`")
        lines.append("")

    if agg.rocleaner_flagged:
        lines.append(f"**RoCleaner**")
        lines.append(f"Found in imported database.")
        if agg.rocleaner_servers:
            lines.append(f"Servers: `{len(agg.rocleaner_servers)}`")
        lines.append("")

    if agg.moco_group_count:
        lines.append(f"**Moco-co**")
        lines.append(f"Flagged Groups: `{agg.moco_group_count}`")
        if agg.moco_group_types:
            lines.append(f"Group Types: `{', '.join(agg.moco_group_types)}`")
        if agg.moco_groups:
            for g in agg.moco_groups:
                gline = f"  • **{g.get('name', 'Unknown')}**"
                if g.get("id"): gline += f" (`{g['id']}`)"
                if g.get("type"): gline += f" — {g['type']}"
                lines.append(gline)
        lines.append("")

    if not lines:
        return c_container(c_text("## Violation Details"), c_sep(),
                           c_text("No violations detected."))

    body = "\n".join(lines).strip()
    return c_container(c_text("## Violation Details"), c_sep(), c_text(body))


def build_check_friends(agg: AggregateResult) -> dict:
    friends = agg.rotector_flagged_friends
    header  = f"Flagged Friends: `{len(friends)}`"
    if friends:
        lines = [f"• **{f.get('name', 'Unknown')}** (`{f.get('id', '?')}`)" for f in friends]
        inner = [c_text(header), c_sep(), c_text("\n".join(lines))]
    else:
        inner = [c_text(header), c_sep(), c_text("No flagged friends detected.")]
    return c_container(*inner)


def build_check_groups(agg: AggregateResult) -> dict:
    groups = (agg.rotector_flagged_groups or []) + (agg.moco_groups or [])
    total  = len(groups) or agg.moco_group_count or 0
    header = f"Flagged Groups: `{total}`"
    if groups:
        lines = []
        for g in groups:
            line = f"• **{g.get('name', 'Unknown')}** (`{g.get('id', '?')}`)"
            if g.get("type"): line += f" — {g['type']}"
            lines.append(line)
        inner = [c_text(header), c_sep(), c_text("\n".join(lines))]
    elif agg.moco_group_types:
        inner = [c_text(header), c_sep(),
                 c_text(f"Group types: `{', '.join(agg.moco_group_types)}`")]
    else:
        inner = [c_text(header), c_sep(), c_text("No flagged groups detected.")]
    return c_container(*inner)


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
    name = _display_name(user, agg)
    accounts = [f"## Accounts — {name}", ""]
    if agg.rotector_connections:
        accounts.append("**Linked Roblox Accounts**")
        for conn in agg.rotector_connections:
            u = conn.get('robloxUsername', '?')
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
            u = alt.get('robloxUsername', '?')
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


def build_lookup_profile(user, agg: AggregateResult) -> Optional[dict]:
    name = _display_name(user, agg)
    profile = [f"## Profile — {name}", ""]
    if agg.rotector_flagged_friends:
        profile.append("**Flagged Friends**")
        for f in agg.rotector_flagged_friends:
            profile.append(f"• {f.get('name', '?')} (`{f.get('id', '?')}`)")
        profile.append("")
    if agg.rotector_flagged_groups:
        profile.append("**Flagged Groups**")
        for g in agg.rotector_flagged_groups:
            gline = f"• {g.get('name', '?')} (`{g.get('id', '?')}`)"
            if g.get("type"): gline += f" — {g['type']}"
            profile.append(gline)
        profile.append("")
    if agg.moco_groups:
        profile.append("**Moco-co Groups**")
        for g in agg.moco_groups:
            gline = f"• {g.get('name', '?')} (`{g.get('id', '?')}`)"
            if g.get("type"): gline += f" — {g['type']}"
            profile.append(gline)
        profile.append("")
    if agg.rotector_reasons or agg.rotector_flag_type is not None:
        profile.append("**Violation Details**")
        if agg.rotector_flag_type is not None:
            flag = config.ROTECTOR_FLAG_LABELS.get(agg.rotector_flag_type, "Unknown")
            conf = agg.rotector_confidence or 0
            profile.append(f"Flag: `{flag}` · Confidence: `{conf:.1f}%`")
        if agg.rotector_reasons:
            profile.append("Reasons:")
            for r in agg.rotector_reasons:
                profile.append(f"  • {r}")
        profile.append("")
    if agg.rotector_alt_accounts:
        profile.append("**Alternate Accounts**")
        for alt in agg.rotector_alt_accounts:
            username = alt.get('robloxUsername', '?')
            userid = alt.get('robloxUserId', '?')
            profile.append(f"• {username} (`{userid}`)")
        profile.append("")
    if len(profile) <= 2:
        return None
    body = "\n".join(profile).strip()
    return c_container(c_text(body))


def build_lookup_exploit(user, agg: AggregateResult, extra: bool = False) -> dict:
    exploits = correlate_exploit_servers(agg)
    total    = len(exploits)
    if total:
        sources = sorted({src for s in exploits for src in s.get("sources", [])})
        head  = f"## Detected in {' / '.join(sources)}:"
        lines = [_server_line(s, extra) for s in exploits]
        note  = (f"\n\n-# Data is a snapshot, not live.\n"
                 f"-# Page 1/1 · Servers: {total}")
        inner = [c_text(head), c_sep(), c_text("\n".join(lines) + note)]
    else:
        inner = [c_text("## Exploiting Records"), c_sep(),
                 c_text("This user has not been flagged for exploiting.")]
    return c_container(*inner)


def build_lookup_violation(user, agg: AggregateResult) -> dict:
    name = _display_name(user, agg)
    lines = [f"## Violation Details — {name}", ""]

    if agg.rotector_flag_type is not None:
        flag = config.ROTECTOR_FLAG_LABELS.get(agg.rotector_flag_type, "Unknown")
        conf = agg.rotector_confidence or 0
        lines.append("**Rotector (Roblox)**")
        lines.append(f"Flag Type: `{flag}`")
        lines.append(f"Confidence: `{conf:.1f}%`")
        if agg.rotector_reasons:
            lines.append("Reasons:")
            for r in agg.rotector_reasons:
                lines.append(f"  • {r}")
        lines.append("")

    if agg.tase_score is not None and agg.tase_score > 0:
        lines.append("**TASE**")
        lines.append(f"Score: `{agg.tase_score}`")
        if agg.tase_score_breakdown:
            for k, v in agg.tase_score_breakdown.items():
                if v:
                    sign = "+" if v >= 0 else ""
                    lines.append(f"  • {k.replace('_', ' ').title()}: `{sign}{v}`")
        lines.append("")

    if agg.bloxycleaner_flagged:
        lines.append("**BloxyCleaner (ERP)**")
        lines.append("Flagged: Yes")
        if agg.bloxycleaner_servers:
            lines.append(f"Servers: `{len(agg.bloxycleaner_servers)}`")
        lines.append("")

    if agg.bloxycleaner_exploit_flagged:
        lines.append("**BloxyCleaner (Exploit)**")
        lines.append("Flagged: Yes")
        if agg.bloxycleaner_exploit_servers:
            lines.append(f"Servers: `{len(agg.bloxycleaner_exploit_servers)}`")
        lines.append("")

    if agg.rocleaner_flagged:
        lines.append("**RoCleaner**")
        lines.append("Found in imported database.")
        if agg.rocleaner_servers:
            lines.append(f"Servers: `{len(agg.rocleaner_servers)}`")
        lines.append("")

    if agg.moco_group_count:
        lines.append("**Moco-co**")
        lines.append(f"Flagged Groups: `{agg.moco_group_count}`")
        if agg.moco_group_types:
            lines.append(f"Group Types: `{', '.join(agg.moco_group_types)}`")
        if agg.moco_groups:
            for g in agg.moco_groups:
                gline = f"  • **{g.get('name', 'Unknown')}**"
                if g.get("id"): gline += f" (`{g['id']}`)"
                if g.get("type"): gline += f" — {g['type']}"
                lines.append(gline)
        lines.append("")

    if len(lines) <= 2:
        lines.append("No violations detected.")

    body = "\n".join(lines).strip()
    return c_container(c_text(body))


def build_lookup_friends(user, agg: AggregateResult) -> Optional[dict]:
    friends = agg.rotector_flagged_friends
    if not friends: return None
    name  = _display_name(user, agg)
    head  = f"## Flagged Friends — {name}\nTotal: `{len(friends)}`"
    lines = [f"• **{f.get('name', 'Unknown')}** (`{f.get('id', '?')}`)" for f in friends]
    return c_container(c_text(head), c_sep(), c_text("\n".join(lines)))


def build_lookup_groups(user, agg: AggregateResult) -> Optional[dict]:
    groups = (agg.rotector_flagged_groups or []) + (agg.moco_groups or [])
    total  = len(groups) or agg.moco_group_count or 0
    if not total: return None
    name  = _display_name(user, agg)
    head  = f"## Flagged Groups — {name}\nTotal: `{total}`"
    if groups:
        lines = []
        for g in groups:
            line = f"• **{g.get('name', 'Unknown')}** (`{g.get('id', '?')}`)"
            if g.get("type"): line += f" — {g['type']}"
            lines.append(line)
        body = "\n".join(lines)
    else:
        body = f"Group types: `{', '.join(agg.moco_group_types)}`"
    return c_container(c_text(head), c_sep(), c_text(body))
