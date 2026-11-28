"""index.html is revalidated on every load; other files are not (#1302)."""

import pytest

from teamarr.api.app import spa_file_response


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html></html>")
    (tmp_path / "favicon.ico").write_bytes(b"ico")
    (tmp_path / "assets" / "index-abc123.js").write_text("js")
    return tmp_path


@pytest.mark.parametrize("path", ["", "index.html", "sources", "settings/general", "missing.png"])
def test_the_page_is_never_cached_without_revalidation(dist, path):
    response = spa_file_response(dist, path)
    assert response.path == str(dist / "index.html")
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["favicon.ico", "assets/index-abc123.js"])
def test_other_files_keep_default_caching(dist, path):
    response = spa_file_response(dist, path)
    assert response.path == str(dist / path)
    assert "cache-control" not in response.headers


def test_a_path_outside_dist_gets_the_page(dist):
    response = spa_file_response(dist, "../../etc/passwd")
    assert response.path == str(dist / "index.html")
