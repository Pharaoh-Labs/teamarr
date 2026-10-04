""""Only when" conditions on stream priority rules (#539).

A team's own channel is attached to every one of its games, including the
exclusive national ones where it shows nothing. No fixed score can fix that:
the same stream must lead on a normal night and trail on a dark one. A rule
can now carry a condition on the channel's game — no local broadcast listed,
or a season type — and matches only while it holds. Unknown never holds.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.consumers.lifecycle.service import ChannelLifecycleService
from teamarr.database import get_db, init_db
from teamarr.database.channels import (
    add_stream_to_channel,
    compute_stream_priority_from_rules,
    create_managed_channel,
    get_channel_streams,
    reorder_channel_streams,
)
from teamarr.database.channels.types import ManagedChannelStream
from teamarr.database.groups import create_group
from teamarr.database.settings import get_stream_ordering_settings
from teamarr.database.settings.types import StreamOrderingRule
from teamarr.database.settings.update import update_stream_ordering_rules
from teamarr.services.stream_ordering import (
    BAND_STRIDE,
    NO_MATCH_PRIORITY,
    GameContext,
    StreamOrderingService,
)
from teamarr.utilities.broadcasts import has_local_broadcast
from tests.fakes import FakeManagedChannel, make_event

BASELINE = NO_MATCH_PRIORITY * BAND_STRIDE

# The reporter's rule: the team's own channel sinks on a dark night.
DEMOTE_TEAM_WHEN_DARK = StreamOrderingRule(
    "stream_type", "team", 99, mode="score", points=-20000, condition="no_local_broadcast"
)


def _team_stream():
    return ManagedChannelStream(
        id=1, managed_channel_id=1, dispatcharr_stream_id=1,
        stream_name="MLB | Milwaukee Brewers", match_type="team",
    )


def _priority(rule, **context):
    return StreamOrderingService([rule], context=GameContext(**context)).compute_priority(
        _team_stream()
    )


class TestLocalBroadcastFact:
    """What the listing says, measured against MLB's 2026 Brewers schedule."""

    def _event(self, markets):
        return SimpleNamespace(broadcast_markets=markets)

    def test_an_ordinary_game_has_one(self):
        event = self._event({"MLB.TV": "national", "Brewers.TV": "away", "MASN": "home"})
        assert has_local_broadcast(event) is True

    def test_a_national_game_simulcast_locally_still_has_one(self):
        # BOS @ TB, 2026-09-18: both local broadcasters filed under 'home'
        event = self._event(
            {"ESPN Unlmtd": "national", "MLB.TV": "national", "Rays.TV": "home", "NESN": "home"}
        )
        assert has_local_broadcast(event) is True

    def test_an_exclusive_national_game_has_none(self):
        # MIL @ BAL, 2026-09-20
        assert has_local_broadcast(self._event({"Peacock": "national"})) is False

    def test_no_listing_is_unknown_not_none(self):
        assert has_local_broadcast(self._event({})) is None
        assert has_local_broadcast(SimpleNamespace()) is None


class TestConditionMatching:
    def test_no_local_broadcast_fires_only_on_a_dark_night(self):
        assert _priority(DEMOTE_TEAM_WHEN_DARK, has_local_broadcast=False) == BASELINE + 20000
        assert _priority(DEMOTE_TEAM_WHEN_DARK, has_local_broadcast=True) == BASELINE

    def test_unknown_never_fires(self):
        assert _priority(DEMOTE_TEAM_WHEN_DARK) == BASELINE
        # ...and a service built with no context at all behaves the same
        assert StreamOrderingService([DEMOTE_TEAM_WHEN_DARK]).compute_priority(
            _team_stream()
        ) == BASELINE

    @pytest.mark.parametrize("season", ["preseason", "regular", "postseason"])
    def test_season_condition_matches_its_own_season_only(self, season):
        rule = StreamOrderingRule(
            "stream_type", "team", 99, mode="score", points=-500, condition=f"season:{season}"
        )
        for actual in ("preseason", "regular", "postseason", None):
            expected = BASELINE + 500 if actual == season else BASELINE
            assert _priority(rule, season_type=actual) == expected

    def test_the_stream_must_still_match_the_rule(self):
        event_stream = ManagedChannelStream(
            id=2, managed_channel_id=1, dispatcharr_stream_id=2,
            stream_name="Brewers vs Orioles", match_type="event",
        )
        service = StreamOrderingService(
            [DEMOTE_TEAM_WHEN_DARK], context=GameContext(has_local_broadcast=False)
        )
        assert service.compute_priority(event_stream) == BASELINE

    def test_a_conditioned_priority_rule_only_sets_the_band_when_met(self):
        rule = StreamOrderingRule(
            "stream_type", "team", 5, mode="priority", condition="season:postseason"
        )
        assert _priority(rule, season_type="postseason") == 5
        assert _priority(rule, season_type="regular") == NO_MATCH_PRIORITY

    def test_an_unrecognised_condition_matches_nothing(self):
        rule = StreamOrderingRule(
            "stream_type", "team", 99, mode="score", points=-500, condition="full_moon"
        )
        assert _priority(rule, has_local_broadcast=False, season_type="regular") == BASELINE

    def test_the_explainer_reports_the_condition(self):
        service = StreamOrderingService(
            [DEMOTE_TEAM_WHEN_DARK], context=GameContext(has_local_broadcast=False)
        )
        matched = service.evaluate_rules(_team_stream())
        assert [(m.type, m.condition) for m in matched] == [
            ("stream_type", "no_local_broadcast"),
            ("catch_all", ""),
        ]

    def test_a_dark_night_flips_the_order(self):
        """The whole point: same two streams, opposite order, by the game."""
        rules = [
            StreamOrderingRule("stream_type", "team", 99, mode="score", points=10000),
            DEMOTE_TEAM_WHEN_DARK,
        ]
        unlabelled = ManagedChannelStream(
            id=2, managed_channel_id=1, dispatcharr_stream_id=2,
            stream_name="Brewers vs Orioles", match_type="event",
        )
        normal = StreamOrderingService(rules, context=GameContext(has_local_broadcast=True))
        dark = StreamOrderingService(rules, context=GameContext(has_local_broadcast=False))

        assert normal.compute_priority(_team_stream()) < normal.compute_priority(unlabelled)
        assert dark.compute_priority(_team_stream()) > dark.compute_priority(unlabelled)


class TestGameContextFromChannel:
    def test_reads_a_dataclass_a_dict_and_a_row(self, db_conn):
        fake = SimpleNamespace(season_type="postseason", has_local_broadcast=0)
        assert GameContext.from_channel(fake) == GameContext("postseason", False)
        assert GameContext.from_channel({"season_type": "", "has_local_broadcast": 1}) == (
            GameContext(None, True)
        )
        row = db_conn.execute("SELECT 'regular' AS season_type, NULL AS has_local_broadcast")
        assert GameContext.from_channel(row.fetchone()) == GameContext("regular", None)

    def test_a_channel_without_the_facts_is_unknown(self):
        assert GameContext.from_channel(None) == GameContext()
        assert GameContext.from_channel(FakeManagedChannel()) == GameContext()


@pytest.fixture
def ruled_db(db_conn):
    update_stream_ordering_rules(
        db_conn,
        [{"type": "stream_type", "value": "team", "priority": 99, "mode": "score",
          "points": -20000, "condition": "no_local_broadcast"}],
    )
    db_conn.commit()
    return db_conn


class TestStorage:
    def test_the_condition_round_trips(self, ruled_db):
        rule = get_stream_ordering_settings(ruled_db).rules[0]
        assert rule.condition == "no_local_broadcast"

    def test_rules_saved_before_the_field_existed_read_as_always(self, db_conn):
        db_conn.execute(
            "UPDATE settings SET stream_ordering_rules = ? WHERE id = 1",
            ('[{"type": "regex", "value": "HD", "priority": 1}]',),
        )
        assert get_stream_ordering_settings(db_conn).rules[0].condition == ""

    def test_an_unknown_condition_is_dropped_on_save(self, db_conn):
        update_stream_ordering_rules(
            db_conn,
            [{"type": "regex", "value": "HD", "priority": 1, "condition": "full_moon"}],
        )
        assert get_stream_ordering_settings(db_conn).rules[0].condition == ""


class TestChannelPaths:
    """Every place a priority is computed must see the channel's game."""

    def _channel(self, conn, local):
        group = create_group(conn, name="MLB", leagues=["mlb"])
        channel_id = create_managed_channel(
            conn,
            event_epg_group_id=group,
            event_id="1",
            event_provider="espn",
            tvg_id="teamarr-event-1",
            channel_name="Brewers at Orioles",
            sport="baseball",
            league="mlb",
            has_local_broadcast=local,
        )
        add_stream_to_channel(conn, channel_id, 500, stream_name="MLB | Brewers",
                              match_type="team", priority=0)
        return channel_id

    def test_attach_time_priority_uses_the_game(self, ruled_db):
        dark = compute_stream_priority_from_rules(
            ruled_db, "MLB | Brewers", None, None, match_type="team", has_local_broadcast=False
        )
        normal = compute_stream_priority_from_rules(
            ruled_db, "MLB | Brewers", None, None, match_type="team", has_local_broadcast=True
        )
        assert (dark, normal) == (BASELINE + 20000, BASELINE)

    @pytest.mark.parametrize(("local", "expected"), [(False, BASELINE + 20000), (True, BASELINE)])
    def test_reorder_reads_the_stored_fact(self, ruled_db, local, expected):
        channel_id = self._channel(ruled_db, local)
        reorder_channel_streams(ruled_db, channel_id)
        assert get_channel_streams(ruled_db, channel_id)[0].priority == expected

    def test_sync_keeps_the_fact_current_and_never_blanks_it(self, db_factory, db_conn):
        lifecycle = ChannelLifecycleService(
            db_factory=db_factory,
            sports_service=MagicMock(),
            channel_manager=MagicMock(),
            logo_manager=MagicMock(),
            epg_manager=MagicMock(),
        )
        lifecycle._dynamic_resolver = MagicMock()

        def sync(event, existing):
            with (
                patch.object(lifecycle, "_generate_channel_name", return_value="n"),
                patch.object(lifecycle, "_sync_channel_profiles"),
                patch.object(lifecycle, "_sync_channel_logo"),
                patch.object(lifecycle, "_sync_stream_profile"),
                patch("teamarr.database.channels.update_managed_channel") as update,
            ):
                lifecycle._sync_channel_settings(
                    conn=db_conn, existing=existing, stream={"id": 1}, event=event,
                    group_config={}, template=None,
                )
            written = {}
            for call in update.call_args_list:
                written.update(call.args[2])
            return written

        picked_up_nationally = make_event(sport="baseball", league="mlb")
        picked_up_nationally.broadcast_markets = {"Peacock": "national"}
        assert sync(picked_up_nationally, FakeManagedChannel())["has_local_broadcast"] is False

        unreadable = make_event(sport="baseball", league="mlb")
        assert "has_local_broadcast" not in sync(unreadable, FakeManagedChannel())


class TestApi:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
        init_db()
        return TestClient(app)

    def _rule(self, **extra):
        return {"type": "stream_type", "value": "team", "priority": 99, "mode": "score",
                "points": -20000, **extra}

    def test_put_and_get_carry_the_condition(self, client):
        resp = client.put(
            "/api/v1/settings/stream-ordering",
            json={"rules": [self._rule(condition="no_local_broadcast")]},
        )
        assert resp.status_code == 200, resp.text
        rules = client.get("/api/v1/settings/stream-ordering").json()["rules"]
        assert rules[0]["condition"] == "no_local_broadcast"

    def test_leaving_it_out_means_always(self, client):
        client.put("/api/v1/settings/stream-ordering", json={"rules": [self._rule()]})
        assert client.get("/api/v1/settings/stream-ordering").json()["rules"][0]["condition"] == ""

    def test_an_unknown_condition_is_rejected(self, client):
        resp = client.put(
            "/api/v1/settings/stream-ordering",
            json={"rules": [self._rule(condition="full_moon")]},
        )
        assert resp.status_code == 400

    def test_a_scoped_ruleset_carries_it_too(self, client):
        resp = client.post(
            "/api/v1/settings/stream-ordering/scopes",
            json={"name": "MLB", "sports": [], "leagues": ["mlb"],
                  "rules": [self._rule(condition="season:postseason")],
                  "use_global_scoring": True, "use_global_priority": True},
        )
        assert resp.status_code in (200, 201), resp.text
        with get_db() as conn:
            from teamarr.database.stream_ordering_scopes import resolve_stream_ordering_rules

            rules, scope = resolve_stream_ordering_rules(conn, "baseball", "mlb")
        assert scope is not None
        assert [r.condition for r in rules] == ["season:postseason"]
