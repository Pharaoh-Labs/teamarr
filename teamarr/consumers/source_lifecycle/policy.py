"""The rules the source lifecycle runs by, read from settings (#1058).

One object, so the Sources page and the two passes read the same numbers:
the daily pass (discover, add, retire) and the per-generation pass (missing
groups, remove).
"""

from dataclasses import dataclass
from sqlite3 import Connection

# Defaults, also the values before the settings existed (#997).
DEFAULT_IDLE_DAYS = 14
DEFAULT_GONE_DAYS = 14
DEFAULT_MISSING_DELETE_DAYS = 0  # never
# A discovered source whose group name still names a subscribed league gets
# this much longer before it is switched off: the name is weak evidence that
# games come back.
NAMED_IDLE_GRACE_DAYS = 7


@dataclass(frozen=True)
class SourceLifecyclePolicy:
    discovery_enabled: bool = True
    auto_max_streams: int = 1000
    # Retire: a discovered source that matched nothing for this many days is
    # switched off (settings kept); +NAMED_IDLE_GRACE_DAYS when its name names
    # a subscribed league.
    idle_days: int = DEFAULT_IDLE_DAYS
    # Remove: a switched-off discovered source whose group has been gone from
    # Dispatcharr this many days is deleted.
    gone_days: int = DEFAULT_GONE_DAYS
    # Remove: a hand-made source whose group has been missing this many days
    # is deleted. 0 = never.
    missing_delete_days: int = DEFAULT_MISSING_DELETE_DAYS

    @property
    def idle_days_named(self) -> int:
        return self.idle_days + NAMED_IDLE_GRACE_DAYS


def load_policy(conn: Connection) -> SourceLifecyclePolicy:
    from teamarr.database.settings import get_scheduler_settings

    s = get_scheduler_settings(conn)
    return SourceLifecyclePolicy(
        discovery_enabled=s.source_discovery_mode != "off",
        auto_max_streams=s.source_discovery_auto_max_streams,
        idle_days=s.source_idle_days,
        gone_days=s.source_gone_days,
        missing_delete_days=s.source_missing_delete_days,
    )
