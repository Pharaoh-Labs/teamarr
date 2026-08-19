"""provider_calls telemetry survives the run persistence round-trip (kbbk.2).

Generation snapshots the run-scoped provider-call counter into
``extra_metrics``; this locks the contract that it persists to the DB and
surfaces through ``ProcessingRun.to_dict`` (what ``GET /stats/runs`` returns).
"""

from teamarr.database.stats import create_run, get_run, save_run


def test_provider_calls_persist_and_surface(db_conn):
    run = create_run(db_conn, run_type="full_epg")
    run.channels_active = 126
    run.extra_metrics["provider_calls"] = {
        "espn:summary": 289,
        "espn:scoreboard": 40,
        "mlbstats:schedule": 12,
    }
    run.extra_metrics["provider_calls_total"] = 341
    save_run(db_conn, run)

    reloaded = get_run(db_conn, run.id)
    d = reloaded.to_dict()
    assert d["extra_metrics"]["provider_calls"]["espn:summary"] == 289
    assert d["extra_metrics"]["provider_calls_total"] == 341

    # calls-per-channel — the headline the UI derives — is computable from the
    # surfaced fields (this is the regression signal: ~2.7 healthy vs ~16 buggy).
    ratio = d["extra_metrics"]["provider_calls_total"] / d["channels"]["active"]
    assert round(ratio, 1) == 2.7
