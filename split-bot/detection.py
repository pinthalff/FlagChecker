from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp

import config
from models import AggregateResult

log = logging.getLogger("bot.detection")


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
            # Guard against HTML/Cloudflare error pages
            ct = r.headers.get("Content-Type", "")
            if "html" in ct:
                log.warning("HTML response (Cloudflare?) from %s", url); return {}
            try:
                text = await r.text()
                if text.strip().startswith("<"):
                    log.warning("Got HTML instead of JSON from %s", url); return {}
                import json as _json
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

async def _fetch_bloxycleaner(session, discord_id: str) -> dict:
    token = config.BLOXYCLEANER_API_KEY or "pub-freeusage"
    data  = await _get(session, f"{config.BLOXYCLEANER_BASE}/p/api/v1/flagged",
                       {"Authorization": token}, {"userid": discord_id}, timeout=20)
    return data.get("users", {}).get(str(discord_id), {})

async def _fetch_robloxwatcher(session, user_id: str) -> dict:
    return await _get(session,
        "https://robloxwatcher.info/checker/api/check.php",
        params={"id": user_id, "key": config.ROBLOXWATCHER_API_KEY})

async def _fetch_rotector(session, roblox_id: str) -> dict:
    return await _get(session,
        f"{config.ROTECTOR_API_BASE}/v1/lookup/roblox/user/{roblox_id}",
        {"Authorization": f"Bearer {config.ROTECTOR_API_KEY}"})

async def _fetch_moco(session, roblox_id: str) -> dict:
    return await _get(session,
        f"https://api.moco-co.org/v2/checkuser/{roblox_id}",
        {"Authorization": config.MOCO_API_KEY})


def _safe_ts(val) -> Optional[int]:
    if val is None: return None
    try: return int(val)
    except (TypeError, ValueError): return None


def correlate_condo_servers(agg: AggregateResult) -> list[dict]:
    by_key: dict = {}

    def _add(server: dict, source: str):
        if not server: return
        sid   = server.get("id")
        name  = server.get("name") or "Unknown"
        key   = str(sid) if sid else name.lower()
        entry = by_key.setdefault(key, {"id": sid, "name": name, "sources": [], "last_seen": None})
        if source not in entry["sources"]: entry["sources"].append(source)
        ts = _safe_ts(server.get("lastSeen"))
        if ts is not None and (entry["last_seen"] is None or ts > entry["last_seen"]):
            entry["last_seen"] = ts

    for s in agg.tase_guilds:          _add(s, "TASE")
    for s in agg.rw_condo_servers:     _add(s, "RobloxWatcher")
    for s in agg.bloxycleaner_servers: _add(s, "BloxyCleaner")
    return sorted(by_key.values(), key=lambda x: x["last_seen"] or 0, reverse=True)


def correlate_exploit_servers(agg: AggregateResult) -> list[dict]:
    return [
        {"id": s.get("id"), "name": s.get("name") or "Unknown", "sources": ["RobloxWatcher"]}
        for s in agg.rw_exploit_servers
    ]


def format_last_seen(ts: Optional[int]) -> str:
    if not ts: return "—"
    try:
        dt   = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        h12  = dt.hour % 12 or 12
        ampm = "AM" if dt.hour < 12 else "PM"
        return f"{h12}:{dt.minute:02d}:{dt.second:02d} {ampm} {dt.month:02d}/{dt.day:02d}/{dt.year % 100:02d}"
    except Exception: return "—"


class DetectionService:
    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    def _sess(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def lookup(self, user_id: str, roblox_only: bool = False, disabled_apis: set = None) -> AggregateResult:
        """
        roblox_only=False : Discord ID — runs TASE + BloxyCleaner + RobloxWatcher concurrently.
        roblox_only=True  : Roblox ID  — runs Rotector + Moco-co only.
        """
        sess    = self._sess()
        errors  = []
        checked = []
        if disabled_apis is None:
            disabled_apis = {s.strip() for s in (getattr(config, "DISABLED_APIS", "") or "").split(",") if s.strip()}

        if roblox_only:
            agg = AggregateResult(discord_id="", roblox_id=int(user_id))

            jobs = []
            if "ROTECTOR" not in disabled_apis:
                checked.append("Rotector")
                jobs.append(("rotector", _fetch_rotector(sess, user_id)))
            if "MOCO" not in disabled_apis:
                checked.append("Moco-co")
                jobs.append(("moco", _fetch_moco(sess, user_id)))

            results = await asyncio.gather(*[j[1] for j in jobs], return_exceptions=True)
            for (key, _), res in zip(jobs, results):
                if isinstance(res, Exception):
                    log.error("API %s raised: %s", key, res)
                    errors.append(f"{key}: {type(res).__name__}"); continue
                if not isinstance(res, dict): continue
                if key == "rotector" and res:
                    agg.rotector_flag_type       = res.get("flagType")
                    agg.rotector_confidence      = res.get("confidence")
                    agg.rotector_reasons         = res.get("reasons", [])
                    agg.rotector_flagged_friends = (res.get("friends") or res.get("flaggedFriends") or [])
                    agg.rotector_flagged_groups  = (res.get("groups")  or res.get("flaggedGroups")  or [])
                    if agg.rotector_flag_type and agg.rotector_flag_type > 0:
                        agg.sources_flagged.append("Rotector")
                elif key == "moco" and res:
                    agg.moco_group_count = res.get("groupCount")
                    agg.moco_group_types = res.get("groupTypes", [])
                    agg.moco_groups      = res.get("groups", [])
                    if agg.moco_group_count:
                        agg.sources_flagged.append("Moco-co")

        else:
            agg = AggregateResult(discord_id=user_id)

            jobs = []
            if "TASE" not in disabled_apis:
                checked.append("TASE")
                jobs.append(("tase", _fetch_tase(sess, user_id)))
            if "BLOXYCLEANER" not in disabled_apis:
                checked.append("BloxyCleaner")
                jobs.append(("bc", _fetch_bloxycleaner(sess, user_id)))
            if "ROBLOXWATCHER" not in disabled_apis:
                checked.append("RobloxWatcher")
                jobs.append(("rw", _fetch_robloxwatcher(sess, user_id)))

            results = await asyncio.gather(*[j[1] for j in jobs], return_exceptions=True)
            for (key, _), res in zip(jobs, results):
                if isinstance(res, Exception):
                    log.error("API %s raised: %s", key, res)
                    errors.append(f"{key}: {type(res).__name__}"); continue
                if not isinstance(res, dict): continue
                if key == "tase" and res:
                    agg.tase_score           = res.get("score")
                    agg.tase_score_breakdown = res.get("scoreBreakdown", {})
                    agg.tase_guilds          = res.get("guilds", [])
                    agg.tase_nsfw_records    = res.get("nsfwRecords", [])
                    agg.tase_guilds_count    = len(agg.tase_guilds)
                    if agg.tase_score and agg.tase_score > 0:
                        agg.sources_flagged.append("TASE")
                elif key == "bc" and res:
                    agg.bloxycleaner_flagged = res.get("f", False)
                    agg.bloxycleaner_servers = res.get("servers", [])
                    if agg.bloxycleaner_flagged:
                        agg.sources_flagged.append("BloxyCleaner")
                elif key == "rw" and res:
                    agg.rw_condo_servers   = res.get("roblox_servers") or res.get("condo_servers") or []
                    agg.rw_exploit_servers = res.get("exploit_servers") or []
                    agg.rw_condo_count     = len(agg.rw_condo_servers)
                    agg.rw_exploit_count   = len(agg.rw_exploit_servers)
                    if agg.rw_condo_count or agg.rw_exploit_count:
                        agg.sources_flagged.append("RobloxWatcher")

        agg.errors          = errors
        agg.sources_checked = checked
        return agg

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
