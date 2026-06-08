"""Discord Components V2 — no left border, no section emojis."""
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


# ── Component primitives ──────────────────────────────────────────────────────

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


# ── HTTP helpers ──────────────────────────────────────────────────────────────

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
    interaction.response._responded = True  # type: ignore


# ── Score badge formatting (image-2 style, two rows) ─────────────────────────

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


# ── /check sections ───────────────────────────────────────────────────────────

def build_check_overview(user, agg: AggregateResult, extra: bool = False) -> dict:
    condos   = correlate_condo_servers(agg)
    exploits = correlate_exploit_servers(agg)

    name    = str(user) if user else f"User {agg.discord_id or agg.roblox_id}"
    mention = f"<@{user.id}>" if user else "Unknown"
    uid     = user.id if user else (agg.discord_id or agg.roblox_id)
    avatar  = str(user.display_avatar.url) if user and user.display_avatar else None

    header  = f"## {name}\nDiscord: `{uid}`\nUser: {mention}"

    stats   = f"Total Records: `{len(condos) + len(exploits)}`\n"
    stats  += f"Condo Records: `{len(condos)}`\n"
    stats  += f"Exploit Records: `{len(exploits)}`\n"
    stats  += f"\nFlagged By: {', '.join(agg.sources_flagged) if agg.sources_flagged else '`None`'}"
    if agg.tase_score is not None:
        stats += f"\nTASE Score: `{agg.tase_score}`"
    if agg.rotector_flag_type:
        flag = config.ROTECTOR_FLAG_LABELS.get(agg.rotector_flag_type, "Unknown")
        conf = agg.rotector_confidence or 0
        stats += f"\nRotector: {flag} · `{conf:.1f}%`"
    if agg.moco_group_count:
        stats += f"\nMoco-co Groups: `{agg.moco_group_count}`"
    if extra and agg.sources_checked:
        stats += f"\nAPIs Checked: `{', '.join(agg.sources_checked)}`"

    head_comp = c_section(header, avatar) if avatar else c_text(header)
    inner = [head_comp, c_sep(), c_text(stats)]
    badges = _score_badges(agg.tase_score_breakdown)
    if badges:
        inner += [c_sep(), c_text(badges)]
    return c_container(*inner)


def build_check_condos(agg: AggregateResult, extra: bool = False, page: int = 0) -> dict:
    condos      = correlate_condo_servers(agg)
    total       = len(condos)
    total_pages = max(1, math.ceil(total / PAGE_SIZE_CONDOS))
    page_data   = condos[page * PAGE_SIZE_CONDOS:(page + 1) * PAGE_SIZE_CONDOS]

    timestamps = [s["last_seen"] for s in condos if s.get("last_seen")]
    header  = f"First Seen: `{format_last_seen(min(timestamps)) if timestamps else 'n/a'}`"
    header += f" · Last Seen: `{format_last_seen(max(timestamps)) if timestamps else 'n/a'}`\n"
    header += f"Total Records: `{total}`"

    if page_data:
        lines = []
        for s in page_data:
            line = _server_line(s, extra)
            if s.get("last_seen"): line += f"\n  ↳ Last seen: `{format_last_seen(s['last_seen'])}`"
            lines.append(line)
        body = "\n\n".join(lines) + f"\n\n-# Page {page+1}/{total_pages} · Servers: {total}"
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


def build_check_friends(agg: AggregateResult) -> dict:
    friends = agg.rotector_flagged_friends
    header  = f"Flagged Friends: `{len(friends)}`"
    if friends:
        lines = [f"• **{f.get('name', 'Unknown')}** (`{f.get('id', '?')}`)" for f in friends[:15]]
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
        for g in groups[:15]:
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


def build_database_section(user_id: str, storage, is_admin: bool) -> dict:
    if not is_admin:
        return c_container(c_text("This section is admin only."))
    rec = storage.get_flagged_user(user_id)
    if rec:
        sources  = ", ".join(rec.get("sources", [])) or "Unknown"
        username = rec.get("username", "Unknown")
        added    = rec.get("added_at", "?")[:10]
        servers  = rec.get("servers", [])
        head  = f"## Database Record\nUser: **{username}**\nStatus: Flagged\n"
        head += f"Flagged by: `{sources}`\nAdded: `{added}`"
        if servers:
            lines = [f"• **{s['name']}**" + (f" — `{', '.join(s['sources'])}`" if s.get("sources") else "")
                     for s in servers[:8]]
            inner = [c_text(head), c_sep(), c_text("\n".join(lines))]
        else:
            inner = [c_text(head)]
    else:
        inner = [c_text("## Database Record"), c_sep(),
                 c_text("Status: Clean — not in your database.")]
    return c_container(*inner)


# ── /lookup cards ─────────────────────────────────────────────────────────────

def build_lookup_main(user, agg: AggregateResult, extra: bool = False, page: int = 0) -> dict:
    name    = str(user) if user else f"User {agg.discord_id or agg.roblox_id}"
    mention = f"<@{user.id}>" if user else "@unknown-user"
    uid     = user.id if user else (agg.discord_id or agg.roblox_id)
    avatar  = str(user.display_avatar.url) if user and user.display_avatar else None

    condos      = correlate_condo_servers(agg)
    total       = len(condos)
    total_pages = max(1, math.ceil(total / PAGE_SIZE_CONDOS)) if total else 1
    page_data   = condos[page * PAGE_SIZE_CONDOS:(page + 1) * PAGE_SIZE_CONDOS]
    timestamps  = [s["last_seen"] for s in condos if s.get("last_seen")]
    last_seen   = format_last_seen(max(timestamps)) if timestamps else "n/a"

    header  = f"## {name}\nUser: {mention}\nUser ID: `{uid}`\nLast Seen: `{last_seen}`"
    badges  = _score_badges(agg.tase_score_breakdown)
    if badges: header += f"\n\n{badges}"

    head_comp = c_section(header, avatar) if avatar else c_text(header)
    inner = [head_comp, c_sep()]

    if total:
        flagged = ", ".join(agg.sources_flagged) if agg.sources_flagged else "—"
        status  = f"Flagged by: {flagged} · Condo Records: `{total}`"
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
        inner.append(c_text("This user has not been detected in FlagChecker databases."))
    return c_container(*inner)


def build_lookup_exploit(user, agg: AggregateResult, extra: bool = False) -> dict:
    exploits = correlate_exploit_servers(agg)
    total    = len(exploits)
    if total:
        head  = "## Detected in Roblox Watcher's database:"
        lines = [_server_line(s, extra) for s in exploits[:10]]
        note  = (f"\n\n-# Roblox Watcher's database is a snapshot, not live.\n"
                 f"-# Page 1/1 · Servers: {total}")
        inner = [c_text(head), c_sep(), c_text("\n".join(lines) + note)]
    else:
        inner = [c_text("## Exploiting Records"), c_sep(),
                 c_text("This user has not been flagged for exploiting.")]
    return c_container(*inner)


def build_lookup_friends(user, agg: AggregateResult) -> Optional[dict]:
    friends = agg.rotector_flagged_friends
    if not friends: return None
    name  = str(user) if user else f"User {agg.discord_id or agg.roblox_id}"
    head  = f"## Flagged Friends — {name}\nTotal: `{len(friends)}`"
    lines = [f"• **{f.get('name', 'Unknown')}** (`{f.get('id', '?')}`)" for f in friends[:15]]
    return c_container(c_text(head), c_sep(), c_text("\n".join(lines)))


def build_lookup_groups(user, agg: AggregateResult) -> Optional[dict]:
    groups = (agg.rotector_flagged_groups or []) + (agg.moco_groups or [])
    total  = len(groups) or agg.moco_group_count or 0
    if not total: return None
    name  = str(user) if user else f"User {agg.discord_id or agg.roblox_id}"
    head  = f"## Flagged Groups — {name}\nTotal: `{total}`"
    if groups:
        lines = []
        for g in groups[:15]:
            line = f"• **{g.get('name', 'Unknown')}** (`{g.get('id', '?')}`)"
            if g.get("type"): line += f" — {g['type']}"
            lines.append(line)
        body = "\n".join(lines)
    else:
        body = f"Group types: `{', '.join(agg.moco_group_types)}`"
    return c_container(c_text(head), c_sep(), c_text(body))
