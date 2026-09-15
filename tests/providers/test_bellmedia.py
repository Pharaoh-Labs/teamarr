"""Bell Media provider normalization and routing tests."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import httpx

from teamarr.providers.bellmedia.client import BellMediaClient
from teamarr.providers.bellmedia.provider import BellMediaProvider

COMPETITORS = [
    {
        "competitorId": 93775,
        "name": "BC Lions",
        "club": "Lions",
        "shortName": "BC",
        "seoIdentifier": "bc-lions",
        "primaryColor": "F15623",
    },
    {
        "competitorId": 112939,
        "name": "Calgary Stampeders",
        "club": "Stampeders",
        "shortName": "CGY",
        "primaryColor": "E51937",
    },
]


def _event(*, event_id=13419712, event_date="2026-08-13", status="Final", **extra):
    event = {
        "eventId": event_id,
        "season": 2026,
        "date": event_date,
        "seasonTypeId": 1,
        "event": {
            "status": status,
            "venue": "McMahon Stadium",
            "top": {
                "competitorId": 93775,
                "location": "BC",
                "name": "Lions",
                "shortName": "BC",
                "score": 30,
            },
            "bottom": {
                "competitorId": 112939,
                "location": "Calgary",
                "name": "Stampeders",
                "shortName": "CGY",
                "score": 26,
            },
            "dateGMT": "2026-08-14T01:00:00",
            "formattedTime": "Final",
            "broadcast": "TSN",
            "broadcastStations": [{"callLetters": "TSN"}, {"callLetters": "TSN1"}],
        },
    }
    event.update(extra)
    return event


class _Mapping:
    def supports_league(self, league, provider):
        return league == "cfl" and provider == "bellmedia"

    def get_leagues_for_provider(self, provider):
        return [SimpleNamespace(league_code="cfl")] if provider == "bellmedia" else []


class _Client:
    def __init__(self, events=()):
        self.events = list(events)

    def supports_league(self, league):
        return league in {"cfl", "ohl", "pwhl"}

    def get_mapping(self, league):
        mappings = {
            "cfl": SimpleNamespace(sport="football", provider_league_id="cfl"),
            "ohl": SimpleNamespace(sport="hockey", provider_league_id="ohl"),
            "pwhl": SimpleNamespace(sport="hockey", provider_league_id="pwhl"),
        }
        return mappings.get(league)

    def get_competitors(self, league):
        return COMPETITORS if league == "cfl" else []

    def get_events_between(self, league, start, end):
        return [event for event in self.events if start <= date.fromisoformat(event["date"]) <= end]

    def get_event(self, league, event_id):
        return next((event for event in self.events if str(event["eventId"]) == event_id), None)


def _provider(events=()):
    return BellMediaProvider(league_mapping_source=_Mapping(), client=_Client(events))


def test_team_parsing_and_league_discovery():
    provider = _provider()

    team = provider.get_team("93775", "cfl")

    assert team is not None
    assert team.name == "BC Lions"
    assert team.abbreviation == "BC"
    assert team.color == "F15623"
    assert provider.get_supported_leagues() == ["cfl"]


def test_hockey_team_parsing_uses_tsn_widget_logo_url():
    provider = _provider()

    team = provider._parse_team(
        {
            "competitorId": 14,
            "name": "London Knights",
            "club": "Knights",
            "shortName": "LDN",
            "seoIdentifier": "london-knights",
        },
        "ohl",
    )

    assert team is not None
    assert team.logo_url == "https://widgets.sports.bellmedia.ca/img/ohl/london-knights.webp"


def test_event_only_hockey_team_uses_tsn_widget_logo_url():
    provider = _provider()

    team = provider._parse_event_team(
        {
            "competitorId": 6,
            "location": "Toronto",
            "name": "Sceptres",
            "shortName": "TOR",
            "seoIdentifier": "toronto-sceptres",
        },
        {},
        "pwhl",
    )

    assert team is not None
    assert team.logo_url == "https://widgets.sports.bellmedia.ca/img/pwhl/toronto-sceptres.webp"


def test_cfl_team_parsing_uses_tsn_widget_logo_url():
    provider = _provider()

    assert (
        provider._parse_team(COMPETITORS[0], "cfl").logo_url
        == "https://widgets.sports.bellmedia.ca/img/cfl/bc-lions.webp"
    )


def test_missing_seo_identifier_has_no_widget_logo():
    provider = _provider()

    competitor = {key: value for key, value in COMPETITORS[0].items() if key != "seoIdentifier"}
    team = provider._parse_team(competitor, "ohl")

    assert team is not None
    assert team.logo_url is None


def test_event_parsing_uses_top_as_away_and_bottom_as_home():
    event = _provider([_event()]).get_event("13419712", "cfl")

    assert event is not None
    assert event.name == "BC Lions at Calgary Stampeders"
    assert event.short_name == "BC at CGY"
    assert event.start_time == datetime(2026, 8, 14, 1, tzinfo=UTC)
    assert event.status.state == "final"
    assert (event.away_score, event.home_score) == (30, 26)
    assert event.broadcasts == ["TSN", "TSN1"]
    assert event.venue and event.venue.name == "McMahon Stadium"
    assert event.season_type == "regular"


def test_event_parsing_canonicalizes_hockey_season_types():
    provider = _provider()

    assert provider._parse_event(_event(seasonTypeId=0), "ohl", {}).season_type == "preseason"
    assert provider._parse_event(_event(seasonTypeId=1), "ohl", {}).season_type == "regular"
    assert provider._parse_event(_event(seasonTypeId=2), "ohl", {}).season_type == "postseason"


def test_scheduled_event_hides_scores():
    event = _provider([_event(status="Scheduled")]).get_event("13419712", "cfl")

    assert event is not None
    assert event.status.state == "scheduled"
    assert event.home_score is None
    assert event.away_score is None


def test_get_events_returns_superset_window():
    """±1-day superset (#590): exact membership is the service seam's job."""
    rows = [
        _event(event_date="2026-08-13"),
        _event(event_id=2, event_date="2026-08-14"),
        _event(event_id=3, event_date="2026-08-16"),
    ]
    events = _provider(rows).get_events("cfl", date(2026, 8, 13))

    assert [event.id for event in events] == ["13419712", "2"]


def test_team_schedule_filters_and_sorts(monkeypatch):
    today = date(2026, 8, 15)
    monkeypatch.setattr(
        "teamarr.providers.bellmedia.provider.date", SimpleNamespace(today=lambda: today)
    )
    events = [
        _event(event_id=2, event_date="2026-08-20"),
        _event(event_id=1, event_date="2026-08-13"),
        _event(event_id=3, event_date="2026-09-01"),
    ]
    events[0]["event"]["dateGMT"] = "2026-08-20T23:00:00"
    events[1]["event"]["dateGMT"] = "2026-08-13T23:00:00"

    schedule = _provider(events).get_team_schedule("93775", "cfl", days_ahead=14)

    assert [event.id for event in schedule] == ["1", "2"]


def test_unsupported_league_returns_no_data():
    provider = _provider([_event()])

    assert provider.get_events("nfl", date(2026, 8, 13)) == []
    assert provider.get_team("93775", "nfl") is None


def test_client_preserves_bellmedia_endpoint_paths():
    requests = []
    client = BellMediaClient()
    client._client = httpx.Client(
        headers=client._headers,
        transport=httpx.MockTransport(
            lambda request: (requests.append(request), httpx.Response(200, json={}))[1]
        ),
    )
    mapping = SimpleNamespace(sport="football", provider_league_id="cfl")

    for path in (
        "competitor/{sport}/{league}",
        "leagueCalendar/sports/{sport}/leagues/{league}",
        "schedule/sports/{sport}/leagues/{league}",
        "event/{sport}/{league}/13419712",
    ):
        client._request_for_mapping(mapping, path, label="test")

    assert [request.url.path for request in requests] == [
        "/v2/competitor/football/cfl",
        "/v2/leagueCalendar/sports/football/leagues/cfl",
        "/v2/schedule/sports/football/leagues/cfl",
        "/v2/event/football/cfl/13419712",
    ]
    assert all(request.url.params["brand"] == "tsn" for request in requests)
    assert all(request.url.params["lang"] == "en" for request in requests)
    client.close()


def test_client_uses_bellmedia_origin():
    requests = []
    client = BellMediaClient()
    client._client = httpx.Client(
        headers=client._headers,
        transport=httpx.MockTransport(
            lambda request: (requests.append(request), httpx.Response(200, json={}))[1]
        ),
    )

    client._request_for_mapping(
        SimpleNamespace(sport="football", provider_league_id="cfl"),
        "competitor/{sport}/{league}",
        label="test",
    )

    assert str(requests[0].url).startswith(
        "https://next-gen.sports.bellmedia.ca/v2/competitor/football/cfl"
    )
    client.close()


def test_client_reads_hockey_daily_calendar_groups(monkeypatch):
    client = BellMediaClient()
    groups = []
    monkeypatch.setattr(
        client,
        "get_calendar",
        lambda league: {
            "season": 2026,
            "monthlyCalendar": {
                "2026-09": {"calendarDates": ["2026-09-12", "2026-09-13", "2026-09-14"]}
            },
        },
    )
    monkeypatch.setattr(
        client,
        "get_schedule_group",
        lambda league, grouping, season: groups.append(grouping)
        or [{"eventId": grouping}, {"eventId": grouping}],
    )

    events = client.get_events_between("ohl", date(2026, 9, 13), date(2026, 9, 14))

    assert groups == ["2026-09-13", "2026-09-14"]
    assert [event["eventId"] for event in events] == ["2026-09-13", "2026-09-14"]
    client.close()
