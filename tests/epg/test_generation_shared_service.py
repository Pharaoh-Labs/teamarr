"""One run-scoped ``SportsDataService`` per generation (#830, Packet 1).

``run_full_generation`` has always claimed to build a single service and share
it "across all processing" so the event cache stays warm for the whole run.
Group processing and lifecycle construction did receive it; team processing did
not — ``process_all_teams()`` took no ``service`` argument and so built its own
with a cold cache. These tests make the claim true and keep it true.

The observable consequence is fewer provider calls, because the second consumer
to ask for an event now finds it cached. That is the intended change; what must
*not* change is the provider-call metric schema, its endpoint/provider
attribution, the reset-at-run-start timing, or its persistence onto the run row
(all pinned in ``test_generation_contract.py``).
"""

import pytest

from teamarr.consumers.team_processor import TeamProcessor, process_all_teams
from teamarr.database import get_db, init_db


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    return get_db


class _SentinelService:
    """Not a SportsDataService — identity is the whole point."""


# ---------------------------------------------------------------------------
# The convenience function
# ---------------------------------------------------------------------------


def test_supplied_service_reaches_the_processor_unchanged(isolated_db, monkeypatch):
    """``process_all_teams(service=X)`` hands X straight to ``TeamProcessor``."""
    sentinel = _SentinelService()
    seen: dict = {}

    class _CapturingProcessor:
        def __init__(self, db_factory, service=None):
            seen["db_factory"] = db_factory
            seen["service"] = service

        def process_all_teams(self, progress_callback=None):
            seen["progress_callback"] = progress_callback
            return "batch-result"

    monkeypatch.setattr("teamarr.consumers.team_processor.TeamProcessor", _CapturingProcessor)

    def callback(current, total, name):
        pass

    out = process_all_teams(db_factory=isolated_db, progress_callback=callback, service=sentinel)

    assert out == "batch-result"
    assert seen["service"] is sentinel
    assert seen["db_factory"] is isolated_db
    assert seen["progress_callback"] is callback


def test_omitting_the_service_still_builds_one(isolated_db, monkeypatch):
    """Existing direct callers that pass no service keep working."""
    built = []

    def fake_create_default_service():
        service = _SentinelService()
        built.append(service)
        return service

    monkeypatch.setattr(
        "teamarr.consumers.team_processor.create_default_service",
        fake_create_default_service,
    )
    monkeypatch.setattr("teamarr.consumers.team_processor.TeamEPGGenerator", lambda *a, **kw: None)

    seen: dict = {}

    class _CapturingProcessor(TeamProcessor):
        def process_all_teams(self, progress_callback=None):
            seen["service"] = self._service
            return "batch-result"

    monkeypatch.setattr("teamarr.consumers.team_processor.TeamProcessor", _CapturingProcessor)

    out = process_all_teams(db_factory=isolated_db)

    assert out == "batch-result"
    assert len(built) == 1
    assert seen["service"] is built[0]


def test_explicit_none_is_the_same_as_omitting_it(isolated_db, monkeypatch):
    """``service=None`` must not be mistaken for "use no service"."""
    monkeypatch.setattr("teamarr.consumers.team_processor.create_default_service", _SentinelService)
    monkeypatch.setattr("teamarr.consumers.team_processor.TeamEPGGenerator", lambda *a, **kw: None)

    seen: dict = {}

    class _CapturingProcessor(TeamProcessor):
        def process_all_teams(self, progress_callback=None):
            seen["service"] = self._service
            return "batch-result"

    monkeypatch.setattr("teamarr.consumers.team_processor.TeamProcessor", _CapturingProcessor)

    process_all_teams(db_factory=isolated_db, service=None)

    assert isinstance(seen["service"], _SentinelService)


# ---------------------------------------------------------------------------
# One service per generation run
# ---------------------------------------------------------------------------


def test_one_service_is_built_per_generation(isolated_db, monkeypatch):
    """The generation-owned service factory is called exactly once."""
    import teamarr.consumers.generation as generation_mod
    from teamarr.consumers.generation import run_full_generation

    built = []
    original = generation_mod.create_default_service

    def counting(*args, **kwargs):
        service = original(*args, **kwargs)
        built.append(service)
        return service

    monkeypatch.setattr(generation_mod, "create_default_service", counting)

    result = run_full_generation(db_factory=isolated_db, dispatcharr_client=None)

    assert result.success is True
    assert len(built) == 1


def test_the_same_service_reaches_teams_groups_and_lifecycle(isolated_db, monkeypatch):
    """Identity, not equality: one object flows through all three consumers."""
    import teamarr.consumers.generation as generation_mod
    from teamarr.consumers.generation import run_full_generation

    built: list = []
    original_create = generation_mod.create_default_service

    def counting(*args, **kwargs):
        service = original_create(*args, **kwargs)
        built.append(service)
        return service

    monkeypatch.setattr(generation_mod, "create_default_service", counting)

    received: dict = {}

    def fake_process_all_teams(db_factory, progress_callback=None, service=None):
        received["teams"] = service
        from teamarr.consumers.team_processor import BatchTeamResult

        return BatchTeamResult()

    def fake_process_all_event_groups(**kwargs):
        received["groups"] = kwargs.get("service")
        from teamarr.consumers.event_group_processor import BatchProcessingResult

        return BatchProcessingResult()

    original_lifecycle = None

    def fake_create_lifecycle_service(db_factory, service, dispatcharr_client=None):
        received["lifecycle"] = service
        return original_lifecycle(db_factory, service, dispatcharr_client=dispatcharr_client)

    import teamarr.consumers as consumers_mod

    original_lifecycle = consumers_mod.create_lifecycle_service

    monkeypatch.setattr(consumers_mod, "process_all_teams", fake_process_all_teams)
    monkeypatch.setattr(consumers_mod, "process_all_event_groups", fake_process_all_event_groups)
    monkeypatch.setattr(consumers_mod, "create_lifecycle_service", fake_create_lifecycle_service)

    result = run_full_generation(db_factory=isolated_db, dispatcharr_client=None)

    assert result.success is True
    assert len(built) == 1
    shared = built[0]
    assert received["teams"] is shared
    assert received["groups"] is shared
    assert received["lifecycle"] is shared


def test_team_processing_no_longer_builds_its_own_service(isolated_db, monkeypatch):
    """The regression guard: a cold service must not be created mid-run.

    Before Packet 1 this counter reached 2 — one for the run, one built inside
    ``process_all_teams`` with an empty cache.
    """
    import teamarr.consumers.generation as generation_mod
    import teamarr.consumers.team_processor as team_processor_mod
    from teamarr.consumers.generation import run_full_generation

    run_services = []
    team_services = []

    original_run_create = generation_mod.create_default_service
    original_team_create = team_processor_mod.create_default_service

    monkeypatch.setattr(
        generation_mod,
        "create_default_service",
        lambda *a, **kw: run_services.append(original_run_create(*a, **kw)) or run_services[-1],
    )
    monkeypatch.setattr(
        team_processor_mod,
        "create_default_service",
        lambda *a, **kw: team_services.append(original_team_create(*a, **kw)) or team_services[-1],
    )

    result = run_full_generation(db_factory=isolated_db, dispatcharr_client=None)

    assert result.success is True
    assert len(run_services) == 1
    assert team_services == []
