"""Regex over live M3U group names: the resolver and its preview endpoint.

What is left of #450 after #1056: the exception-keyword source editor
previews which M3U groups a keyword's group pattern matches.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.database import init_db
from teamarr.services.group_pattern import compile_group_pattern, resolve_group_name_pattern

client = TestClient(app)


def _grp(gid, name, m3u=True):
    return SimpleNamespace(id=gid, name=name, m3u_accounts=(1,) if m3u else ())


class TestResolver:
    LIVE = [
        _grp(1, "EPL (MW1)"),
        _grp(2, "EPL (MW2)"),
        _grp(3, "USA | MLB"),
        _grp(4, "epl classics", m3u=False),  # not M3U-provided
    ]

    def test_matches_by_regex(self):
        got = resolve_group_name_pattern(self.LIVE, r"EPL \(MW\d+\)")
        assert [g.id for g in got] == [1, 2]

    def test_case_insensitive_search(self):
        got = resolve_group_name_pattern(self.LIVE, r"usa \| mlb")
        assert [g.id for g in got] == [3]

    def test_non_m3u_groups_excluded(self):
        # "epl classics" matches the regex but has no M3U account relation.
        got = resolve_group_name_pattern(self.LIVE, r"epl")
        assert [g.id for g in got] == [1, 2]

    def test_missing_m3u_accounts_field_fails_closed(self):
        bare = [SimpleNamespace(id=9, name="EPL (MW3)")]
        assert resolve_group_name_pattern(bare, r"EPL") == []

    def test_invalid_pattern_returns_empty(self):
        assert resolve_group_name_pattern(self.LIVE, r"EPL (") == []
        assert compile_group_pattern(r"EPL (") is None

    def test_empty_pattern_returns_empty(self):
        assert resolve_group_name_pattern(self.LIVE, None) == []
        assert resolve_group_name_pattern(self.LIVE, "   ") == []


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()


class TestPatternPreviewApi:
    def _patch_dispatcharr(self, monkeypatch, groups):
        import teamarr.api.routes.groups as groups_routes

        fake = SimpleNamespace(m3u=SimpleNamespace(list_groups=lambda: groups))
        monkeypatch.setattr(
            groups_routes, "get_dispatcharr_connection", lambda db_factory=None: fake
        )

    def test_preview_returns_matches(self, isolated_db, monkeypatch):
        self._patch_dispatcharr(
            monkeypatch, [_grp(1, "EPL (MW1)"), _grp(2, "EPL (MW2)"), _grp(3, "USA | MLB")]
        )
        resp = client.post(
            "/api/v1/groups/dispatcharr/group-pattern-preview",
            json={"pattern": r"EPL \(MW\d+\)"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["valid"] is True
        assert body["total"] == 2
        assert [m["name"] for m in body["matches"]] == ["EPL (MW1)", "EPL (MW2)"]

    def test_preview_invalid_regex_is_soft_error(self, isolated_db, monkeypatch):
        self._patch_dispatcharr(monkeypatch, [_grp(1, "EPL (MW1)")])
        resp = client.post(
            "/api/v1/groups/dispatcharr/group-pattern-preview",
            json={"pattern": "EPL ("},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert body["total"] == 0

    def test_preview_unconfigured_dispatcharr_is_400(self, isolated_db, monkeypatch):
        import teamarr.api.routes.groups as groups_routes

        monkeypatch.setattr(
            groups_routes, "get_dispatcharr_connection", lambda db_factory=None: None
        )
        resp = client.post(
            "/api/v1/groups/dispatcharr/group-pattern-preview", json={"pattern": "EPL"}
        )
        assert resp.status_code == 400
