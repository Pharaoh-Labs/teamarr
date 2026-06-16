"""Score-merge join tests for SupabaseLeagueClient (CBL).

Pins how completed-game scores attach to schedule entries. The join is on
``game_number`` (exact int, matching games.schedule_game_number <->
schedule_game_overrides.game_number) rather than parsed city names, because:

  * baseball doubleheaders share date + both team names but have distinct
    game numbers (regression: bead teamarrv2-hh7 / PR #204), and
  * the name key silently mismatches teams whose first word != schedule city
    override (e.g. "Chatham-Kent Barnstormers" vs override "chatham").

Field shapes mirror the live Supabase schema confirmed via read-only probe.
"""

from teamarr.providers.supabase.client import SupabaseLeagueClient


def _client() -> SupabaseLeagueClient:
    # No mapping source needed — build_score_map/_merge_scores are pure.
    return SupabaseLeagueClient(league_mapping_source=None)


def _game(number, date, home, away, hs, as_):
    return {
        "id": f"uuid-{number}",
        "schedule_game_number": number,
        "game_date": date,
        "home_team_name": home,
        "away_team_name": away,
        "home_score": hs,
        "away_score": as_,
    }


def _entry(number, date, home_city, away_city):
    return {
        "id": f"sched-{number}",
        "game_number": number,
        "game_date_override": date,
        "home_team_override": home_city,
        "away_team_override": away_city,
    }


class TestGameNumberJoin:
    def test_attaches_score_by_game_number(self):
        c = _client()
        games = [_game(10, "2026-05-29", "Barrie Baycats", "London Majors", 5, 3)]
        smap = c.build_score_map(games)
        merged = c._merge_scores([_entry(10, "2026-05-29", "barrie", "london")], smap)
        assert merged[0]["_score"]["home_score"] == 5
        assert merged[0]["_score"]["away_score"] == 3

    def test_chatham_kent_joins_where_name_key_would_miss(self):
        # First word "chatham-kent" != schedule override "chatham": name key fails,
        # game_number join succeeds.
        c = _client()
        games = [_game(7, "2026-05-15", "Chatham-Kent Barnstormers", "Guelph Royals", 2, 1)]
        smap = c.build_score_map(games)
        merged = c._merge_scores([_entry(7, "2026-05-15", "chatham", "guelph")], smap)
        assert merged[0]["_score"]["home_score"] == 2


class TestDoubleheader:
    def test_each_game_gets_its_own_score(self):
        # Same date, same two teams, two games -> distinct numbers, distinct scores.
        c = _client()
        games = [
            _game(101, "2026-06-01", "Barrie Baycats", "London Majors", 4, 2),
            _game(102, "2026-06-01", "Barrie Baycats", "London Majors", 1, 7),
        ]
        smap = c.build_score_map(games)
        entries = [
            _entry(101, "2026-06-01", "barrie", "london"),
            _entry(102, "2026-06-01", "barrie", "london"),
        ]
        merged = c._merge_scores(entries, smap)
        assert merged[0]["_score"]["home_score"] == 4
        assert merged[0]["_score"]["away_score"] == 2
        assert merged[1]["_score"]["home_score"] == 1
        assert merged[1]["_score"]["away_score"] == 7
        # No cross-contamination: the two entries carry different scores.
        assert merged[0]["_score"]["id"] != merged[1]["_score"]["id"]


class TestNameKeyFallback:
    def test_falls_back_to_name_key_when_number_absent(self):
        # Legacy/odd game with no schedule_game_number still matches by name.
        c = _client()
        g = _game(None, "2026-05-20", "London Majors", "Toronto Maple Leafs", 6, 0)
        smap = c.build_score_map([g])
        entry = _entry(None, "2026-05-20", "london", "toronto")
        del entry["game_number"]
        merged = c._merge_scores([entry], smap)
        assert merged[0]["_score"]["home_score"] == 6

    def test_number_miss_falls_back_to_name(self):
        # Entry has a number, but no completed game carries it yet -> name fallback.
        c = _client()
        g = _game(None, "2026-05-21", "Guelph Royals", "Barrie Baycats", 3, 3)
        smap = c.build_score_map([g])
        merged = c._merge_scores([_entry(55, "2026-05-21", "guelph", "barrie")], smap)
        assert merged[0]["_score"]["home_score"] == 3


class TestNoMatch:
    def test_entry_unchanged_when_no_score(self):
        c = _client()
        smap = c.build_score_map([_game(1, "2026-05-01", "Barrie Baycats", "London Majors", 2, 1)])
        entry = _entry(99, "2026-05-09", "guelph", "toronto")
        merged = c._merge_scores([entry], smap)
        assert "_score" not in merged[0]
        assert merged[0] is entry
