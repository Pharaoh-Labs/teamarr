"""{exception_keyword} wildcard in channel-group/profile patterns, plus the
untagged label that stands in for channels no keyword matched.
"""

from unittest.mock import patch

import pytest

from teamarr.consumers.lifecycle.dynamic_resolver import DynamicResolver
from teamarr.consumers.lifecycle.naming import ChannelNaming
from teamarr.database.channels import keyword_display_value
from teamarr.database.settings import get_dispatcharr_settings, update_dispatcharr_settings


@pytest.fixture
def resolver():
    r = DynamicResolver()
    r._initialized = True
    r._sport_display_names = {"rugby": "Rugby"}
    r._league_aliases = {"eng.1": "Premier League"}
    # Group/profile ids are the created name, so assertions read the resolved text.
    with (
        patch.object(r, "_get_or_create_group", side_effect=lambda n: n),
        patch.object(r, "_get_or_create_profile", side_effect=lambda n: n),
    ):
        yield r


class TestPatternToken:
    def test_token_resolves(self, resolver):
        assert (
            resolver.resolve_channel_group(
                "{exception_keyword}: {sport}", 7, "rugby", None, exception_keyword="Spanish"
            )
            == "Spanish: Rugby"
        )

    def test_league_override_style_pattern(self, resolver):
        assert (
            resolver.resolve_channel_group(
                "{exception_keyword}: {league}", 7, "soccer", "eng.1", exception_keyword="ES"
            )
            == "ES: Premier League"
        )

    @pytest.mark.parametrize("keyword", [None, ""])
    def test_empty_keyword_falls_back_to_static_group(self, resolver, keyword):
        # No keyword and no untagged label: creating "{exception_keyword}: Rugby"
        # or ": Rugby" would be worse than the configured static group.
        assert (
            resolver.resolve_channel_group(
                "{exception_keyword}: {sport}", 7, "rugby", None, exception_keyword=keyword
            )
            == 7
        )

    def test_patterns_without_token_ignore_keyword(self, resolver):
        assert (
            resolver.resolve_channel_group(
                "{sport}", 7, "rugby", None, exception_keyword="Spanish"
            )
            == "Rugby"
        )

    def test_profile_pattern(self, resolver):
        assert resolver.resolve_channel_profiles(
            ["{exception_keyword} | {sport}"], "rugby", None, exception_keyword="ES"
        ) == ["ES | Rugby"]

    def test_profile_pattern_skipped_without_keyword(self, resolver):
        assert (
            resolver.resolve_channel_profiles(
                ["{exception_keyword} | {sport}"], "rugby", None
            )
            == []
        )


class TestDisplayValue:
    @pytest.mark.parametrize(
        ("keyword", "label", "expected"),
        [
            ("ES", "EN", "ES"),
            (None, "EN", "EN"),
            (None, None, ""),
            ("", None, ""),
            ("ES", None, "ES"),
        ],
    )
    def test_keyword_display_value(self, keyword, label, expected):
        assert keyword_display_value(keyword, label) == expected


class TestUntaggedLabelSetting:
    def test_round_trip_and_clear(self, db_conn):
        assert get_dispatcharr_settings(db_conn).untagged_keyword_label is None
        update_dispatcharr_settings(db_conn, untagged_keyword_label="EN")
        assert get_dispatcharr_settings(db_conn).untagged_keyword_label == "EN"
        update_dispatcharr_settings(db_conn, untagged_keyword_label=None)
        assert get_dispatcharr_settings(db_conn).untagged_keyword_label is None

    def test_omitted_leaves_label_alone(self, db_conn):
        update_dispatcharr_settings(db_conn, untagged_keyword_label="EN")
        update_dispatcharr_settings(db_conn, cleanup_unused_logos=True)
        assert get_dispatcharr_settings(db_conn).untagged_keyword_label == "EN"


class TestNamingValue:
    """Lifecycle name/logo path: the label feeds {exception_keyword} only for
    untagged channels, and never touches the real keyword."""

    @pytest.fixture
    def naming(self, db_factory):
        n = ChannelNaming.__new__(ChannelNaming)
        n._db_factory = db_factory
        return n

    def test_untagged_without_label_is_empty(self, naming):
        assert naming._keyword_template_value(None) == ""

    def test_untagged_with_label(self, naming, db_conn):
        update_dispatcharr_settings(db_conn, untagged_keyword_label="EN")
        db_conn.commit()
        assert naming._keyword_template_value(None) == "EN"

    def test_tagged_unaffected_by_label(self, naming, db_conn):
        update_dispatcharr_settings(db_conn, untagged_keyword_label="EN")
        db_conn.commit()
        assert naming._keyword_template_value("ES") == "ES"


# The two lifecycle templates the label has to render the same way in the
# Dispatcharr channel name and the XMLTV display name.
_TOKEN_NAME = "{exception_keyword}: {away_team} @ {home_team}"
_PLAIN_NAME = "{away_team} @ {home_team}"


def _real_event():
    from datetime import UTC, datetime

    from teamarr.core.types import Event, EventStatus, Team

    def team(id_, name, abbrev):
        return Team(
            id=id_, provider="espn", name=name, short_name=name,
            abbreviation=abbrev, league="eng.1", sport="soccer",
        )

    return Event(
        id="401", provider="espn", name="Arsenal at Chelsea", short_name="ARS @ CHE",
        start_time=datetime(2026, 9, 26, 15, 0, tzinfo=UTC),
        home_team=team("1", "Chelsea", "CHE"), away_team=team("2", "Arsenal", "ARS"),
        status=EventStatus(state="pre"), league="eng.1", sport="soccer",
    )


def _frozen_service():
    """Sports service stand-in: no enrichment, stats, or odds."""
    from unittest.mock import MagicMock

    service = MagicMock()
    service.enrich_event_preview.side_effect = lambda e: e
    service.refresh_event_status.side_effect = lambda e: e
    service.get_team_stats.return_value = None
    return service


@pytest.fixture
def league_service(db_factory):
    from teamarr.services import league_mappings as lm

    prior = lm._league_mapping_service
    lm.init_league_mapping_service(db_factory)
    yield
    lm._league_mapping_service = prior


@pytest.fixture
def lifecycle(db_factory):
    from unittest.mock import MagicMock

    from teamarr.consumers.lifecycle.service import ChannelLifecycleService

    return ChannelLifecycleService(
        db_factory=db_factory,
        sports_service=_frozen_service(),
        channel_manager=MagicMock(),
        logo_manager=MagicMock(),
        epg_manager=MagicMock(),
    )


def _set_label(db_conn, label):
    update_dispatcharr_settings(db_conn, untagged_keyword_label=label)
    db_conn.commit()


def _epg_channel(label, keyword, name_format, logo_url=None):
    from teamarr.consumers.event_epg import EventEPGGenerator, EventEPGOptions
    from teamarr.database.templates import EventTemplateConfig

    options = EventEPGOptions(
        template=EventTemplateConfig(
            channel_name_format=name_format, event_channel_logo_url=logo_url
        ),
        untagged_keyword_label=label,
    )
    match = {"stream": {"name": "Arsenal v Chelsea"}, "event": _real_event()}
    if keyword:
        match["_exception_keyword"] = keyword
    generator = EventEPGGenerator(_frozen_service())
    _, channels = generator.generate_for_matched_streams([match], options)
    return channels[0]


@pytest.mark.usefixtures("league_service")
class TestUntaggedLabelInNames:
    """Channel name, logo URL and XMLTV display name all render the label for
    an untagged channel, and none of them changes the tvg-id."""

    def test_untagged_with_label_uses_it(self, lifecycle, db_conn):
        _set_label(db_conn, "EN")
        name = lifecycle._generate_channel_name(
            _real_event(), {"event_channel_name": _TOKEN_NAME}, None
        )
        assert name == "EN: Arsenal @ Chelsea"
        assert _epg_channel("EN", None, _TOKEN_NAME).name == name

    def test_untagged_without_label_matches_today(self, lifecycle):
        name = lifecycle._generate_channel_name(
            _real_event(), {"event_channel_name": _PLAIN_NAME}, None
        )
        assert name == "Arsenal @ Chelsea"
        assert _epg_channel(None, None, _PLAIN_NAME).name == name

    def test_label_never_auto_appended(self, lifecycle, db_conn):
        # The "(Keyword)" suffix is for real keywords; an untagged channel
        # whose template doesn't use the token must not become "... (EN)".
        _set_label(db_conn, "EN")
        name = lifecycle._generate_channel_name(
            _real_event(), {"event_channel_name": _PLAIN_NAME}, None
        )
        assert name == "Arsenal @ Chelsea"
        assert _epg_channel("EN", None, _PLAIN_NAME).name == name

    def test_tagged_channel_ignores_label(self, lifecycle, db_conn):
        _set_label(db_conn, "EN")
        token = lifecycle._generate_channel_name(
            _real_event(), {"event_channel_name": _TOKEN_NAME}, "ES"
        )
        plain = lifecycle._generate_channel_name(
            _real_event(), {"event_channel_name": _PLAIN_NAME}, "ES"
        )
        assert token == "ES: Arsenal @ Chelsea"
        assert plain == "Arsenal @ Chelsea (ES)"
        assert _epg_channel("EN", "ES", _TOKEN_NAME).name == token
        assert _epg_channel("EN", "ES", _PLAIN_NAME).name == plain

    def test_logo_url(self, lifecycle, db_conn):
        _set_label(db_conn, "EN")
        url = "https://logos.example/{exception_keyword}.png"
        assert (
            lifecycle._resolve_logo_url(_real_event(), {"event_channel_logo_url": url}, None)
            == "https://logos.example/EN.png"
        )
        assert _epg_channel("EN", None, _PLAIN_NAME, logo_url=url).icon == (
            "https://logos.example/EN.png"
        )

    @pytest.mark.parametrize("keyword", [None, "ES"])
    def test_tvg_id_unchanged_by_label(self, keyword):
        assert (
            _epg_channel("EN", keyword, _TOKEN_NAME).channel_id
            == _epg_channel(None, keyword, _TOKEN_NAME).channel_id
        )


class TestSyncResolvesSameGroup:
    """The syncer re-resolves the group every run from the stored keyword; it
    must land where the creator put the channel or the channel flips groups."""

    @pytest.mark.parametrize(
        ("stored_keyword", "label", "expected"),
        [
            ("ES", "EN", "ES: Rugby"),
            (None, "EN", "EN: Rugby"),
            (None, None, 7),
        ],
    )
    def test_sync_matches_create(
        self, lifecycle, resolver, db_conn, stored_keyword, label, expected
    ):
        from tests.fakes import FakeManagedChannel, make_event

        update_dispatcharr_settings(
            db_conn,
            default_channel_group_mode="{exception_keyword}: {sport}",
            default_channel_group_id=7,
            untagged_keyword_label=label,
        )
        db_conn.commit()

        # What the creator resolves for the same keyword and settings
        created = resolver.resolve_channel_group(
            "{exception_keyword}: {sport}", 7, "rugby", None,
            exception_keyword=keyword_display_value(stored_keyword, label),
        )
        assert created == expected

        lifecycle._dynamic_resolver = resolver
        with (
            patch.object(
                resolver, "resolve_channel_group", wraps=resolver.resolve_channel_group
            ) as spy,
            patch.object(lifecycle, "_generate_channel_name", return_value="n"),
            patch.object(lifecycle, "_sync_channel_profiles"),
            patch.object(lifecycle, "_sync_channel_logo"),
            patch.object(lifecycle, "_sync_stream_profile"),
        ):
            lifecycle._sync_channel_settings(
                conn=db_conn,
                existing=FakeManagedChannel(exception_keyword=stored_keyword),
                stream={"id": 1},
                event=make_event(sport="rugby", league=None),
                group_config={},
                template=None,
            )
            synced = resolver.resolve_channel_group(**spy.call_args_list[0].kwargs)
        assert spy.call_count == 2  # the sync call, plus the re-run just above
        assert synced == created
