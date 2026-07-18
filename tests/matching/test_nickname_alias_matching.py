"""Nickname short names, alias normalization, honest DATE_MISMATCH (#480).

Built from a remote user's log: 'MLB 13 | Cardinals x D-backs
start:2026-07-18 02:40' failed as date_mismatch while the real defects were
(1) their 'D-backs' alias stored raw-lowercased but looked up normalized,
(2) fuzzy scoring never consulting ESPN's short_name ('D-backs'), and
(3) the DATE_MISMATCH reason firing for unrelated date-gated candidates.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import CustomRegexConfig, classify_stream
from teamarr.consumers.matching.normalizer import normalize_for_matching
from teamarr.consumers.matching.result import FailedReason, MatchMethod, ResultCategory
from teamarr.consumers.matching.team_matcher import MatchContext, normalize_text
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_team_matcher

TODAY = datetime.now(UTC).date()


def _team(name: str, abbr: str, short_name: str | None = None) -> Team:
    return Team(
        id="t-" + abbr.lower(),
        provider="espn",
        name=name,
        short_name=short_name or name.split()[-1],
        abbreviation=abbr,
        league="mlb",
        sport="baseball",
    )


CARDINALS = _team("St. Louis Cardinals", "STL", "Cardinals")
DBACKS = _team("Arizona Diamondbacks", "ARI", "Diamondbacks")


def _event(days_from_today: int = 0, eid: str = "evt-1") -> Event:
    start = datetime.combine(
        TODAY + timedelta(days=days_from_today), datetime.min.time(), tzinfo=UTC
    ).replace(hour=19)
    return Event(
        id=eid,
        provider="espn",
        name="St. Louis Cardinals vs Arizona Diamondbacks",
        short_name="Cardinals vs D-backs",
        start_time=start,
        home_team=CARDINALS,
        away_team=DBACKS,
        status=EventStatus(state="scheduled"),
        league="mlb",
        sport="baseball",
    )


def _match(stream_name: str, events: list[Event], matcher=None, cfg=None):
    classified = classify_stream(stream_name, custom_regex=cfg)
    matcher = matcher or make_team_matcher()
    ctx = MatchContext(
        stream_name=stream_name,
        stream_id=1,
        group_id=1,
        target_date=TODAY,
        generation=1,
        user_tz=ZoneInfo("UTC"),
        classified=classified,
        team1=classified.team1,
        team2=classified.team2,
    )
    return matcher._match_against_events(ctx, events, "mlb")


class TestShortNameScoring:
    def test_dbacks_matches_out_of_the_box_via_builtin_alias(self):
        # ESPN has no "D-backs" string anywhere (short_name scores ~53), so
        # the official club nickname is a BUILTIN alias (#480) — no user
        # alias required
        outcome = _match("Cardinals x D-backs", [_event()])
        assert outcome.category == ResultCategory.MATCHED

    def test_dbacks_no_hyphen_variant_matches(self):
        outcome = _match("Cardinals x Dbacks", [_event()])
        assert outcome.category == ResultCategory.MATCHED


class TestAliasNormalization:
    def test_punctuated_user_alias_fires(self):
        # Alias stored as the user typed it ('D-backs'); lookup side is
        # normalize_for_matching output ('d backs') — keys must agree
        matcher = make_team_matcher()
        matcher._user_aliases = {
            (normalize_text("D-backs"), "mlb"): normalize_text("Arizona Diamondbacks")
        }
        resolved = matcher._resolve_alias(normalize_for_matching("D-backs"), "mlb")
        assert resolved == "arizona diamondbacks"

    def test_punctuated_builtin_alias_fires(self):
        # 'miami-oh' is a builtin alias key with punctuation — dead before #480
        matcher = make_team_matcher()
        resolved = matcher._resolve_alias(normalize_for_matching("Miami-OH"), None)
        assert resolved == "miami oh"


class TestHonestDateMismatch:
    CFG = None

    def _iso_cfg(self, *sample_streams: str):
        cfg = CustomRegexConfig(
            date_pattern=r"(?P<date>\d{4}-\d{2}-\d{2})", date_enabled=True
        )
        # Mirror the pipeline: match_all learns the format from the batch
        # before matching — that's what makes a blob-pattern date trusted
        cfg.learn_date_format(list(sample_streams))
        return cfg

    def test_utc_day_boundary_tolerated(self):
        # Stream stamped with tomorrow's UTC date for tonight's game (the
        # remote user's shape) — ±1 tolerance must let it match. The D-backs
        # side rides the user's alias, exactly like their setup.
        matcher = make_team_matcher()
        matcher._user_aliases = {
            (normalize_text("d-backs"), "mlb"): normalize_text("Arizona Diamondbacks"),
        }
        stamp = (TODAY + timedelta(days=1)).isoformat()
        name = f"Cardinals x D-backs {stamp}"
        outcome = _match(name, [_event()], matcher=matcher, cfg=self._iso_cfg(name))
        assert outcome.category == ResultCategory.MATCHED

    def test_date_mismatch_only_when_teams_matched(self):
        # Teams DO match an event, but it's 5 days from the stream date →
        # honest DATE_MISMATCH
        stamp = TODAY.isoformat()
        name = f"Cardinals x Diamondbacks {stamp}"
        outcome = _match(name, [_event(days_from_today=5)], cfg=self._iso_cfg(name))
        assert outcome.category == ResultCategory.FAILED
        assert outcome.failed_reason == FailedReason.DATE_MISMATCH

    def test_team_failure_not_blamed_on_date(self):
        # Teams match NOTHING; other-dated games exist in the window. The
        # old logic labeled this date_mismatch — it must say no_event_found
        stamp = TODAY.isoformat()
        name = f"Wanderers x Nomads {stamp}"
        outcome = _match(
            name,
            [_event(days_from_today=0), _event(days_from_today=5, eid="evt-2")],
            cfg=self._iso_cfg(name),
        )
        assert outcome.category == ResultCategory.FAILED
        assert outcome.failed_reason == FailedReason.NO_EVENT_FOUND


class TestAliasEndToEnd:
    def test_alias_match_wins_at_full_confidence(self):
        matcher = make_team_matcher()
        matcher._user_aliases = {
            (normalize_text("D-backs"), "mlb"): normalize_text("Arizona Diamondbacks"),
            (normalize_text("Cards"), "mlb"): normalize_text("St. Louis Cardinals"),
        }
        outcome = _match("Cards x D-backs", [_event()], matcher=matcher)
        assert outcome.category == ResultCategory.MATCHED
        assert outcome.match_method == MatchMethod.ALIAS

    def test_single_sided_alias_carries_its_side(self):
        # THE remote-user case (#480 round 2): only 'D-backs' is aliased;
        # 'Cardinals' matches by fuzz. One alias must be enough — requiring
        # both sides to alias made a lone alias structurally useless.
        matcher = make_team_matcher()
        matcher._user_aliases = {
            (normalize_text("D-backs"), "mlb"): normalize_text("Arizona Diamondbacks"),
        }
        outcome = _match("Cardinals x D-backs", [_event()], matcher=matcher)
        assert outcome.category == ResultCategory.MATCHED



    def test_alias_for_wrong_team_does_not_help(self):
        # Canonical must actually be one of the event's teams
        matcher = make_team_matcher()
        matcher._user_aliases = {
            (normalize_text("D-backs"), "mlb"): normalize_text("Colorado Rockies"),
        }
        outcome = _match("Cardinals x D-backs", [_event()], matcher=matcher)
        assert outcome.category == ResultCategory.FAILED
