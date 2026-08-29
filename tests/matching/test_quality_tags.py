"""Video-quality tags never reach a team name (#651).

`USA: NCAAF PACKAGE [1080p]` matched 0 of 30 streams while its untagged twin
matched 21 of 30. `[1080p]` fell between the two existing rules — the HD/SD
word list and the bracketed pure-digit channel number — and rode into team2 as
"Wagner [1080p]", which scores exactly 60 against "Wagner Seahawks" AND makes
"1080p" a discriminating residual for the fixture gate. Two independent kills.
A leading tag was worse: it blocked the league-hint prefix strip, so team1 came
out as "[1080p] NCAAF 16: Robert Morris".
"""

import pytest

from teamarr.consumers.matching.classifier import StreamCategory, classify_stream
from teamarr.consumers.matching.identity import residual_contradicts
from teamarr.consumers.matching.normalizer import strip_quality_tags


class TestTagsAreStrippedFromTeamNames:
    @pytest.mark.parametrize(
        "stream",
        [
            "NCAAF 16: Robert Morris at Wagner 12pm [1080p]",
            "[1080p] NCAAF 16: Robert Morris at Wagner 12pm",
            "NCAAF 21: 3:30PM Robert Morris at Wagner [1080p]",
            "NCAAF 01: Robert Morris vs Wagner @ Oct 24 7:00 PM [1080p]",
            "Robert Morris at Wagner 1080p",
            "Robert Morris at Wagner 1080P",
            "Robert Morris at Wagner (1080i)",
            "Robert Morris at Wagner [720p]",
            "Robert Morris at Wagner [2160p]",
            "Robert Morris at Wagner (4K)",
            "Robert Morris at Wagner HD 1080p",
            "Robert Morris at Wagner | 1080p",
            "Robert Morris at Wagner FHD",
        ],
    )
    def test_both_sides_come_out_clean(self, stream):
        result = classify_stream(stream)
        assert result.category is StreamCategory.TEAM_VS_TEAM
        assert result.team1 == "Robert Morris"
        assert result.team2 == "Wagner"

    def test_tagged_source_title_is_not_a_team_named_after_the_tag(self):
        result = classify_stream("USA: NCAAF PACKAGE [1080p]")
        assert result.team1 == "PACKAGE"
        assert result.team2 is None

    def test_a_tag_never_leaves_empty_brackets_behind(self):
        result = classify_stream("Robert Morris at Wagner [1080p]")
        assert "[" not in (result.team2 or "") and "(" not in (result.team2 or "")


class TestDigitBearingNamesAreUntouched:
    @pytest.mark.parametrize(
        "stream,team1,team2",
        [
            (
                "San Francisco 49ers vs Philadelphia 76ers",
                "San Francisco 49ers",
                "Philadelphia 76ers",
            ),
            ("France U20 vs Spain U-21", "France U20", "Spain U-21"),
        ],
    )
    def test_matchups(self, stream, team1, team2):
        result = classify_stream(stream)
        assert (result.team1, result.team2) == (team1, team2)

    @pytest.mark.parametrize("name", ["Daytona 500", "Formula 1 Grand Prix", "Coca-Cola 600"])
    def test_single_names(self, name):
        assert classify_stream(name).team1 == name

    @pytest.mark.parametrize(
        "text",
        ["Daytona 500", "Phoenix 1080", "Ipswich Town 1878", "Top 250", "1. FC Koln"],
    )
    def test_stream_level_strip_leaves_plain_numbers_alone(self, text):
        assert strip_quality_tags(text) == text


class TestFixtureGateIgnoresQualityResidue:
    """The score was one kill; `residual_contradicts` was the other."""

    @pytest.mark.parametrize("residue", ["1080p", "720i", "2160p", "fhd", "uhd"])
    def test_quality_token_is_not_a_discriminating_residual(self, residue):
        assert residual_contradicts(f"wagner {residue}", "wagner seahawks") is False

    def test_a_real_residual_still_contradicts(self):
        assert residual_contradicts("wagner rams", "wagner seahawks") is True
