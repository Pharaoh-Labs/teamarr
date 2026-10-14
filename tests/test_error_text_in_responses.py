"""Exception text stays in the log, not in the response (#1051).

CodeQL's stack-trace-exposure rule flags ``str(exc)`` flowing into an HTTP
response. The two routes that did it now name the failure class only.
"""

from fastapi.testclient import TestClient

from teamarr.api.app import app

client = TestClient(app)


def test_epg_sources_error_names_the_class_not_the_message(monkeypatch):
    def boom(_db):
        raise RuntimeError("token abc123 rejected by http://dispatcharr.local")

    monkeypatch.setattr("teamarr.api.routes.settings.dispatcharr.get_dispatcharr_connection", boom)

    body = client.get("/api/v1/dispatcharr/epg-sources").json()

    assert body["success"] is False
    assert body["sources"] == []
    assert "RuntimeError" in body["error"]
    assert "abc123" not in body["error"]
    assert "dispatcharr.local" not in body["error"]
