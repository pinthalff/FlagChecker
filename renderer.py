from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

import config
from models import AggregateResult

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


# ── Time helpers ──────────────────────────────────────────────────────────────

def _to_unix(value) -> Optional[int]:
    try: return int(float(value))
    except (TypeError, ValueError): pass
    try:
        s  = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (TypeError, ValueError): return None

def to_card_date(value) -> str:
    if not value: return "n/a"
    ts = _to_unix(value)
    if ts is None: return str(value)
    diff = datetime.now(timezone.utc).timestamp() - ts
    if diff < 60:        return "just now"
    if diff < 3600:      return f"{int(diff/60)}m ago"
    if diff < 86400:     return f"{int(diff/3600)}h ago"
    if diff < 604800:    return f"{int(diff/86400)}d ago"
    if diff < 2592000:   return f"{int(diff/604800)}wk ago"
    if diff < 31536000:  return f"{int(diff/2592000)}mo ago"
    return f"{int(diff/31536000)}yr ago"


# ── Card context builders (feed into Jinja2 templates) ────────────────────────

def userlookup_context(member, agg: AggregateResult) -> dict:
    badges = []
    if agg.tase_score_breakdown:
        for k, (label, _) in config.SCORE_BADGE_MAP.items():
            if agg.tase_score_breakdown.get(k, 0) > 0:
                badges.append(label)
    if not badges and agg.sources_flagged:
        badges = [b[0] for b in config.FALLBACK_BADGES]
    return {
        "member_name": str(member), "member_id": member.id,
        "avatar_url": str(member.display_avatar.url),
        "score": agg.tase_score or 0, "badges": badges,
        "tase_guilds": agg.tase_guilds[:6],
        "tase_guilds_count": agg.tase_guilds_count,
        "rw_condo_count": agg.rw_condo_count,
        "rw_exploit_count": agg.rw_exploit_count,
        "sources_flagged": agg.sources_flagged,
        "divider": config.DIVIDER,
    }

def search_condo_context(agg: AggregateResult) -> dict:
    return {"roblox_id": agg.roblox_id, "servers": agg.rw_condo_servers[:6],
            "total": agg.rw_condo_count, "divider": config.DIVIDER}

def search_exploit_context(agg: AggregateResult) -> dict:
    return {"roblox_id": agg.roblox_id, "servers": agg.rw_exploit_servers[:6],
            "total": agg.rw_exploit_count, "divider": config.DIVIDER}

def robloxsearch_context(agg: AggregateResult) -> dict:
    return {
        "roblox_id": agg.roblox_id,
        "flag_label": config.ROTECTOR_FLAG_LABELS.get(agg.rotector_flag_type or 0, "Unknown"),
        "confidence": agg.rotector_confidence or 0,
        "reasons": agg.rotector_reasons[:5],
        "moco_group_count": agg.moco_group_count or 0,
        "moco_group_types": agg.moco_group_types[:5],
        "divider": config.DIVIDER,
    }


# ── CardRenderer ──────────────────────────────────────────────────────────────

class CardRenderer:
    def __init__(self) -> None:
        self._pw      = None
        self._browser = None
        self._jinja   = Environment(
            loader=FileSystemLoader(Path(__file__).parent / "template"),
            autoescape=True,
        )

    async def _ensure_started(self) -> None:
        if not PLAYWRIGHT_AVAILABLE:
            logging.warning("Playwright not available — cards will not render.")
            return
        if self._browser and self._browser.is_connected():
            return
        self._pw      = await async_playwright().start()
        self._browser = await self._pw.chromium.launch()
        logging.info("Playwright Chromium launched — cards will render as images.")

    async def render(self, template_name: str, context: dict) -> Optional[bytes]:
        if not self._browser:
            return None
        try:
            html = self._jinja.get_template(template_name).render(**context)
            page = await self._browser.new_page(viewport={"width": 480, "height": 1})
            await page.set_content(html, wait_until="networkidle")
            body = await page.query_selector("body")
            img  = await body.screenshot(type="png")
            await page.close()
            return img
        except Exception as exc:
            logging.error("Render error (%s): %s", template_name, exc)
            return None

    async def render_many(self, jobs: list) -> list:
        return await asyncio.gather(*(self.render(t, c) for t, c in jobs))

    async def close(self) -> None:
        if self._browser: await self._browser.close()
        if self._pw:      await self._pw.stop()


# ── Card context builders for /lookup ─────────────────────────────────────────

TASE_BADGE_ICONS = {
    "booster": "💎", "staff": "🔨", "messages": "💬",
    "typing": "⌨️", "reactions": "⚡", "nsfw_content": "🔞",
    "exploiting": "💥", "scam": "⚠️", "spam": "📢",
}


def lookup_card_context(user, agg: AggregateResult) -> dict:
    from detection import correlate_condo_servers, format_last_seen

    condos = correlate_condo_servers(agg)

    badges = []
    for key, val in (agg.tase_score_breakdown or {}).items():
        if not val: continue
        emoji = TASE_BADGE_ICONS.get(key, "📊")
        label = key.replace("_", " ").title()
        sign  = "+" if val >= 0 else ""
        badges.append({"emoji": emoji, "label": label, "value": f"{sign}{val}"})

    timestamps = [s["last_seen"] for s in condos if s.get("last_seen")]
    last_seen  = format_last_seen(max(timestamps)) if timestamps else "n/a"

    condo_list = []
    for s in condos[:8]:
        condo_list.append({
            "name":       s["name"],
            "sources":    ", ".join(s["sources"]),
            "first_seen": "—",
            "last_seen":  format_last_seen(s["last_seen"]) if s.get("last_seen") else "—",
        })

    return {
        "title":         str(user) if user else f"User {agg.discord_id or agg.roblox_id}",
        "mention":       str(user) if user else str(agg.discord_id or agg.roblox_id),
        "user_id":       str(user.id if user else (agg.discord_id or agg.roblox_id)),
        "last_seen":     last_seen,
        "roblox":        agg.roblox_id or "",
        "avatar_url":    str(user.display_avatar.url) if user and user.display_avatar else "",
        "badges":        badges,
        "condo_servers": condo_list,
        "detected_by":   agg.sources_flagged,
        "exploit_servers": [],
        "total_pages":   1,
        "page":          1,
    }


def exploit_card_context(agg: AggregateResult) -> dict:
    from detection import correlate_exploit_servers

    exploits = correlate_exploit_servers(agg)
    return {
        "total_exploit":   len(exploits),
        "first_detected":  "—",
        "most_recent":     "—",
        "exploit_servers": [
            {
                "name":       s["name"],
                "sources":    "RobloxWatcher / ExploitWatcher",
                "first_seen": "—",
                "last_seen":  "—",
            }
            for s in exploits[:10]
        ],
        "total_pages": 1,
        "page":        1,
    }
