import pytest

from teamarr.utilities.m3u_group_identity import rotating_group_key


@pytest.mark.parametrize(
    "suffix",
    [
        "(Thur)",
        "(Wed)",
        "[ FRIDAY 13 ]",
        "(12.11)",
        "(12-11)",
        " 12-11-2026",
        " Nov 12",
        " 12 Nov",
        " Tue 2026-11-17",
    ],
)
def test_recognized_rotation_suffixes(suffix):
    assert rotating_group_key(f"LÍVE | Conference League{suffix}") == "live conference league"


@pytest.mark.parametrize(
    "name",
    [
        "NHL (Preseason)",
        "NHL (HD)",
        "NHL 24/7",
        "NHL (24/7)",
        "NHL 24-7",
        "NHL (24-7)",
        "NHL 24.7",
        "US | ESPN+ 1-10",
        "US | ESPN+ 11-20",
        "US | PPV 16-30",
        "US | PPV (16-30)",
        "NHL (3)",
        "NHL (Wed) HD",
        "(Wed)",
    ],
)
def test_non_rotation_labels_are_not_stripped(name):
    assert rotating_group_key(name) is None


def test_rotation_retains_the_feed_qualifier():
    assert rotating_group_key("UK | NHL Backup (Thu)") == "uk nhl backup"
