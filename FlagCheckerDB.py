# FlagCheckerDB.py

# FlagCheckerDB.py

# FlagCheckerDB.py

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from pymongo import MongoClient, ASCENDING

log = logging.getLogger("bot.db")


def _bool_env(key: str, default: bool) -> bool:
    val = os.environ.get(key, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes")

SELFBOT_ENABLED = _bool_env("SELFBOT_ENABLED", False)


class FlagCheckerDB:
    def __init__(self):
        url = os.environ.get("FLAGDB_URL", "")
        db  = os.environ.get("FLAGDB_DB",  "discord_scraper")
        if not url:
            raise RuntimeError("FLAGDB_URL not set")

        self._client = MongoClient(url, serverSelectionTimeoutMS=5000)
        self._db     = self._client[db]

        self.flagged_users = self._db["flagged_users"]
        self.seen_users    = self._db["seen_users"]
        self.api_errors    = self._db["api_errors"]
        self.disabled_apis = self._db["disabled_apis"]
        self.roles         = self._db["roles"]
        self.rocleaner     = self._db["rocleaner"]

        self.flagged_users.create_index("user_id", unique=True)
        self.seen_users.create_index([("user_id", ASCENDING), ("guild_id", ASCENDING)], unique=True)
        self.seen_users.create_index("user_id")
        self.api_errors.create_index([("logged_at", ASCENDING)])
        self.disabled_apis.create_index("api_name", unique=True)
        self.roles.create_index([("role_name", ASCENDING), ("user_id", ASCENDING)], unique=True)
        self.rocleaner.create_index("user_id")

        log.info("[FlagCheckerDB] Connected — DB: %s | SELFBOT_ENABLED: %s", db, SELFBOT_ENABLED)

    def close(self):
        self._client.close()

    def selfbot_enabled(self) -> bool:
        return SELFBOT_ENABLED

    # ─────────────────────────────────────────────
    # Flagged users
    # ─────────────────────────────────────────────

    def add_flagged_user(self, user_id: str, username: str, sources: list, servers: list) -> None:
        try:
            self.flagged_users.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "username":   username,
                        "sources":    sources,
                        "servers":    servers,
                        "updated_at": datetime.now(timezone.utc),
                    },
                    "$setOnInsert": {
                        "user_id":    user_id,
                        "flagged_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True
            )
        except Exception as e:
            log.error("[FlagCheckerDB] add_flagged_user: %s", e)

    def get_flagged_user(self, user_id: str) -> Optional[dict]:
        try:
            return self.flagged_users.find_one({"user_id": str(user_id)})
        except Exception as e:
            log.error("[FlagCheckerDB] get_flagged_user: %s", e)
            return None

    def get_all_flagged(self, limit: int = 100, skip: int = 0) -> list:
        try:
            return list(
                self.flagged_users.find()
                .sort("flagged_at", -1)
                .skip(skip)
                .limit(limit)
            )
        except Exception as e:
            log.error("[FlagCheckerDB] get_all_flagged: %s", e)
            return []

    def count_flagged(self) -> int:
        try:
            return self.flagged_users.count_documents({})
        except Exception:
            return 0

    def save_detection_result(self, user_id: str, username: str, agg) -> None:
        """
        Saves full detection result to flagged_users.
        Stores condos, exploits, tase, rotector, bloxycleaner,
        selfbot guilds — everything from the AggregateResult.
        """
        try:
            servers = []
            for s in getattr(agg, "tase_guilds", []):
                servers.append({"name": s.get("name", "Unknown"), "source": "TASE"})
            for s in getattr(agg, "rw_condo_servers", []):
                servers.append({"name": s.get("name", "Unknown"), "source": "RobloxWatcher-Condo"})
            for s in getattr(agg, "rw_exploit_servers", []):
                servers.append({"name": s.get("name", "Unknown"), "source": "RobloxWatcher-Exploit"})
            for s in getattr(agg, "bloxycleaner_servers", []):
                servers.append({"name": s.get("name", s.get("serverName", "Unknown")), "source": "BloxyCleaner-ERP"})
            for s in getattr(agg, "bloxycleaner_exploit_servers", []):
                servers.append({"name": s.get("name", s.get("serverName", "Unknown")), "source": "BloxyCleaner-Exploit"})
            for s in getattr(agg, "rocleaner_servers", []):
                servers.append({"name": s.get("name", "Unknown"), "source": "RoCleaner"})
            for s in getattr(agg, "rotector_discord_servers", []):
                servers.append({"name": s.get("name", "Unknown"), "source": "Rotector"})
            for g in getattr(agg, "selfbot_active_guilds", []):
                servers.append({"name": g.get("guild_name", "Unknown"), "source": "Selfbot-Current"})
            for g in getattr(agg, "selfbot_prev_guilds", []):
                servers.append({"name": g.get("guild_name", "Unknown"), "source": "Selfbot-Previous"})

            if not servers and not getattr(agg, "sources_flagged", []):
                return

            self.flagged_users.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "username":        username,
                        "sources_flagged": getattr(agg, "sources_flagged", []),
                        "servers":         servers,
                        "tase_score":      getattr(agg, "tase_score", None),
                        "roblox_id":       str(getattr(agg, "roblox_id", "") or ""),
                        "roblox_username": getattr(agg, "roblox_username", None),
                        "updated_at":      datetime.now(timezone.utc),
                    },
                    "$setOnInsert": {
                        "user_id":    user_id,
                        "flagged_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True
            )
        except Exception as e:
            log.error("[FlagCheckerDB] save_detection_result: %s", e)

    # ─────────────────────────────────────────────
    # Seen users — selfbot scraped data
    # ─────────────────────────────────────────────

    def get_seen_user(self, user_id: int) -> list:
        try:
            return list(self.seen_users.find({"user_id": user_id}))
        except Exception as e:
            log.error("[FlagCheckerDB] get_seen_user: %s", e)
            return []

    def build_selfbot_report(self, user_id: int) -> dict:
        docs = self.get_seen_user(user_id)
        if not docs:
            return {}

        guilds = []
        for doc in docs:
            guilds.append({
                "guild_id":        str(doc.get("guild_id", "")),
                "guild_name":      doc.get("guild_name", "Unknown"),
                "username":        doc.get("username", f"ID:{user_id}"),
                "join_date":       doc.get("join_date", "unknown"),
                "roles":           doc.get("roles", []),
                "still_in_server": doc.get("still_in_server", False),
                "message_count":   doc.get("message_count", 0),
                "recent_messages": doc.get("messages", []),
                "source":          "db"
            })

        return {
            "user_id":       str(user_id),
            "guilds":        guilds,
            "total_servers": len(guilds)
        }

    # ─────────────────────────────────────────────
    # API errors — keep these, useful for debugging
    # ─────────────────────────────────────────────

    def add_api_error(self, entry: dict) -> None:
        try:
            entry["logged_at"] = datetime.now(timezone.utc)
            self.api_errors.insert_one(entry)
        except Exception as e:
            log.error("[FlagCheckerDB] add_api_error: %s", e)

    # ─────────────────────────────────────────────
    # Disabled APIs
    # ─────────────────────────────────────────────

    def get_disabled_apis(self) -> set:
        try:
            docs = self.disabled_apis.find({}, {"api_name": 1})
            return {d["api_name"].upper() for d in docs}
        except Exception:
            return set()

    def disable_api(self, api_name: str) -> None:
        try:
            self.disabled_apis.update_one(
                {"api_name": api_name.upper()},
                {"$setOnInsert": {
                    "api_name":    api_name.upper(),
                    "disabled_at": datetime.now(timezone.utc)
                }},
                upsert=True
            )
        except Exception as e:
            log.error("[FlagCheckerDB] disable_api: %s", e)

    def enable_api(self, api_name: str) -> None:
        try:
            self.disabled_apis.delete_one({"api_name": api_name.upper()})
        except Exception as e:
            log.error("[FlagCheckerDB] enable_api: %s", e)

    # ─────────────────────────────────────────────
    # Roles
    # ─────────────────────────────────────────────

    def has_role(self, role_name: str, user_id: int) -> bool:
        try:
            return bool(self.roles.find_one({
                "role_name": role_name,
                "user_id":   str(user_id)
            }))
        except Exception:
            return False

    def add_role(self, role_name: str, user_id: int) -> None:
        try:
            self.roles.update_one(
                {"role_name": role_name, "user_id": str(user_id)},
                {"$setOnInsert": {
                    "role_name": role_name,
                    "user_id":   str(user_id),
                    "added_at":  datetime.now(timezone.utc)
                }},
                upsert=True
            )
        except Exception as e:
            log.error("[FlagCheckerDB] add_role: %s", e)

    def remove_role(self, role_name: str, user_id: int) -> None:
        try:
            self.roles.delete_one({
                "role_name": role_name,
                "user_id":   str(user_id)
            })
        except Exception as e:
            log.error("[FlagCheckerDB] remove_role: %s", e)

    def get_role_members(self, role_name: str) -> list:
        try:
            return [
                int(d["user_id"])
                for d in self.roles.find({"role_name": role_name}, {"user_id": 1})
            ]
        except Exception:
            return []

    # ─────────────────────────────────────────────
    # RoCleaner
    # ─────────────────────────────────────────────

    def get_rocleaner_servers(self, user_id: str) -> list:
        try:
            doc = self.rocleaner.find_one({"user_id": str(user_id)})
            return doc.get("servers", []) if doc else []
        except Exception as e:
            log.error("[FlagCheckerDB] get_rocleaner_servers: %s", e)
            return []

    # ─────────────────────────────────────────────
    # User servers
    # ─────────────────────────────────────────────

    def store_user_servers(self, user_id: int, servers: list) -> None:
        try:
            self.flagged_users.update_one(
                {"user_id": str(user_id)},
                {"$set": {
                    "mutual_servers": servers,
                    "updated_at":     datetime.now(timezone.utc)
                }}
            )
        except Exception as e:
            log.error("[FlagCheckerDB] store_user_servers: %s", e)

    def get_user_servers(self, user_id: int) -> list:
        try:
            doc = self.flagged_users.find_one(
                {"user_id": str(user_id)},
                {"mutual_servers": 1}
            )
            return doc.get("mutual_servers", []) if doc else []
        except Exception:
            return []

    # ─────────────────────────────────────────────
    # Global notes
    # ─────────────────────────────────────────────

    def set_global_note(self, user_id: str, note: str, set_by: str) -> None:
        try:
            self.flagged_users.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "global_note":        note,
                        "global_note_set_by": set_by,
                        "global_note_at":     datetime.now(timezone.utc),
                        "updated_at":         datetime.now(timezone.utc),
                    },
                    "$setOnInsert": {
                        "user_id":    user_id,
                        "flagged_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True
            )
        except Exception as e:
            log.error("[FlagCheckerDB] set_global_note: %s", e)

    def get_global_note(self, user_id: str) -> Optional[str]:
        try:
            doc = self.flagged_users.find_one(
                {"user_id": user_id},
                {"global_note": 1}
            )
            return doc.get("global_note") if doc else None
        except Exception:
            return None
