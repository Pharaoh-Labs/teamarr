"""Tests for Xtream-Codes provider EPG detection + URL building (epic crs)."""

import io
from datetime import UTC, datetime

from teamarr.consumers.matching.epg_xtream import (
    _parse_xmltv_time,
    is_xtream_account,
    parse_xmltv_programs,
    xmltv_url,
)


def _xc(**kw):
    base = {
        "account_type": "XC",
        "server_url": "https://db4.org",
        "username": "user",
        "password": "pass",
    }
    base.update(kw)
    return base


# ================================================================= detection


def test_is_xtream_true_for_xc_with_credentials():
    assert is_xtream_account(_xc()) is True


def test_is_xtream_false_for_standard_account():
    assert is_xtream_account({"account_type": "STD", "server_url": "http://x/lineup.m3u"}) is False


def test_is_xtream_false_when_credentials_missing():
    assert is_xtream_account(_xc(username="")) is False
    assert is_xtream_account(_xc(password="")) is False
    assert is_xtream_account(_xc(server_url="")) is False


def test_is_xtream_false_for_empty_or_none():
    assert is_xtream_account({}) is False
    assert is_xtream_account(None) is False


# =============================================================== url builder


def test_xmltv_url_basic():
    assert xmltv_url(_xc()) == "https://db4.org/xmltv.php?username=user&password=pass"


def test_xmltv_url_strips_trailing_slash_and_path():
    # server_url with a trailing slash or an existing get.php path -> clean host.
    assert xmltv_url(_xc(server_url="https://msx.p13.one/")) == (
        "https://msx.p13.one/xmltv.php?username=user&password=pass"
    )
    assert xmltv_url(_xc(server_url="https://h.tv:8080/get.php?type=m3u_plus")) == (
        "https://h.tv:8080/xmltv.php?username=user&password=pass"
    )


def test_xmltv_url_percent_encodes_credentials():
    url = xmltv_url(_xc(username="a b", password="p@ss/word"))
    assert "username=a%20b" in url
    assert "password=p%40ss%2Fword" in url


def test_xmltv_url_none_for_non_xtream():
    assert xmltv_url({"account_type": "STD"}) is None


# ============================================================= time parsing


def test_parse_xmltv_time_with_offset():
    assert _parse_xmltv_time("20260603233000 -0400") == datetime(2026, 6, 4, 3, 30, tzinfo=UTC)


def test_parse_xmltv_time_without_offset_assumes_utc():
    assert _parse_xmltv_time("20260603233000") == datetime(2026, 6, 3, 23, 30, tzinfo=UTC)


def test_parse_xmltv_time_bad_input():
    assert _parse_xmltv_time("") is None
    assert _parse_xmltv_time("not-a-time") is None


# ============================================================= xmltv parsing

_XML = """<?xml version="1.0"?><tv>
<channel id="USANetwork.us"><display-name>USA</display-name></channel>
<channel id="ESPN.us"><display-name>ESPN</display-name></channel>
<programme start="20260603193000 -0400" stop="20260603220000 -0400" channel="USANetwork.us">
  <title>WNBA Basketball</title><sub-title>Toronto Tempo at New York Liberty</sub-title>
  <desc>Game</desc><category>Sports</category><category>Basketball</category></programme>
<programme start="20260603150000 -0400" stop="20260603160000 -0400" channel="USANetwork.us">
  <title>Law &amp; Order</title></programme>
<programme start="20260603200000 -0400" stop="20260603223000 -0400" channel="ESPN.us">
  <title>Softball</title><sub-title>Texas Tech vs. Texas</sub-title></programme>
<programme start="20260603200000 -0400" stop="20260603223000 -0400" channel="NotWanted.us">
  <title>Ignore Me</title></programme>
</tv>"""


def _parse(wanted, ws, we):
    return parse_xmltv_programs(io.BytesIO(_XML.encode()), wanted, ws, we)


def test_parse_filters_by_channel_and_builds_program():
    ws = datetime(2026, 6, 3, 22, tzinfo=UTC)  # 18:00 ET
    we = datetime(2026, 6, 4, 6, tzinfo=UTC)  # 02:00 ET
    res = _parse({"USANetwork.us", "ESPN.us"}, ws, we)
    # USA WNBA (23:30Z) + ESPN softball (00:00Z) overlap; USA Law&Order (19:00Z) does not.
    assert set(res) == {"USANetwork.us", "ESPN.us"}
    assert len(res["USANetwork.us"]) == 1
    p = res["USANetwork.us"][0]
    assert p.title == "WNBA Basketball"
    assert p.sub_title == "Toronto Tempo at New York Liberty"
    assert p.categories == ("Sports", "Basketball")
    assert p.start_time == "2026-06-03T23:30:00Z"
    assert p.id < 0  # synthetic, not from DP


def test_parse_excludes_unwanted_channels():
    ws = datetime(2026, 6, 3, 0, tzinfo=UTC)
    we = datetime(2026, 6, 5, 0, tzinfo=UTC)
    res = _parse({"USANetwork.us"}, ws, we)
    assert set(res) == {"USANetwork.us"}  # ESPN + NotWanted excluded
    assert len(res["USANetwork.us"]) == 2  # both USA programmes are in this wide window


def test_parse_empty_wanted_returns_empty():
    ws = datetime(2026, 6, 3, 0, tzinfo=UTC)
    we = datetime(2026, 6, 5, 0, tzinfo=UTC)
    assert _parse(set(), ws, we) == {}
