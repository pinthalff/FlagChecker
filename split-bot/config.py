from __future__ import annotations
import os
from dotenv import load_dotenv
load_dotenv()

def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()

def _bool(key: str, default: bool = False) -> bool:
    return _env(key, str(default)).lower() in ("1", "true", "yes")

DISCORD_TOKEN         = _env("DISCORD_TOKEN")
DEV_GUILD_ID          = _env("DEV_GUILD_ID")
LOG_CHANNEL_ID        = _env("LOG_CHANNEL_ID")
STATUS_CHANNEL_ID     = _env("STATUS_CHANNEL_ID")
MOCK_MODE             = _bool("MOCK_MODE", False)   # DEFAULT OFF — use real APIs
TASE_API_KEY          = _env("TASE_API_KEY")
ROTECTOR_API_KEY      = _env("ROTECTOR_API_KEY")
ROTECTOR_API_BASE     = _env("ROTECTOR_API_BASE", "https://roscoe.robalyx.com")
MOCO_API_KEY          = _env("MOCO_API_KEY")
ROBLOXWATCHER_API_KEY = _env("ROBLOXWATCHER_API_KEY", "ROBLOXWATCHERFREEKEY")
BLOXYCLEANER_API_KEY  = _env("BLOXYCLEANER_API_KEY", "")
BLOXYCLEANER_BASE     = _env("BLOXYCLEANER_BASE", "https://api.bloxycleaner.xyz")
DISABLED_APIS         = [x.strip().upper() for x in _env("DISABLED_APIS").split(",") if x.strip()]

EMBED_COLOR = 0x2B2D31
DIVIDER     = "━" * 26

ROTECTOR_FLAG_LABELS = {0: "Clear", 1: "Flagged", 2: "Confirmed", 3: "Mixed", 4: "Past Offender"}
SCORE_BADGE_MAP = {
    "nsfw_content": ("NSFW Content", 0xff0000),
    "exploiting":   ("Exploiting",   0xff6b00),
    "scam":         ("Scam",         0xffaa00),
    "spam":         ("Spam",         0xffff00),
}
FALLBACK_BADGES = [("Flagged", 0xff0000)]
