from __future__ import annotations
import json, logging, os
from datetime import datetime, timezone

_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "settings.json")
_MAX_LOGS  = 100

log = logging.getLogger("bot.storage")

def _defaults() -> dict:
    return {
        "settings": {"private": False, "testing": False, "moderator_only": False, "developer_only": False},
        "roles": {"authorized": [], "blacklisted": [], "developers": [], "moderators": [], "testers": []},
        "command_logs": [], "api_errors": [], "user_servers": {},
        "api_settings": {"TASE": True, "BLOXYCLEANER": True, "ROBLOXWATCHER": True,
                         "ROTECTOR": True, "MOCO": True, "ROCLEANER": True},
    }


class BotStorage:
    def __init__(self, db=None) -> None:
        self.path      = _DATA_PATH
        self._data     = self._load()
        self._db       = db       # DatabaseLayer instance (set after DB connects)
        self._imported = self._load_imported()  # JSON.GZ fallback until MongoDB ready

    # ── DB wiring ──────────────────────────────────────────────────────────────

    def set_database(self, db) -> None:
        """Called from bot.py after database.setup_databases() succeeds."""
        self._db = db
        self._imported = {}  # Free memory once MongoDB is live

    # ── JSON.GZ fallback loader ────────────────────────────────────────────────

    def _load_imported(self) -> dict:
        import gzip
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "imported_flagged.json")
        gz   = base + ".gz"
        try:
            if os.path.exists(gz):
                with gzip.open(gz, "rt", encoding="utf-8") as f:
                    data = __import__("json").load(f)
                log.info("Loaded RoCleaner fallback (JSON.GZ): %d users", len(data))
                return data
            elif os.path.exists(base):
                with open(base, encoding="utf-8") as f:
                    data = __import__("json").load(f)
                log.info("Loaded RoCleaner fallback (JSON): %d users", len(data))
                return data
        except Exception as exc:
            log.error("RoCleaner fallback load error: %s", exc)
        return {}

    # ── JSON settings load/save ────────────────────────────────────────────────

    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in _defaults().items():
                data.setdefault(k, v)
                if isinstance(v, dict):
                    for kk, vv in v.items():
                        data[k].setdefault(kk, vv)
            return data
        except FileNotFoundError: return _defaults()
        except Exception as exc:
            logging.error("Storage load error: %s", exc); return _defaults()

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as exc: logging.error("Storage save error: %s", exc)

    # ── Settings ───────────────────────────────────────────────────────────────

    def get_settings(self) -> dict: return self._data["settings"]
    def toggle_setting(self, key: str) -> bool:
        self._data["settings"][key] = not self._data["settings"].get(key, False)
        self.save(); return self._data["settings"][key]
    def set_setting(self, key: str, value: bool) -> None:
        self._data["settings"][key] = value; self.save()

    # ── Roles ──────────────────────────────────────────────────────────────────

    def has_role(self, role: str, uid) -> bool:
        return str(uid) in self._data["roles"].get(role, [])
    def add_role(self, role: str, uid) -> bool:
        s = str(uid)
        if s not in self._data["roles"][role]:
            self._data["roles"][role].append(s); self.save(); return True
        return False
    def remove_role(self, role: str, uid) -> bool:
        s = str(uid)
        if s in self._data["roles"][role]:
            self._data["roles"][role].remove(s); self.save(); return True
        return False
    def get_role_list(self, role: str) -> list:
        return list(self._data["roles"].get(role, []))

    # ── Command logs ───────────────────────────────────────────────────────────

    def add_command_log(self, entry: dict) -> None:
        entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        logs = self._data["command_logs"]; logs.append(entry)
        if len(logs) > _MAX_LOGS: self._data["command_logs"] = logs[-_MAX_LOGS:]
        self.save()
    def get_command_logs(self, limit: int = 20) -> list:
        return list(reversed(self._data["command_logs"]))[:limit]

    # ── API errors ─────────────────────────────────────────────────────────────

    def add_api_error(self, entry: dict) -> None:
        entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        errs = self._data["api_errors"]; errs.append(entry)
        if len(errs) > _MAX_LOGS: self._data["api_errors"] = errs[-_MAX_LOGS:]
        self.save()
    def get_api_errors(self, limit: int = 20) -> list:
        return list(reversed(self._data["api_errors"]))[:limit]
    def clear_api_errors(self) -> None:
        self._data["api_errors"] = []; self.save()

    # ── User servers ───────────────────────────────────────────────────────────

    def store_user_servers(self, uid, servers: list) -> None:
        self._data["user_servers"][str(uid)] = servers; self.save()
    def get_user_servers(self, uid) -> list:
        return self._data["user_servers"].get(str(uid), [])

    # ── Flagged users (MySQL via db layer, JSON fallback) ──────────────────────

    def add_flagged_user(self, user_id, username: str, sources: list, servers: list) -> None:
        if self._db:
            try:
                self._db.add_flagged_user(str(user_id), username, sources, servers)
                return
            except Exception as exc:
                log.error("DB add_flagged_user failed, no fallback: %s", exc)
        else:
            log.warning("No database connected — flagged user %s not saved", user_id)

    def remove_flagged_user(self, user_id) -> bool:
        if self._db:
            try:
                return self._db.remove_flagged_user(str(user_id))
            except Exception as exc:
                log.error("DB remove_flagged_user failed: %s", exc)
        return False

    def get_flagged_user(self, user_id):
        uid = str(user_id)
        if self._db:
            try:
                rec = self._db.get_flagged_user(uid)
                if rec: return rec
                # Check RoCleaner in MongoDB
                servers = self.get_rocleaner_servers(uid)
                if servers:
                    return {"username": f"User {uid}", "discord_id": uid,
                            "sources": ["RoCleaner"], "servers": servers,
                            "added_at": "imported", "imported": True}
                return None
            except Exception as exc:
                log.error("DB get_flagged_user failed: %s", exc)
        return None

    def is_user_flagged(self, user_id) -> bool:
        uid = str(user_id)
        if self._db:
            try:
                return self._db.is_flagged(uid) or self._db.is_rocleaner_flagged(uid)
            except Exception as exc:
                log.error("DB is_user_flagged failed: %s", exc)
        return uid in self._imported

    def list_flagged_users(self, limit: int = 50) -> list:
        if self._db:
            try:
                return self._db.list_flagged_users(limit)
            except Exception as exc:
                log.error("DB list_flagged_users failed: %s", exc)
        return []

    def imported_count(self) -> int:
        if self._db:
            try:
                return self._db.rocleaner_count()
            except Exception as exc:
                log.error("DB imported_count failed: %s", exc)
        return len(self._imported)

    # ── RoCleaner (MongoDB via db layer) ───────────────────────────────────────

    def get_rocleaner_servers(self, user_id) -> list:
        uid = str(user_id)
        if self._db:
            try:
                return self._db.get_rocleaner_servers(uid)
            except Exception as exc:
                log.error("DB get_rocleaner_servers failed: %s", exc)
        # Fallback: use in-memory JSON.GZ
        servers = self._imported.get(uid)
        if not servers:
            return []
        return [{"name": (s.get("name", "Unknown") if isinstance(s, dict) else str(s)),
                 "id":   (s.get("id") if isinstance(s, dict) else None),
                 "sources": ["RoCleaner"]} for s in servers]

    # ── API settings ───────────────────────────────────────────────────────────

    _API_KEYS = ["TASE", "BLOXYCLEANER", "ROBLOXWATCHER", "ROTECTOR", "MOCO", "ROCLEANER"]
    def _api_settings(self) -> dict:
        self._data.setdefault("api_settings", {k: True for k in self._API_KEYS})
        for k in self._API_KEYS: self._data["api_settings"].setdefault(k, True)
        return self._data["api_settings"]
    def is_api_enabled(self, api_key: str) -> bool:
        return self._api_settings().get(api_key, True)
    def toggle_api(self, api_key: str) -> bool:
        settings = self._api_settings()
        settings[api_key] = not settings.get(api_key, True)
        self.save(); return settings[api_key]
    def get_disabled_apis(self) -> set:
        return {k for k, v in self._api_settings().items() if not v}
