from __future__ import annotations
import json, logging, os
from datetime import datetime, timezone

_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "settings.json")
_MAX_LOGS  = 100

def _defaults() -> dict:
    return {
        "settings": {"private": False, "testing": False, "moderator_only": False, "developer_only": False},
        "roles": {"authorized": [], "blacklisted": [], "developers": [], "moderators": [], "testers": []},
        "command_logs": [], "api_errors": [], "user_servers": {},
        "flagged_users": {},
        "api_settings": {"TASE": True, "BLOXYCLEANER": True, "ROBLOXWATCHER": True, "ROTECTOR": True, "MOCO": True},
    }

class BotStorage:
    def __init__(self) -> None:
        self.path  = _DATA_PATH
        self._data = self._load()

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

    def get_settings(self) -> dict: return self._data["settings"]
    def toggle_setting(self, key: str) -> bool:
        self._data["settings"][key] = not self._data["settings"].get(key, False)
        self.save(); return self._data["settings"][key]
    def set_setting(self, key: str, value: bool) -> None:
        self._data["settings"][key] = value; self.save()

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

    def add_command_log(self, entry: dict) -> None:
        entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        logs = self._data["command_logs"]; logs.append(entry)
        if len(logs) > _MAX_LOGS: self._data["command_logs"] = logs[-_MAX_LOGS:]
        self.save()
    def get_command_logs(self, limit: int = 20) -> list:
        return list(reversed(self._data["command_logs"]))[:limit]

    def add_api_error(self, entry: dict) -> None:
        entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        errs = self._data["api_errors"]; errs.append(entry)
        if len(errs) > _MAX_LOGS: self._data["api_errors"] = errs[-_MAX_LOGS:]
        self.save()
    def get_api_errors(self, limit: int = 20) -> list:
        return list(reversed(self._data["api_errors"]))[:limit]
    def clear_api_errors(self) -> None:
        self._data["api_errors"] = []; self.save()

    def store_user_servers(self, uid, servers: list) -> None:
        self._data["user_servers"][str(uid)] = servers; self.save()
    def get_user_servers(self, uid) -> list:
        return self._data["user_servers"].get(str(uid), [])

    # ── Flagged-user database ─────────────────────────────────────────────────
    def add_flagged_user(self, user_id, username: str, sources: list, servers: list) -> None:
        self._data["flagged_users"][str(user_id)] = {
            "username":   username,
            "discord_id": str(user_id),
            "sources":    list(sources),
            "servers":    list(servers)[:20],
            "added_at":   datetime.now(timezone.utc).isoformat(),
        }
        self.save()

    def remove_flagged_user(self, user_id) -> bool:
        key = str(user_id)
        if key in self._data["flagged_users"]:
            del self._data["flagged_users"][key]; self.save(); return True
        return False

    def get_flagged_user(self, user_id):
        return self._data["flagged_users"].get(str(user_id))

    def is_user_flagged(self, user_id) -> bool:
        return str(user_id) in self._data["flagged_users"]

    def list_flagged_users(self, limit: int = 50) -> list:
        users = list(self._data["flagged_users"].values())
        return sorted(users, key=lambda x: x.get("added_at", ""), reverse=True)[:limit]

    # ── API enable/disable settings ───────────────────────────────────────────
    _API_KEYS = ["TASE", "BLOXYCLEANER", "ROBLOXWATCHER", "ROTECTOR", "MOCO"]

    def _api_settings(self) -> dict:
        self._data.setdefault("api_settings", {k: True for k in self._API_KEYS})
        for k in self._API_KEYS:
            self._data["api_settings"].setdefault(k, True)
        return self._data["api_settings"]

    def is_api_enabled(self, api_key: str) -> bool:
        return self._api_settings().get(api_key, True)

    def toggle_api(self, api_key: str) -> bool:
        """Toggle API on/off. Returns new state (True = enabled)."""
        settings = self._api_settings()
        settings[api_key] = not settings.get(api_key, True)
        self.save()
        return settings[api_key]

    def get_disabled_apis(self) -> set:
        return {k for k, v in self._api_settings().items() if not v}
