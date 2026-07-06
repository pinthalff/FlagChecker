from __future__ import annotations
import asyncio
import json as _json
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp

import config
from models import AggregateResult

log = logging.getLogger("bot.detection")

ROTECTOR_ACTIONABLE = {1, 2}


async def _get(session, url, headers=None, params=None, timeout=10) -> dict:
    try:
        async with session.get(
            url, headers=headers or {}, params=params or {},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as r:
            if r.status == 429:
                log.warning("Rate limited (429): %s", url); return {}
            if r.status != 200:
                log.warning("API %s returned %s", url, r.status); return {}
            ct = r.headers.get("Content-Type", "")
            if "html" in ct:
                log.warning("HTML response (Cloudflare?) from %s", url); return {}
            try:
                text = await r.text()
                if text.strip().startswith("<"):
                    log.warning("Got HTML instead of JSON from %s", url); return {}
                return _json.loads(text)
            except Exception as exc:
                log.error("JSON parse error %s: %s", url, exc); return {}
    except asyncio.TimeoutError:
        log.error("Timeout: %s", url); return {}
    except Exception as exc:
        log.error("Error %s: %s", url, exc); return {}


async def _fetch_tase(session, discord_id: str) -> dict:
    return await _get(session, f"https://api.tasebot.org/v2/check/{discord_id}",
                      {"Authorization": config.TASE_API_KEY})

async def _fetch_bloxycleaner_erp(session, discord_id: str) -> dict:
    token = config.BLOXYCLEANER_API_KEY or "pub-freeusage"
    data  = await _get(session, f"{config.BLOXYCLEANER_BASE}/p/api/v1/erp/lookup",
                       {"Authorization": token}, {"userid": discord_id}, timeout=20)
    return data.get("users", {}).get(str(discord_id), {})

async def _fetch_bloxycleaner_exp(session, discord_id: str) -> dict:
    token = config.BLOXYCLEANER_API_KEY or "pub-freeusage"
    data  = await _get(session, f"{config.BLOXYCLEANER_BASE}/p/api/v1/exp/lookup",
                       {"Authorization": token}, {"userid": discord_id}, timeout=20)
    return data.get("users", {}).get(str(discord_id), {})

async def _fetch_robloxwatcher(session, user_id: str) -> dict:
    return await _get(session,
        "https://robloxwatcher.info/checker/api/check.php",
        params={"id": user_id, "key": config.ROBLOXWATCHER_API_KEY})

async def _fetch_rotector_discord(session, discord_id: str) -> dict:
    return await _get(session,
        f"{config.ROTECTOR_API_BASE}/v1/lookup/discord/user/{discord_id}",
        {"Authorization": f"Bearer {config.ROTECTOR_API_KEY}"})

async def _fetch_rotector_roblox(session, roblox_id: str) -> dict:
    return await _get(session,
        f"{config.ROTECTOR_API_BASE}/v1/lookup/roblox/user/{roblox_id}",
        {"Authorization": f"Bearer {config.ROTECTOR_API_KEY}"})

async def _fetch_rotector_roblox_discord(session, roblox_id: str) -> dict:
    return await _get(session,
        f"{config.ROTECTOR_API_BASE}/v1/lookup/roblox/user/{roblox_id}/discord",
        {"Authorization": f"Bearer {config.ROTECTOR_API_KEY}"})

async def _fetch_moco(session, user_id: str) -> dict:
    return await _get(session,
        f"https://api.moco-co.org/v2/checkuser/{user_id}",
        {"Authorization": config.MOCO_API_KEY})

async def _fetch_roblox_username(session, user_id: str) -> Optional[str]:
    data = await _get(session, f"https://users.roblox.com/v1/users/{user_id}")
    return data.get("name") or data.get("displayName")

# ─────────────────────────────────────────────
# Selfbot bridge — POST /check on the selfbot's HTTP API
# ─────────────────────────────────────────────

async def _fetch_selfbot(session, discord_id: str) -> dict:
    """
    Queries the selfbot's /check endpoint.
    Returns the full guild report or {} on any failure.
    Config keys needed:
        SELFBOT_API_URL     — e.g. https://self-bot-production-adc8.up.railway.app
        SELFBOT_API_KEY     — shared INTERNAL_API_KEY set in the selfbot Railway service
    """
    url = getattr(config, "SELFBOT_API_URL", "") or ""
    key = getattr(config, "SELFBOT_API_KEY", "") or ""
    if not url or not key:
        return {}
    try:
        async with session.post(
            f"{url.rstrip('/')}/check",
            json={"api_key": key, "user_id": int(discord_id)},
            timeout=aiohttp.ClientTimeout(total=180, connect=15, sock_read=120),
        ) as r:
            if r.status == 200:
                return await r.json()
            if r.status == 401:
                log.warning("[Selfbot] API key rejected")
            else:
                log.warning("[Selfbot] HTTP %s", r.status)
            return {}
    except asyncio.TimeoutError:
        log.warning("[Selfbot] Timed out for user %s", discord_id)
        return {}
    except Exception as exc:
        log.error("[Selfbot] Error: %s", exc)
        return {}


def _safe_ts(val) -> Optional[int]:
    if val is None: return None
    try: return int(val)
    except (TypeError, ValueError): return None


def _parse_rotector_reasons(reasons_raw) -> list[str]:
    if not reasons_raw or not isinstance(reasons_raw, dict):
        return []
    lines = []
    for key, val in reasons_raw.items():
        if isinstance(val, dict):
            msg  = val.get("message", "")
            conf = val.get("confidence")
            line = f"{key}"
            if msg:  line += f": {msg}"
            if conf is not None: line += f" ({conf:.0%})"
            lines.append(line)
        else:
            lines.append(str(key))
    return lines


def _extract_groups_from_reasons(reasons_raw) -> list[dict]:
    if not reasons_raw or not isinstance(reasons_raw, dict):
        return []
    groups = []
    for key, val in reasons_raw.items():
        if "group" not in key.lower(): continue
        if isinstance(val, dict):
            for ev in (val.get("evidence") or []):
                groups.append({"name": str(ev), "id": None})
            if not groups:
                msg = val.get("message", "")
                if msg: groups.append({"name": f"{key}: {msg[:80]}", "id": None})
        elif isinstance(val, str) and val:
            groups.append({"name": f"{key}: {val[:80]}", "id": None})
    return groups


def _merge_server(by_key: dict, name_index: dict, server: dict, source: str) -> None:
    if not server: return
    sid   = server.get("id") or server.get("serverId")
    name  = server.get("name") or server.get("serverName") or "Unknown"
    nlow  = name.lower()
    key   = str(sid) if sid else name_index.get(nlow, nlow)
    entry = by_key.setdefault(key, {"id": sid, "name": name, "sources": [], "last_seen": None})
    if sid and entry.get("id") is None:
        entry["id"] = sid
    name_index.setdefault(nlow, key)
    if source not in entry["sources"]: entry["sources"].append(source)
    ts = _safe_ts(server.get("lastSeen") or server.get("updatedAt") or server.get("firstSeenAt"))
    if ts is not None and (entry["last_seen"] is None or ts > entry["last_seen"]):
        entry["last_seen"] = ts


def correlate_condo_servers(agg: AggregateResult) -> list[dict]:
    by_key: dict     = {}
    name_index: dict = {}
    for s in agg.tase_guilds:              _merge_server(by_key, name_index, s, "TASE")
    for s in agg.rw_condo_servers:         _merge_server(by_key, name_index, s, "RobloxWatcher")
    for s in agg.bloxycleaner_servers:     _merge_server(by_key, name_index, s, "BloxyCleaner")
    for s in agg.rocleaner_servers:        _merge_server(by_key, name_index, s, "RoCleaner")
    for s in agg.rotector_discord_servers: _merge_server(by_key, name_index, s, "Rotector")
    return sorted(by_key.values(), key=lambda x: x["last_seen"] or 0, reverse=True)


def correlate_exploit_servers(agg: AggregateResult) -> list[dict]:
    by_key: dict     = {}
    name_index: dict = {}
    for s in agg.rw_exploit_servers:           _merge_server(by_key, name_index, s, "RobloxWatcher")
    for s in agg.bloxycleaner_exploit_servers: _merge_server(by_key, name_index, s, "BloxyCleaner")
    return sorted(by_key.values(), key=lambda x: x["last_seen"] or 0, reverse=True)


def format_last_seen(ts: Optional[int]) -> str:
    if not ts: return "—"
    try:
        dt   = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        h12  = dt.hour % 12 or 12
        ampm = "AM" if dt.hour < 12 else "PM"
        return f"{h12}:{dt.minute:02d}:{dt.second:02d} {ampm} {dt.month:02d}/{dt.day:02d}/{dt.year % 100:02d}"
    except Exception: return "—"


class DetectionService:
    def __init__(self, storage=None) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        self._storage = storage

    def _sess(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def lookup(self, user_id: str, roblox_only: bool = False, disabled_apis: set = None) -> AggregateResult:
        sess    = self._sess()
        errors  = []
        checked = []

        if disabled_apis is None:
            cfg = getattr(config, "DISABLED_APIS", []) or []
            if isinstance(cfg, str):
                cfg = [s.strip() for s in cfg.split(",") if s.strip()]
            disabled_apis = {str(s).upper() for s in cfg}

        if roblox_only:
            agg  = AggregateResult(discord_id="", roblox_id=int(user_id))
            jobs = []
            jobs.append(("roblox_username", _fetch_roblox_username(sess, user_id)))
            if "ROTECTOR" not in disabled_apis:
                checked.append("Rotector")
                jobs.append(("rotector_roblox", _fetch_rotector_roblox(sess, user_id)))
                jobs.append(("rotector_roblox_discord", _fetch_rotector_roblox_discord(sess, user_id)))
            if "MOCO" not in disabled_apis:
                checked.append("Moco-co")
                jobs.append(("moco", _fetch_moco(sess, user_id)))
        else:
            agg  = AggregateResult(discord_id=user_id)
            jobs = []
            if "TASE" not in disabled_apis:
                checked.append("TASE")
                jobs.append(("tase", _fetch_tase(sess, user_id)))
            if "BLOXYCLEANER" not in disabled_apis:
                checked.append("BloxyCleaner")
                jobs.append(("bc_erp", _fetch_bloxycleaner_erp(sess, user_id)))
                jobs.append(("bc_exp", _fetch_bloxycleaner_exp(sess, user_id)))
            if "ROBLOXWATCHER" not in disabled_apis:
                checked.append("RobloxWatcher")
                jobs.append(("rw", _fetch_robloxwatcher(sess, user_id)))
            if "ROTECTOR" not in disabled_apis:
                checked.append("Rotector")
                jobs.append(("rotector_discord", _fetch_rotector_discord(sess, user_id)))
            if "MOCO" not in disabled_apis:
                checked.append("Moco-co")
                jobs.append(("moco", _fetch_moco(sess, user_id)))
            # ── Selfbot — always runs in Discord mode if configured ──
            if "SELFBOT" not in disabled_apis:
                selfbot_url = getattr(config, "SELFBOT_API_URL", "") or ""
                selfbot_key = getattr(config, "SELFBOT_API_KEY", "") or ""
                if selfbot_url and selfbot_key:
                    checked.append("Selfbot")
                    jobs.append(("selfbot", _fetch_selfbot(sess, user_id)))

        results = await asyncio.gather(*[j[1] for j in jobs], return_exceptions=True)

        for (key, _), res in zip(jobs, results):
            if isinstance(res, Exception):
                log.error("API %s raised: %s", key, res)
                errors.append(f"{key}: {type(res).__name__}"); continue
            if key == "roblox_username":
                agg.roblox_username = res if isinstance(res, str) else None
                continue
            if not isinstance(res, dict): continue

            if key == "tase" and res:
                agg.tase_score           = res.get("score")
                agg.tase_score_breakdown = res.get("scoreBreakdown", {})
                agg.tase_guilds          = res.get("guilds", [])
                agg.tase_nsfw_records    = res.get("nsfwRecords", [])
                agg.tase_guilds_count    = len(agg.tase_guilds)
                if agg.tase_score and agg.tase_score > 0:
                    agg.sources_flagged.append("TASE")

            elif key == "bc_erp" and res:
                agg.bloxycleaner_flagged = res.get("f", False)
                agg.bloxycleaner_servers = res.get("servers", [])
                if agg.bloxycleaner_flagged and "BloxyCleaner" not in agg.sources_flagged:
                    agg.sources_flagged.append("BloxyCleaner")

            elif key == "bc_exp" and res:
                agg.bloxycleaner_exploit_flagged = res.get("f", False)
                agg.bloxycleaner_exploit_servers = res.get("servers", [])
                if agg.bloxycleaner_exploit_flagged and "BloxyCleaner" not in agg.sources_flagged:
                    agg.sources_flagged.append("BloxyCleaner")

            elif key == "rw" and res:
                agg.rw_condo_servers   = res.get("roblox_servers") or res.get("condo_servers") or []
                agg.rw_exploit_servers = res.get("exploit_servers") or []
                agg.rw_condo_count     = len(agg.rw_condo_servers)
                agg.rw_exploit_count   = len(agg.rw_exploit_servers)
                if agg.rw_condo_count or agg.rw_exploit_count:
                    agg.sources_flagged.append("RobloxWatcher")

            elif key == "rotector_discord" and res:
                data         = res.get("data") or {}
                servers      = data.get("servers", [])
                connections  = data.get("connections", [])
                alt_accounts = data.get("altAccounts", [])
                agg.rotector_discord_servers = servers
                agg.rotector_connections     = connections
                agg.rotector_alt_accounts    = alt_accounts
                if servers:
                    agg.sources_flagged.append("Rotector")
                if connections:
                    agg.rotector_roblox_links = [
                        f"{c.get('robloxUsername', '?')} (`{c.get('robloxUserId', '?')}`)"
                        for c in connections
                    ]

            elif key == "rotector_roblox" and res:
                data       = res.get("data") or {}
                flag_type  = data.get("flagType")
                confidence = data.get("confidence")
                reasons    = data.get("reasons", {})
                agg.rotector_flag_type       = flag_type
                agg.rotector_confidence      = (confidence or 0) * 100 if confidence and confidence <= 1 else confidence
                agg.rotector_reasons         = _parse_rotector_reasons(reasons)
                agg.rotector_category        = data.get("category")
                agg.rotector_is_locked       = data.get("isLocked", False)
                agg.rotector_flagged_friends = data.get("friends") or data.get("flaggedFriends") or []
                agg.rotector_flagged_groups  = data.get("groups")  or data.get("flaggedGroups")  or _extract_groups_from_reasons(reasons)
                if flag_type in ROTECTOR_ACTIONABLE:
                    agg.sources_flagged.append("Rotector")

            elif key == "rotector_roblox_discord" and res:
                data = res.get("data") or {}
                agg.rotector_discord_accounts = data.get("discordAccounts", [])
                agg.rotector_roblox_alts      = data.get("altAccounts", [])

            elif key == "moco" and res:
                agg.moco_group_count = res.get("groupCount")
                agg.moco_group_types = res.get("groupTypes", [])
                agg.moco_groups      = res.get("groups", [])
                if agg.moco_group_count:
                    agg.sources_flagged.append("Moco-co")

            # ── Selfbot result parsing ──
            elif key == "selfbot" and res:
                guilds = res.get("guilds", [])
                if guilds:
                    agg.selfbot_guilds        = guilds
                    agg.selfbot_active_guilds = [g for g in guilds if g.get("still_in_server")]
                    agg.selfbot_prev_guilds   = [g for g in guilds if not g.get("still_in_server")]
                    agg.sources_flagged.append("Selfbot")
                else:
                    agg.selfbot_guilds        = []
                    agg.selfbot_active_guilds = []
                    agg.selfbot_prev_guilds   = []

        # RoCleaner — Discord mode only
        if not roblox_only and self._storage and "ROCLEANER" not in disabled_apis:
            checked.append("RoCleaner")
            servers = self._storage.get_rocleaner_servers(user_id)
            if servers:
                agg.rocleaner_servers = servers
                agg.rocleaner_flagged = True
                agg.sources_flagged.append("RoCleaner")

        agg.errors          = errors
        agg.sources_checked = checked
        return agg

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
