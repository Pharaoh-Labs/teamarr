"""Regression: combined GET /settings must serialize the full EPG section.

Bug teamarrv2-335: the combined `/settings` handler built EPGSettingsModel
without `epg_xtream_fallback_enabled`, so it silently fell back to the model
default (False) regardless of the stored value. The Settings page loads its EPG
state from the combined endpoint, so the saved XC-fallback toggle reverted on
reload even though the DB and the dedicated `/settings/epg` endpoint were correct.

This guards parity: every field the dedicated endpoint exposes must also be
carried through the combined endpoint. Read-only — it compares the two live
endpoints against whatever the current DB holds, so any omitted field whose
stored value differs from the model default is caught.
"""

from fastapi.testclient import TestClient

from teamarr.api.app import app

client = TestClient(app)


def test_combined_settings_epg_matches_dedicated_endpoint():
    dedicated = client.get("/api/v1/settings/epg")
    combined = client.get("/api/v1/settings")
    assert dedicated.status_code == 200
    assert combined.status_code == 200

    epg_dedicated = dedicated.json()
    epg_combined = combined.json().get("epg", {})

    # Every field the dedicated EPG endpoint returns must be present and equal
    # in the combined endpoint's epg section (no silent default fallbacks).
    mismatches = {
        key: (value, epg_combined.get(key))
        for key, value in epg_dedicated.items()
        if epg_combined.get(key) != value
    }
    assert not mismatches, (
        f"combined /settings epg section diverges from /settings/epg: {mismatches}"
    )


def test_combined_settings_includes_xtream_fallback_key():
    # Explicit guard for the exact field that regressed.
    epg = client.get("/api/v1/settings").json().get("epg", {})
    assert "epg_xtream_fallback_enabled" in epg
