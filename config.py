# config.py

from __future__ import annotations
import os
from dotenv import load_dotenv
load_dotenv()

def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()

def _bool(key: str, default: bool = False) -> bool:
    return _env(key, str(default)).lower() in ("1", "true", "yes")

DISCORD_TOKEN          = _env("DISCORD_TOKEN")
DEV_GUILD_ID           = _env("DEV_GUILD_ID")
LOG_CHANNEL_ID         = _env("LOG_CHANNEL_ID")
STATUS_CHANNEL_ID      = _env("STATUS_CHANNEL_ID")
MOCK_MODE              = _bool("MOCK_MODE", False)

TASE_API_KEY           = _env("TASE_API_KEY")
ROTECTOR_API_KEY       = _env("ROTECTOR_API_KEY")
ROTECTOR_API_BASE      = _env("ROTECTOR_API_BASE", "https://roscoe.robalyx.com")
MOCO_API_KEY           = _env("MOCO_API_KEY")

# RobloxWatcher — new API (RW_ key)
ROBLOXWATCHER_API_KEY  = _env("ROBLOXWATCHER_API_KEY", "")
ROBLOXWATCHER_API_BASE = _env("ROBLOXWATCHER_API_BASE", "https://api.robloxwatcher.com")

# ExploitWatcher — separate EW_ key same base URL
EXPLOITWATCHER_API_KEY  = _env("EXPLOITWATCHER_API_KEY", "")

BLOXYCLEANER_API_KEY   = _env("BLOXYCLEANER_API_KEY", "")
BLOXYCLEANER_BASE      = _env("BLOXYCLEANER_BASE", "https://api.bloxycleaner.xyz")

DISABLED_APIS = [x.strip().upper() for x in _env("DISABLED_APIS").split(",") if x.strip()]

EMBED_COLOR = 0x2B2D31
DIVIDER     = "━" * 26

ROTECTOR_FLAG_LABELS = {0: "Clear", 1: "Flagged", 2: "Confirmed", 3: "Mixed", 4: "Past Offender"}

# RobloxWatcher guild type labels
RW_GUILD_TYPE_LABELS = {
    1: "Condo Server",
    2: "Roblox NSFW Content Server",
    3: "Roblox NSFW Asset Server",
    4: "Roblox NSFW Mods Server",
    5: "Roblox ERP Server",
}

# ExploitWatcher guild type labels
EW_GUILD_TYPE_LABELS = {
    1: "Executor Server",
    2: "Serverside Executor Server",
    3: "External Exploits Server",
    4: "Exploit Scripts Server",
    5: "Executor Reselling Server",
    6: "Serverside Executor Reselling Server",
    7: "External Exploits Reselling Server",
    8: "Exploit Key Bypassing Server",
}

SCORE_BADGE_MAP = {
    "nsfw_content": ("NSFW Content", 0xff0000),
    "exploiting":   ("Exploiting",   0xff6b00),
    "scam":         ("Scam",         0xffaa00),
    "spam":         ("Spam",         0xffff00),
}

FALLBACK_BADGES = [("Flagged", 0xff0000)]
