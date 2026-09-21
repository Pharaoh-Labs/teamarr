"""UEFA Nations League is a supported ESPN competition."""

from teamarr.consumers.matching.classifier import detect_league_hint


def test_seeded_uefa_nations_league_mapping(db_conn):
    row = db_conn.execute(
        """SELECT provider, provider_league_id, sport, league_alias, league_id
           FROM leagues WHERE league_code = 'uefa.nations'"""
    ).fetchone()

    assert tuple(row) == (
        "espn",
        "soccer/uefa.nations",
        "soccer",
        "UNL",
        "uefa-nations-league",
    )


def test_detect_uefa_nations_league_hint():
    assert (
        detect_league_hint("UEFA Nations League: Germany vs Netherlands")
        == "uefa.nations"
    )
