"""Regression tests for channel/competition pollution in extracted team names (#790).

From the live-install audit: the brand strip removes "Sky Sports" from
"Sky Sports + 01: EFL Championship Derby v West Brom @ 9 Sep 07:30 PM London"
but the leftover "+ 01:" anchored every channel-number rule away from the
digits, and the "EFL Championship" competition label rode into team1
(scores ~33 vs "Derby County", under the 60 floor) while team2 kept the
"@ London" venue tail — for events that exist on ESPN and sit inside the
match window.

The fixes live in `_clean_team_name`: plus-form and brand-with-plus channel
numbers, parenthesized provider designations, trailing "@ <venue>" and
weekday tails, and a leading competition/sport label strip that requires the
label pattern to consume the candidate exactly (hint detection is
containment-based — "OHL 01 : Kitchener" merely *contains* the OHL hint).
"""

from teamarr.consumers.matching.classifier import classify_stream


class TestChannelPrefixStrips:
    def test_sky_sports_plus_number_competition(self):
        c = classify_stream(
            "Sky Sports + 01: EFL Championship Derby v West Brom @ 9 Sep 07:30 PM London"
        )
        assert c.team1 == "Derby"
        assert c.team2 == "West Brom"

    def test_sky_sports_plus_number_umbrella_multiword(self):
        c = classify_stream(
            "Sky Sports + 02: EFL Championship Norwich v Birmingham @ 9 Sep 07:30 PM London"
        )
        assert c.team1 == "Norwich"
        assert c.team2 == "Birmingham"

    def test_brand_with_embedded_plus(self):
        c = classify_stream("BIG10+ 21: Soccer (M) Ohio State at Wisconsin Fri")
        assert c.team1 == "Ohio State"
        assert c.team2 == "Wisconsin"

    def test_parenthesized_provider_designation_and_feed_label(self):
        c = classify_stream("US (Peacock 057): Home Feed: NYY at AZ (2026-09-19 20:00:00)")
        assert c.team1 == "NYY"

    def test_ohl_label_sheds_channel_number_residue(self):
        c = classify_stream("OHL  01 : 6:00 PM Kitchener Rangers @ Barrie Colts [1080p]")
        assert c.team1 == "Kitchener Rangers"
        assert c.team2 == "Barrie Colts"


class TestTailStrips:
    def test_venue_tail_removed_from_team2(self):
        c = classify_stream(
            "Sky Sports + 01: EFL Championship Derby v West Brom @ 9 Sep 07:30 PM London"
        )
        assert "London" not in (c.team2 or "")
        assert "@" not in (c.team2 or "")

    def test_weekday_tail_removed(self):
        c = classify_stream("Soccer Ohio State at Wisconsin Fri")
        assert c.team2 == "Wisconsin"


class TestOverStripGuards:
    """Hint detection is containment; the strip must not be."""

    def test_team_containing_a_hint_word_keeps_the_word(self):
        # "Kitchener" follows the hint word; only a pure label run is stripped.
        c = classify_stream("OHL Kitchener Rangers vs London Knights")
        assert c.team1 == "Kitchener Rangers"
        assert c.team2 == "London Knights"

    def test_tennis_player_survives_tournament_prefix(self):
        c = classify_stream("Wimbledon: Zheng vs Norrie")
        assert c.team1 == "Zheng"
        assert c.team2 == "Norrie"

    def test_plain_matchups_unchanged(self):
        c = classify_stream("NBA | Lakers @ Celtics")
        assert c.team1 == "Lakers"
        assert c.team2 == "Celtics"

    def test_full_names_with_pipe_provider_unchanged(self):
        c = classify_stream(
            "US (ESPN+ 072) | American Conference: Dayton vs. South Florida (2026-09-11 20:00:00)"
        )
        assert c.team1 == "Dayton"
        assert c.team2 == "South Florida"

    def test_single_word_label_is_never_the_whole_name(self):
        # A one-word team is never stripped even if it is itself a hint word.
        c = classify_stream("Arsenal vs Chelsea")
        assert c.team1 == "Arsenal"
        assert c.team2 == "Chelsea"
