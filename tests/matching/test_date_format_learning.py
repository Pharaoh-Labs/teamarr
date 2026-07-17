"""Date regex as format descriptor (#474).

The custom date regex says WHERE a source's date lives; the format is either
declared (month/day/year component groups) or learned from the whole batch.
A trusted date gates candidates (±1 day); an untrusted one only ranks them —
a misread date can no longer zero out a group's matching.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import (
    CustomRegexConfig,
    classify_stream,
    extract_date_with_custom_regex,
    infer_date_formats,
)
from teamarr.consumers.matching.result import FailedReason, ResultCategory
from teamarr.consumers.matching.team_matcher import MatchContext
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_team_matcher

TODAY = datetime.now(UTC).date()


def _fmt(d: date, fmt: str) -> str:
    return d.strftime(fmt)


# ---------------------------------------------------------------------------
# infer_date_formats
# ---------------------------------------------------------------------------


class TestInferDateFormats:
    def test_unambiguous_sample_proves_day_first(self):
        # A day > 12 anywhere in the batch pins the whole source to day-first
        samples = ["16/07/2026", "05/07/2026"]
        assert infer_date_formats(samples) == ["%d/%m/%Y"]

    def test_all_ambiguous_prefers_dates_near_today(self):
        # Consecutive dates around today: day-first lands them all in the
        # window; month-first scatters them across months
        samples = [
            _fmt(TODAY - timedelta(days=1), "%d/%m/%Y"),
            _fmt(TODAY, "%d/%m/%Y"),
            _fmt(TODAY + timedelta(days=1), "%d/%m/%Y"),
        ]
        result = infer_date_formats(samples)
        assert result is not None
        parsed = [datetime.strptime(s, result[0]).date() for s in samples]
        in_window = [abs((d - TODAY).days) <= 2 for d in parsed]
        assert all(in_window)

    def test_inconsistent_samples_return_none(self):
        assert infer_date_formats(["16/07/2026", "July 5"]) is None

    def test_empty_returns_none(self):
        assert infer_date_formats([]) is None


# ---------------------------------------------------------------------------
# Learning + provenance through the config
# ---------------------------------------------------------------------------


class TestLearnDateFormat:
    def test_blob_pattern_learns_and_trusts(self):
        cfg = CustomRegexConfig(
            date_pattern=r"(?P<date>\d{2}/\d{2}/\d{4})", date_enabled=True
        )
        cfg.learn_date_format(["A vs B 16/07/2026", "C vs D 05/07/2026"])
        assert cfg.learned_date_formats == ["%d/%m/%Y"]

        extracted, trusted = extract_date_with_custom_regex("C vs D 05/07/2026", cfg)
        assert extracted == date(2026, 7, 5)  # day-first, not May 7
        assert trusted is True

    def test_blob_pattern_without_learning_is_untrusted(self):
        cfg = CustomRegexConfig(
            date_pattern=r"(?P<date>\d{2}/\d{2}/\d{4})", date_enabled=True
        )
        extracted, trusted = extract_date_with_custom_regex("C vs D 05/07/2026", cfg)
        assert extracted == date(2026, 5, 7)  # US-first guess
        assert trusted is False

    def test_component_groups_are_declared_and_trusted(self):
        cfg = CustomRegexConfig(
            date_pattern=r"(?P<day>\d{2})/(?P<month>\d{2})/(?P<year>\d{4})",
            date_enabled=True,
        )
        # Learning is a no-op for declared formats
        cfg.learn_date_format(["C vs D 05/07/2026"])
        assert cfg.learned_date_formats is None

        extracted, trusted = extract_date_with_custom_regex("C vs D 05/07/2026", cfg)
        assert extracted == date(2026, 7, 5)
        assert trusted is True


# ---------------------------------------------------------------------------
# Matcher behavior: trusted gates (±1), untrusted ranks
# ---------------------------------------------------------------------------


def _team(name: str, abbr: str) -> Team:
    return Team(
        id="t-" + abbr.lower(),
        provider="espn",
        name=name,
        short_name=name,
        abbreviation=abbr,
        league="test",
        sport="hockey",
    )


def _event(start: datetime) -> Event:
    home, away = _team("Detroit Tigers", "DET"), _team("Minnesota Twins", "MIN")
    return Event(
        id="evt-1",
        provider="espn",
        name="Detroit Tigers vs Minnesota Twins",
        short_name="Tigers vs Twins",
        start_time=start,
        home_team=home,
        away_team=away,
        status=EventStatus(state="scheduled"),
        league="test",
        sport="hockey",
    )


def _match(stream_name: str, cfg: CustomRegexConfig | None, event: Event):
    classified = classify_stream(stream_name, custom_regex=cfg)
    matcher = make_team_matcher()
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
    return matcher._match_against_events(ctx, [event], "test")


def _cfg_learned(stream_names: list[str]) -> CustomRegexConfig:
    cfg = CustomRegexConfig(
        date_pattern=r"(?P<date>\d{2}/\d{2}/\d{4})", date_enabled=True
    )
    cfg.learn_date_format(stream_names)
    return cfg


class TestSoftDateFilter:
    def test_trusted_wrong_date_reports_date_mismatch(self):
        # Event 5 days from the stream's (trusted, learned) date → gated,
        # and the failure names the date instead of "no event found"
        event_dt = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC).replace(
            hour=19
        )
        stream_date = TODAY + timedelta(days=5)
        name = f"Tigers vs Twins {stream_date.strftime('%d/%m/%Y')}"
        proof = f"X vs Y {(TODAY + timedelta(days=13)).strftime('%d/%m/%Y')}"
        cfg = _cfg_learned([name, proof])

        outcome = _match(name, cfg, _event(event_dt))
        assert outcome.category == ResultCategory.FAILED
        assert outcome.failed_reason == FailedReason.DATE_MISMATCH

    def test_trusted_date_tolerates_one_day_boundary(self):
        # Provider labels a late game with the next day's date (tz boundary)
        event_dt = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC).replace(
            hour=23
        )
        stream_date = TODAY + timedelta(days=1)
        name = f"Tigers vs Twins {stream_date.strftime('%d/%m/%Y')}"
        proof = f"X vs Y {(TODAY + timedelta(days=13)).strftime('%d/%m/%Y')}"
        cfg = _cfg_learned([name, proof])

        outcome = _match(name, cfg, _event(event_dt))
        assert outcome.category == ResultCategory.MATCHED

    def test_untrusted_wrong_date_still_matches_by_teams(self):
        # No learnable format (one ambiguous sample, no day>12 proof, dates
        # far from today) → untrusted guess; a wildly wrong date must not
        # zero out team matching
        event_dt = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC).replace(
            hour=19
        )
        cfg = CustomRegexConfig(
            date_pattern=r"(?P<date>\d{2}/\d{2}/\d{4})", date_enabled=True
        )
        name = "Tigers vs Twins 05/01/2026"  # parses months away from event
        classified = classify_stream(name, custom_regex=cfg)
        assert classified.normalized.extracted_date_trusted is False

        outcome = _match(name, cfg, _event(event_dt))
        assert outcome.category == ResultCategory.MATCHED
