# FlagCheckerDB.py

# FlagCheckerDB.py

# FlagCheckerDB.py

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

DB_SIZE_LIMIT_BYTES = 460 * 1024 * 1024

def _bool_env(key: str, default: bool) -> bool:
    val = os.environ.get(key, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes")

SELFBOT_ENABLED = _bool_env("SELFBOT_ENABLED", False)


def _get_db_size(client, db_name: str) -> int:
    try:
        stats = client[db_name].command("dbStats")
        return stats.get("dataSize", 0) + stats.get("indexSize", 0)
    except Exception:
        return 0


def _connect(url: str, db_name: str):
    client = MongoClient(
        url,
        serverSelectionTimeoutMS    = 5000,
        connectTimeoutMS            = 5000,
        socketTimeoutMS             = 10000,
        retryWrites                 = True,
        tls                         = True,
        tlsAllowInvalidCertificates = True,
        tlsAllowInvalidHostnames    = True,
    )
    client.admin.command("ping")
    return client, client[db_name]


class FlagCheckerDB:
    """
    Multi-MongoDB support.
    DBs 1-5: member data (seen_users, previous_users, flagged_users)
    DBs 6-7: messages only

    Env vars:
      FLAGDB_URL    / FLAGDB_DB    — DB 1 (required)
      FLAGDB_URL_2  / FLAGDB_DB_2  — DB 2 (optional)
      FLAGDB_URL_3  / FLAGDB_DB_3  — DB 3 (optional)
      FLAGDB_URL_4  / FLAGDB_DB_4  — DB 4 (optional)
      FLAGDB_URL_5  / FLAGDB_DB_5  — DB 5 (optional)
      FLAGDB_URL_6  / FLAGDB_DB_6  — DB 6 messages (optional)
      FLAGDB_URL_7  / FLAGDB_DB_7  — DB 7 messages (optional)

      SELFBOT_ENABLED = true/false
    """

    def __init__(self):
        self._member_conns   = []
        self._message_conns  = []
        self._active_idx     = 0
        self._active_msg_idx = 0

        member_slots = [
            (os.environ.get("FLAGDB_URL",   ""), os.environ.get("FLAGDB_DB",   "discord_scraper")),
            (os.environ.get("FLAGDB_URL_2", ""), os.environ.get("FLAGDB_DB_2", "discord_scraper")),
            (os.environ.get("FLAGDB_URL_3", ""), os.environ.get("FLAGDB_DB_3", "discord_scraper")),
            (os.environ.get("FLAGDB_URL_4", ""), os.environ.get("FLAGDB_DB_4", "discord_scraper")),
            (os.environ.get("FLAGDB_URL_5", ""), os.environ.get("FLAGDB_DB_5", "discord_scraper")),
        ]

        message_slots = [
            (os.environ.get("FLAGDB_URL_6", ""), os.environ.get("FLAGDB_DB_6", "discord_messages")),
            (os.environ.get("FLAGDB_URL_7", ""), os.environ.get("FLAGDB_DB_7", "discord_messages")),
        ]

        # ── Connect member DBs ──
        for i, (url, db_name) in enumerate(member_slots):
            if not url or not db_name:
                continue
            try:
                client, db = _connect(url, db_name)
                self._member_conns.append((client, db, db_name))
                size_mb = _get_db_size(client, db_name) / 1024 / 1024
                log.info("[FlagCheckerDB] Member DB %d connected — %s (%.1fMB)", i + 1, db_name, size_mb)

                db["flagged_users"].create_index("user_id", unique=True)
                db["seen_users"].create_index([("user_id", ASCENDING), ("guild_id", ASCENDING)], unique=True)
                db["seen_users"].create_index("user_id")
                db["previous_users"].create_index([("user_id", ASCENDING), ("guild_id", ASCENDING)], unique=True)
                db["previous_users"].create_index("user_id")
                db["previous_users"].create_index("left_at")
                db["api_errors"].create_index([("logged_at", ASCENDING)])
                db["disabled_apis"].create_index("api_name", unique=True)
                db["roles"].create_index([("role_name", ASCENDING), ("user_id", ASCENDING)], unique=True)
                db["rocleaner"].create_index("user_id")
            except Exception as e:
                log.warning("[FlagCheckerDB] Member DB %d failed: %s", i + 1, e)

        # ── Connect message DBs ──
        for i, (url, db_name) in enumerate(message_slots):
            if not url or not db_name:
                continue
            try:
                client, db = _connect(url, db_name)
                self._message_conns.append((client, db, db_name))
                size_mb = _get_db_size(client, db_name) / 1024 / 1024
                log.info("[FlagCheckerDB] Message DB %d connected — %s (%.1fMB)", i + 6, db_name, size_mb)

                db["messages"].create_index([("message_id", 1)], unique=True)
                db["messages"].create_index("user_id")
                db["messages"].create_index("guild_id")
                db["messages"].create_index("sent_at")
            except Exception as e:
                log.warning("[FlagCheckerDB] Message DB %d failed: %s", i + 6, e)

        if not self._member_conns:
            raise RuntimeError("No MongoDB connections available — set FLAGDB_URL and FLAGDB_DB")

        # ── Find active write DB ──
        for i, (client, db, db_name) in enumerate(self._member_conns):
            size = _get_db_size(client, db_name)
            if size < DB_SIZE_LIMIT_BYTES:
                self._active_idx = i
                log.info("[FlagCheckerDB] Active member write DB: %d (%s)", i + 1, db_name)
                break
        else:
            self._active_idx = len(self._member_conns) - 1
            log.warning("[FlagCheckerDB] All member DBs near capacity")

        if self._message_conns:
            for i, (client, db, db_name) in enumerate(self._message_conns):
                size = _get_db_size(client, db_name)
                if size < DB_SIZE_LIMIT_BYTES:
                    self._active_msg_idx = i
                    log.info("[FlagCheckerDB] Active message write DB: %d (%s)", i + 6, db_name)
                    break
            else:
                self._active_msg_idx = len(self._message_conns) - 1
                log.warning("[FlagCheckerDB] All message DBs near capacity")

    # ─────────────────────────────────────────────
    # Active write DBs — auto overflow
    # ─────────────────────────────────────────────

    @property
    def _active_db(self):
        client, db, db_name = self._member_conns[self._active_idx]
        size = _get_db_size(client, db_name)
        if size >= DB_SIZE_LIMIT_BYTES:
            log.warning("[FlagCheckerDB] Member DB %d full — overflowing", self._active_idx + 1)
            for i in range(self._active_idx + 1, len(self._member_conns)):
                nc, ndb, nname = self._member_conns[i]
                if _get_db_size(nc, nname) < DB_SIZE_LIMIT_BYTES:
                    self._active_idx = i
                    log.info("[FlagCheckerDB] Switched to member DB %d (%s)", i + 1, nname)
                    return ndb
            log.warning("[FlagCheckerDB] No member DB with space")
        return db

    @property
    def _active_msg_db(self):
        if not self._message_conns:
            return None
        client, db, db_name = self._message_conns[self._active_msg_idx]
        size = _get_db_size(client, db_name)
        if size >= DB_SIZE_LIMIT_BYTES:
            log.warning("[FlagCheckerDB] Message DB %d full — overflowing", self._active_msg_idx + 6)
            for i in range(self._active_msg_idx + 1, len(self._message_conns)):
                nc, ndb, nname = self._message_conns[i]
                if _get_db_size(nc, nname) < DB_SIZE_LIMIT_BYTES:
                    self._active_msg_idx = i
                    log.info("[FlagCheckerDB] Switched to message DB %d (%s)", i + 6, nname)
                    return ndb
            log.warning("[FlagCheckerDB] No message DB with space")
        return db

    @property
    def _all_member_dbs(self):
        return [db for _, db, _ in self._member_conns]

    @property
    def _all_message_dbs(self):
        return [db for _, db, _ in self._message_conns]

    @property
    def all_cols(self):
        return [db["seen_users"] for _, db, _ in self._member_conns]

    def close(self):
        for client, _, _ in self._member_conns + self._message_conns:
            try:
                client.close()
            except Exception:
                pass

    def selfbot_enabled(self) -> bool:
        return SELFBOT_ENABLED

    def db_status(self) -> list:
        status = []
        for i, (client, db, db_name) in enumerate(self._member_conns):
            size    = _get_db_size(client, db_name)
            size_mb = size / 1024 / 1024
            pct     = (size / DB_SIZE_LIMIT_BYTES) * 100
            status.append({
                "slot":    i + 1,
                "type":    "member",
                "db_name": db_name,
                "size_mb": round(size_mb, 1),
                "pct":     round(pct, 1),
                "active":  i == self._active_idx,
                "full":    size >= DB_SIZE_LIMIT_BYTES,
            })
        for i, (client, db, db_name) in enumerate(self._message_conns):
            size    = _get_db_size(client, db_name)
            size_mb = size / 1024 / 1024
            pct     = (size / DB_SIZE_LIMIT_BYTES) * 100
            status.append({
                "slot":    i + 6,
                "type":    "messages",
                "db_name": db_name,
                "size_mb": round(size_mb, 1),
                "pct":     round(pct, 1),
                "active":  i == self._active_msg_idx,
                "full":    size >= DB_SIZE_LIMIT_BYTES,
            })
        return status

    # ─────────────────────────────────────────────
    # Flagged users
    # ─────────────────────────────────────────────

    def add_flagged_user(self, user_id: str, username: str, sources: list, servers: list) -> None:
        try:
            self._active_db["flagged_users"].update_one(
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
        for db in self._all_member_dbs:
            try:
                doc = db["flagged_users"].find_one({"user_id": str(user_id)})
                if doc:
                    return doc
            except Exception as e:
                log.error("[FlagCheckerDB] get_flagged_user: %s", e)
        return None

    def get_all_flagged(self, limit: int = 100, skip: int = 0) -> list:
        results = []
        for db in self._all_member_dbs:
            try:
                docs = list(
                    db["flagged_users"].find()
                    .sort("flagged_at", -1)
                    .limit(limit)
                )
                results.extend(docs)
            except Exception:
                pass
        results.sort(key=lambda x: x.get("flagged_at", datetime.min), reverse=True)
        return results[:limit]

    def count_flagged(self) -> int:
        total = 0
        for db in self._all_member_dbs:
            try:
                total += db["flagged_users"].count_documents({})
            except Exception:
                pass
        return total

    def save_detection_result(self, user_id: str, username: str, agg) -> None:
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

            self._active_db["flagged_users"].update_one(
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
    # Seen users + Previous users
    # build_selfbot_report reads BOTH and merges
    # ─────────────────────────────────────────────

    def get_seen_user(self, user_id: int) -> list:
        results     = []
        seen_guilds = set()
        for db in self._all_member_dbs:
            try:
                for doc in db["seen_users"].find({"user_id": user_id}):
                    gid = doc.get("guild_id")
                    if gid not in seen_guilds:
                        seen_guilds.add(gid)
                        results.append(doc)
            except Exception as e:
                log.error("[FlagCheckerDB] get_seen_user: %s", e)
        return results

    def get_previous_user(self, user_id: int) -> list:
        results     = []
        seen_guilds = set()
        for db in self._all_member_dbs:
            try:
                for doc in db["previous_users"].find({"user_id": user_id}):
                    gid = doc.get("guild_id")
                    if gid not in seen_guilds:
                        seen_guilds.add(gid)
                        results.append(doc)
            except Exception as e:
                log.error("[FlagCheckerDB] get_previous_user: %s", e)
        return results

    def _is_in_previous_users(self, user_id: int, guild_id) -> bool:
        """
        Check if a user exists in previous_users for a specific guild.
        If they do — they left — override still_in_server to False.
        """
        guild_id_int = int(guild_id) if guild_id else None
        if not guild_id_int:
            return False
        for db in self._all_member_dbs:
            try:
                doc = db["previous_users"].find_one(
                    {"user_id": user_id, "guild_id": guild_id_int},
                    projection={"_id": 1}
                )
                if doc:
                    return True
            except Exception:
                pass
        return False

    def build_selfbot_report(self, user_id: int) -> dict:
        """
        Reads BOTH seen_users and previous_users.
        
        Priority logic:
        - If user exists in previous_users for a guild → still_in_server = False
        - If user only in seen_users and still_in_server = True → current
        - If user only in seen_users and still_in_server = False → previous
        - If user only in previous_users → previous
        
        previous_users always wins over seen_users still_in_server field.
        """
        guilds      = []
        seen_guilds = set()

        # ── Build set of guild IDs where user is in previous_users ──
        # These are confirmed departed — always override to False
        departed_guild_ids = set()
        for doc in self.get_previous_user(user_id):
            gid = str(doc.get("guild_id", ""))
            if gid:
                departed_guild_ids.add(gid)

        # ── Read seen_users ──
        for doc in self.get_seen_user(user_id):
            gid = str(doc.get("guild_id", ""))
            if gid in seen_guilds:
                continue
            seen_guilds.add(gid)

            # If this guild is in previous_users — they left
            # Override still_in_server regardless of what seen_users says
            if gid in departed_guild_ids:
                still_in_server = False
            else:
                still_in_server = doc.get("still_in_server", False)

            guilds.append({
                "guild_id":        gid,
                "guild_name":      doc.get("guild_name", "Unknown"),
                "username":        doc.get("username", f"ID:{user_id}"),
                "join_date":       doc.get("join_date", "unknown"),
                "roles":           doc.get("roles", []),
                "still_in_server": still_in_server,
                "message_count":   doc.get("message_count", 0),
                "recent_messages": doc.get("messages", []),
                "source":          "seen_users"
            })

        # ── Read previous_users — add guilds not already in seen_users ──
        for doc in self.get_previous_user(user_id):
            gid = str(doc.get("guild_id", ""))
            if gid in seen_guilds:
                continue
            seen_guilds.add(gid)
            guilds.append({
                "guild_id":        gid,
                "guild_name":      doc.get("guild_name", "Unknown"),
                "username":        doc.get("username", f"ID:{user_id}"),
                "join_date":       doc.get("join_date", "unknown"),
                "roles":           doc.get("roles", []),
                "still_in_server": False,
                "message_count":   0,
                "recent_messages": [],
                "source":          "previous_users"
            })

        if not guilds:
            return {}

        return {
            "user_id":       str(user_id),
            "guilds":        guilds,
            "total_servers": len(guilds)
        }

    def save_previous_user(self, user_id: int, guild_id: int, guild_name: str,
                           username: str, join_date: str, roles: list,
                           reason: str = "left") -> None:
        try:
            self._active_db["previous_users"].update_one(
                {"user_id": user_id, "guild_id": guild_id},
                {
                    "$set": {
                        "username":   username,
                        "guild_name": guild_name,
                        "roles":      roles,
                        "reason":     reason,
                        "left_at":    datetime.now(timezone.utc),
                    },
                    "$setOnInsert": {
                        "user_id":    user_id,
                        "guild_id":   guild_id,
                        "join_date":  join_date,
                        "first_seen": datetime.now(timezone.utc),
                    }
                },
                upsert=True
            )
        except Exception as e:
            log.error("[FlagCheckerDB] save_previous_user: %s", e)

    # ─────────────────────────────────────────────
    # Messages — read from DBs 6-7
    # ─────────────────────────────────────────────

    def get_messages(self, user_id: int, limit: int = 50) -> list:
        results = []
        for db in self._all_message_dbs:
            try:
                docs = list(
                    db["messages"]
                    .find({"user_id": user_id})
                    .sort("sent_at", -1)
                    .limit(limit)
                )
                results.extend(docs)
            except Exception as e:
                log.error("[FlagCheckerDB] get_messages: %s", e)
        results.sort(key=lambda x: x.get("sent_at", ""), reverse=True)
        return results[:limit]

    def save_message(self, message_id: str, user_id: int, username: str,
                     guild_id: int, guild_name: str, channel_id: str,
                     channel_name: str, content: str, sent_at: str) -> bool:
        db = self._active_msg_db
        if db is None:
            return False
        try:
            db["messages"].update_one(
                {"message_id": message_id},
                {
                    "$setOnInsert": {
                        "message_id":   message_id,
                        "user_id":      user_id,
                        "username":     username,
                        "guild_id":     guild_id,
                        "guild_name":   guild_name,
                        "channel_id":   channel_id,
                        "channel_name": channel_name,
                        "content":      content[:2000],
                        "sent_at":      sent_at,
                        "logged_at":    datetime.now(timezone.utc),
                    }
                },
                upsert=True
            )
            return True
        except Exception as e:
            log.error("[FlagCheckerDB] save_message: %s", e)
            return False

    # ─────────────────────────────────────────────
    # API errors
    # ─────────────────────────────────────────────

    def add_api_error(self, entry: dict) -> None:
        try:
            entry["logged_at"] = datetime.now(timezone.utc)
            self._active_db["api_errors"].insert_one(entry)
        except Exception as e:
            log.error("[FlagCheckerDB] add_api_error: %s", e)

    # ─────────────────────────────────────────────
    # Disabled APIs
    # ─────────────────────────────────────────────

    def get_disabled_apis(self) -> set:
        try:
            docs = self._active_db["disabled_apis"].find({}, {"api_name": 1})
            return {d["api_name"].upper() for d in docs}
        except Exception:
            return set()

    def disable_api(self, api_name: str) -> None:
        try:
            self._active_db["disabled_apis"].update_one(
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
            self._active_db["disabled_apis"].delete_one({"api_name": api_name.upper()})
        except Exception as e:
            log.error("[FlagCheckerDB] enable_api: %s", e)

    # ─────────────────────────────────────────────
    # Roles
    # ─────────────────────────────────────────────

    def has_role(self, role_name: str, user_id: int) -> bool:
        for db in self._all_member_dbs:
            try:
                if db["roles"].find_one({"role_name": role_name, "user_id": str(user_id)}):
                    return True
            except Exception:
                pass
        return False

    def add_role(self, role_name: str, user_id: int) -> None:
        try:
            self._active_db["roles"].update_one(
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
        for db in self._all_member_dbs:
            try:
                db["roles"].delete_one({"role_name": role_name, "user_id": str(user_id)})
            except Exception:
                pass

    def get_role_members(self, role_name: str) -> list:
        results = set()
        for db in self._all_member_dbs:
            try:
                for d in db["roles"].find({"role_name": role_name}, {"user_id": 1}):
                    results.add(int(d["user_id"]))
            except Exception:
                pass
        return list(results)

    # ─────────────────────────────────────────────
    # RoCleaner
    # ─────────────────────────────────────────────

    def get_rocleaner_servers(self, user_id: str) -> list:
        for db in self._all_member_dbs:
            try:
                doc = db["rocleaner"].find_one({"user_id": str(user_id)})
                if doc:
                    return doc.get("servers", [])
            except Exception as e:
                log.error("[FlagCheckerDB] get_rocleaner_servers: %s", e)
        return []

    # ─────────────────────────────────────────────
    # User servers
    # ─────────────────────────────────────────────

    def store_user_servers(self, user_id: int, servers: list) -> None:
        try:
            self._active_db["flagged_users"].update_one(
                {"user_id": str(user_id)},
                {"$set": {
                    "mutual_servers": servers,
                    "updated_at":     datetime.now(timezone.utc)
                }}
            )
        except Exception as e:
            log.error("[FlagCheckerDB] store_user_servers: %s", e)

    def get_user_servers(self, user_id: int) -> list:
        for db in self._all_member_dbs:
            try:
                doc = db["flagged_users"].find_one(
                    {"user_id": str(user_id)},
                    {"mutual_servers": 1}
                )
                if doc and doc.get("mutual_servers"):
                    return doc["mutual_servers"]
            except Exception:
                pass
        return []

    # ─────────────────────────────────────────────
    # Global notes
    # ─────────────────────────────────────────────

    def set_global_note(self, user_id: str, note: str, set_by: str) -> None:
        try:
            self._active_db["flagged_users"].update_one(
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
        for db in self._all_member_dbs:
            try:
                doc = db["flagged_users"].find_one(
                    {"user_id": user_id},
                    {"global_note": 1}
                )
                if doc and doc.get("global_note"):
                    return doc["global_note"]
            except Exception:
                pass
        return None

    # ─────────────────────────────────────────────
    # Command logs — Discord channel only
    # ─────────────────────────────────────────────

    def add_command_log(self, entry: dict) -> None:
        pass

    def get_command_logs(self, limit: int = 50) -> list:
        return []
