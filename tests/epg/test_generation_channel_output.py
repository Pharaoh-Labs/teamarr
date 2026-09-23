"""Unit contracts for Packet 5A channel-numbering and XMLTV output phases."""

from contextlib import nullcontext
from types import SimpleNamespace

from teamarr.consumers.generation_pipeline.phases import channel_output


class _Context(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.progress_events: list[tuple] = []

    def report(self, *args):
        self.progress_events.append(args)


def _context(tmp_path, output_path=None):
    return _Context(
        db_factory=lambda: nullcontext(object()),
        dispatcharr_client=object(),
        external_occupied={501},
        relayout=False,
        settings=SimpleNamespace(
            epg=SimpleNamespace(epg_output_path=output_path),
            display=SimpleNamespace(
                xmltv_generator_name="Teamarr test",
                xmltv_generator_url="https://example.test/teamarr",
            ),
        ),
        result=SimpleNamespace(file_written=False, file_path=None, file_size=0),
    )


def test_channel_reassignment_forwards_context_dependencies_and_records_relayout(tmp_path):
    context = _context(tmp_path)
    calls = []

    def sync(db_factory, dispatcharr_client, progress, external_occupied):
        calls.append((db_factory, dispatcharr_client, progress, external_occupied))
        return True

    channel_output.stage_channel_reassign(context, sync_global_channels=sync)

    assert calls == [
        (
            context.db_factory,
            context.dispatcharr_client,
            context.report,
            context.external_occupied,
        )
    ]
    assert context.relayout is True


def test_xmltv_save_skips_merge_when_no_content(tmp_path):
    context = _context(tmp_path, tmp_path / "guide.xml")

    channel_output.stage_xmltv_save(
        context,
        get_team_xmltv=lambda _conn: [],
        get_group_xmltv=lambda _conn: [],
        merge_xmltv=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("merged")),
    )

    assert context.progress_events == [("saving", 95, "Saving XMLTV...")]
    assert context.result.file_written is False
    assert context.result.file_path is None
    assert context.result.file_size == 0


def test_xmltv_save_skips_merge_when_output_path_is_missing(tmp_path):
    context = _context(tmp_path)

    channel_output.stage_xmltv_save(
        context,
        get_team_xmltv=lambda _conn: ["<team />"],
        get_group_xmltv=lambda _conn: ["<group />"],
        merge_xmltv=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("merged")),
    )

    assert context.result.file_written is False


def test_xmltv_save_merges_team_before_group_with_generator_metadata(tmp_path):
    output_path = tmp_path / "nested" / "guide.xml"
    context = _context(tmp_path, output_path)
    calls = []

    def merge(contents, *, generator_name, generator_url):
        calls.append((contents, generator_name, generator_url))
        return "<tv>merged</tv>"

    channel_output.stage_xmltv_save(
        context,
        get_team_xmltv=lambda _conn: ["team-1", "team-2"],
        get_group_xmltv=lambda _conn: ["group-1"],
        merge_xmltv=merge,
    )

    assert calls == [
        (
            ["team-1", "team-2", "group-1"],
            "Teamarr test",
            "https://example.test/teamarr",
        )
    ]
    assert output_path.read_text() == "<tv>merged</tv>"
    assert context.result.file_written is True
    assert context.result.file_path == str(output_path.absolute())
    assert context.result.file_size == len("<tv>merged</tv>")
