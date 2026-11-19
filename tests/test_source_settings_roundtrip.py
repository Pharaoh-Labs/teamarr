from teamarr.api.routes import groups


def test_source_playoff_override_and_timezone_round_trip(db_factory, monkeypatch):
    monkeypatch.setattr(groups, "get_db", db_factory)
    created = groups.create_group(
        groups.GroupCreate(
            name="Test source", stream_timezone="America/New_York", bypass_filter_for_playoffs=True
        )
    )

    assert created.bypass_filter_for_playoffs is True
    listed = groups.list_groups(include_disabled=False, include_stats=False).groups[0]
    assert listed.stream_timezone == "America/New_York"
    assert listed.bypass_filter_for_playoffs is True

    updated = groups.update_group_by_id(
        created.id, groups.GroupUpdate(bypass_filter_for_playoffs=False)
    )
    assert updated.bypass_filter_for_playoffs is False
    groups.update_group_by_id(created.id, groups.GroupUpdate(clear_bypass_filter_for_playoffs=True))
    assert groups.get_group_by_id(created.id).bypass_filter_for_playoffs is None
