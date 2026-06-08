from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class AggregateResult:
    discord_id:              str
    roblox_id:               Optional[int]   = None
    # TASE
    tase_score:              Optional[float] = None
    tase_score_breakdown:    dict            = field(default_factory=dict)
    tase_guilds:             list            = field(default_factory=list)
    tase_nsfw_records:       list            = field(default_factory=list)
    tase_guilds_count:       int             = 0
    # RobloxWatcher
    rw_condo_servers:        list            = field(default_factory=list)
    rw_exploit_servers:      list            = field(default_factory=list)
    rw_condo_count:          int             = 0
    rw_exploit_count:        int             = 0
    # Rotector
    rotector_flag_type:      Optional[int]   = None
    rotector_confidence:     Optional[float] = None
    rotector_reasons:        list            = field(default_factory=list)
    rotector_flagged_friends: list           = field(default_factory=list)
    rotector_flagged_groups:  list           = field(default_factory=list)
    # Moco-co
    moco_group_count:        Optional[int]   = None
    moco_group_types:        list            = field(default_factory=list)
    moco_groups:             list            = field(default_factory=list)
    # BloxyCleaner
    bloxycleaner_flagged:    bool            = False
    bloxycleaner_servers:    list            = field(default_factory=list)
    # Meta
    sources_flagged:         list            = field(default_factory=list)
    sources_checked:         list            = field(default_factory=list)
    errors:                  list            = field(default_factory=list)
    created_at:              str             = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def is_empty(self) -> bool:
        return (
            not self.tase_guilds_count
            and not self.rw_condo_count
            and not self.rw_exploit_count
            and self.rotector_flag_type in (None, 0)
            and not self.bloxycleaner_flagged
            and not self.moco_group_count
        )
