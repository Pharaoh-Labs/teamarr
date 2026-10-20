"""ESPN provider constants."""

# Map ESPN status names to our canonical states
STATUS_MAP = {
    "STATUS_SCHEDULED": "scheduled",
    "STATUS_IN_PROGRESS": "live",
    "STATUS_HALFTIME": "live",
    "STATUS_END_PERIOD": "live",
    "STATUS_FINAL": "final",
    "STATUS_FINAL_OT": "final",
    "STATUS_FULL_TIME": "final",  # Soccer
    "STATUS_FULL_TIME_ET": "final",  # Soccer extra time
    # Soccer penalties: ESPN's real name is STATUS_FINAL_PEN (type id 47,
    # 'Final Score - After Penalties'; 2026 UCL final, UEL R16 — #916). The
    # STATUS_FULL_PEN entry was a guess that never matched; kept harmlessly.
    "STATUS_FINAL_PEN": "final",
    "STATUS_FULL_PEN": "final",
    "STATUS_ABANDONED": "cancelled",  # Soccer
    "STATUS_POSTPONED": "postponed",
    "STATUS_CANCELED": "cancelled",
    "STATUS_DELAYED": "scheduled",
}

# Sports that are tournament-based (no home/away teams)
TOURNAMENT_SPORTS = {"tennis", "golf", "racing"}
