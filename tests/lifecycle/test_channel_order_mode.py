"""Opt-in channel order: start time ahead of Sport & League order (#934).

The order inside a block was fixed: sport, then league, then start time. A
single "what's on now" group therefore listed games by league, not by when
they start. ``channel_order_mode = 'start_time'`` moves start time ahead of
the sport and league order. The default is unchanged, and nothing moves
unless the setting is switched.
"""

import pytest

from teamarr.database import channel_numbers as cn
from teamarr.database.channels import create_managed_channel
from teamarr.database.groups import create_group
from teamarr.database.settings import (
    get_channel_numbering_settings,
    update_channel_numbering_settings,
)


@pytest.fixture
def slate(db_conn):
    """Three games: NFL at 20:00, NBA at 18:00 and 20:00. Football is listed
    ahead of basketball in the Sport & League order."""
    group = create_group(db_conn, name="Live", leagues=["nfl", "nba"])
    db_conn.execute("DELETE FROM channel_sort_priorities")
    db_conn.executemany(
        "INSERT INTO channel_sort_priorities (sport, league_code, sort_priority) VALUES (?, ?, ?)",
        [("football", None, 0), ("football", "nfl", 1), ("basketball", None, 2),
         ("basketball", "nba", 3)],
    )

    def channel(event_id, sport, league, start, keyword=None, home="A", away="B"):
        return create_managed_channel(
            conn=db_conn, event_epg_group_id=group, event_id=event_id, event_provider="espn",
            tvg_id=f"tvg-{event_id}-{keyword}", channel_name=f"{league}-{event_id}-{keyword}",
            sport=sport, league=league, home_team=home, away_team=away,
            event_date=start, exception_keyword=keyword,
        )

    ids = {
        "nfl_late": channel("1", "football", "nfl", "2026-10-04T20:00:00+00:00"),
        "nba_early": channel("2", "basketball", "nba", "2026-10-04T18:00:00+00:00"),
        "nba_late": channel("3", "basketball", "nba", "2026-10-04T20:00:00+00:00"),
        "nba_early_4k": channel("2", "basketball", "nba", "2026-10-04T18:00:00+00:00", "4K"),
    }
    db_conn.commit()
    return ids


def _order(conn, ids):
    by_id = {v: k for k, v in ids.items()}
    return [by_id[c["id"]] for c in cn.get_all_channels_sorted(conn)]


def test_default_is_sport_and_league_first(db_conn, slate):
    assert get_channel_numbering_settings(db_conn).channel_order_mode == "sport_league"
    assert _order(db_conn, slate) == ["nfl_late", "nba_early", "nba_early_4k", "nba_late"]


def test_start_time_first_lists_games_as_they_begin(db_conn, slate):
    assert update_channel_numbering_settings(db_conn, channel_order_mode="start_time")
    # 18:00 game and its keyword channel together, then the 20:00 games with
    # the Sport & League order settling the tie (football before basketball).
    assert _order(db_conn, slate) == ["nba_early", "nba_early_4k", "nfl_late", "nba_late"]


def test_switching_back_restores_the_old_order(db_conn, slate):
    update_channel_numbering_settings(db_conn, channel_order_mode="start_time")
    update_channel_numbering_settings(db_conn, channel_order_mode="sport_league")
    assert _order(db_conn, slate) == ["nfl_late", "nba_early", "nba_early_4k", "nba_late"]


def test_everything_priority_team_still_leads(db_conn, slate):
    db_conn.execute("UPDATE managed_channels SET home_team = 'Detroit Lions' WHERE id = ?",
                    (slate["nfl_late"],))
    db_conn.execute(
        "INSERT INTO channel_priority_teams "
        "(provider, provider_team_id, team_name, league, sport, scope) "
        "VALUES ('espn', '8', 'Detroit Lions', 'nfl', 'football', 'all')"
    )
    update_channel_numbering_settings(db_conn, channel_order_mode="start_time")
    assert _order(db_conn, slate)[0] == "nfl_late"


def test_numbers_follow_the_order(db_conn, slate):
    update_channel_numbering_settings(db_conn, channel_order_mode="start_time")
    db_conn.commit()
    cn.reassign_all_channels(db_conn)
    numbers = {
        name: int(float(db_conn.execute(
            "SELECT channel_number FROM managed_channels WHERE id = ?", (cid,)
        ).fetchone()[0]))
        for name, cid in slate.items()
    }
    ordered = ["nba_early", "nba_early_4k", "nfl_late", "nba_late"]
    assert sorted(numbers, key=numbers.__getitem__) == ordered


def test_unknown_mode_is_refused(db_conn):
    assert update_channel_numbering_settings(db_conn, channel_order_mode="league") is False
    assert get_channel_numbering_settings(db_conn).channel_order_mode == "sport_league"


@pytest.mark.parametrize(
    ("stability", "armed"), [("gap", True), ("strict", True), ("compact", False)]
)
def test_changing_the_order_queues_a_relayout_in_sticky_modes(db_conn, stability, armed):
    update_channel_numbering_settings(db_conn, channel_stability_mode=stability)
    db_conn.execute("UPDATE settings SET force_channel_relayout_pending = 0")
    update_channel_numbering_settings(db_conn, channel_order_mode="start_time")
    pending = db_conn.execute("SELECT force_channel_relayout_pending FROM settings").fetchone()[0]
    assert bool(pending) is armed


def test_saving_the_same_order_does_not_queue_a_relayout(db_conn):
    update_channel_numbering_settings(db_conn, channel_stability_mode="gap")
    db_conn.execute("UPDATE settings SET force_channel_relayout_pending = 0")
    update_channel_numbering_settings(db_conn, channel_order_mode="sport_league")
    assert not db_conn.execute(
        "SELECT force_channel_relayout_pending FROM settings"
    ).fetchone()[0]
