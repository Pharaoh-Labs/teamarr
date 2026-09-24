"""Unit contracts for Packet 6B media-job and cleanup phase adapters."""

from types import SimpleNamespace

from teamarr.consumers.generation_pipeline import media_refresh, stats


class _Context(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.progress_events: list[tuple] = []

    def report(self, *args):
        self.progress_events.append(args)


def test_media_job_stage_discards_jobs_only_when_dry_run_records_them():
    context = _Context(db_factory=object(), result=object(), media_jobs=[])
    jobs = [("emby", object())]
    calls = []

    def get_jobs(db_factory):
        calls.append(("jobs", db_factory))
        return jobs

    def dry_run(result, supplied_jobs):
        calls.append(("dry-run", result, supplied_jobs))
        return True

    media_refresh.stage_media_jobs(context, get_jobs=get_jobs, dry_run_refresh=dry_run)

    assert calls == [("jobs", context.db_factory), ("dry-run", context.result, jobs)]
    assert context.media_jobs == []


def test_cleanup_stage_preserves_history_and_logo_result_fields():
    context = _Context(db_factory=object(), dispatcharr_client=object(), result=SimpleNamespace())
    calls = []

    def cleanup(db_factory, dispatcharr_client, report):
        calls.append((db_factory, dispatcharr_client, report))
        return {"history": {"deleted_count": 3}, "logos": {"deleted_count": 2}}

    stats.stage_cleanup(context, cleanup_tasks=cleanup)

    assert context.progress_events == [("cleanup", 99, "Cleaning up history...")]
    assert calls == [(context.db_factory, context.dispatcharr_client, context.report)]
    assert context.result.cleanup == {"deleted_count": 3}
    assert context.result.logo_cleanup == {"deleted_count": 2}
