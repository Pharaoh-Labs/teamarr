"""Sources whose Dispatcharr group is gone (lylt.1, #1058).

Every generation run asks Dispatcharr for its channel groups and marks each
source present or missing. A missing hand-made source is listed under
Sources → Automation → Remove; with ``source_missing_delete_days`` set it is
deleted on its own once it has been missing that long. Discovered (managed)
sources are retired by the daily pass instead (``discovery.maintain_managed_sources``).
"""

import logging
from typing import Any

from teamarr.dispatcharr.factory import get_dispatcharr_connection
from teamarr.utilities.tz import now_utc, parse_db_timestamp

from .policy import SourceLifecyclePolicy, load_policy

logger = logging.getLogger(__name__)


def detect_stale_groups(db_factory: Any) -> list[dict]:
    """Detect managed event groups whose Dispatcharr M3U source group is gone.

    A group is "stale" when it is enabled, has an ``m3u_group_id``, and that
    channel group no longer exists in Dispatcharr — i.e. the source was
    deleted/renamed. This is distinct from off-season (the group still exists
    with zero current streams): Dispatcharr channel-groups are persistent, so an
    off-season group is still returned by ``list_groups()`` and is NOT flagged.

    Side effect: refreshes ``source_last_seen`` for present sources and sets
    ``source_missing`` for missing ones. If Dispatcharr is unreachable or returns
    no groups, nothing is flagged (avoids false mass-staleness on a blip).

    Returns:
        The current list of stale groups (``get_stale_groups``).
    """
    from teamarr.consumers.source_lifecycle.discovery import _group_account_ids
    from teamarr.database.groups import (
        get_stale_groups,
        mark_group_source_missing,
        mark_group_source_seen,
    )
    from teamarr.database.source_candidates import (
        ScanEvidence,
        account_key,
        dismissed_groups,
        move_accepted_candidate,
    )
    from teamarr.utilities.m3u_group_identity import rotating_group_key

    conn_dc = get_dispatcharr_connection(db_factory=db_factory)
    if conn_dc is None:
        logger.debug("[STALE_GROUPS] Dispatcharr not configured — skipping detection")
        return []

    try:
        live_groups = conn_dc.m3u.list_groups()
    except Exception as e:  # noqa: BLE001 — detection must never break generation
        logger.warning("[STALE_GROUPS] Could not list Dispatcharr groups: %s", e)
        return []

    if not live_groups:
        # Empty almost always means a connection/auth issue, not "all sources gone".
        logger.debug("[STALE_GROUPS] Dispatcharr returned no groups — skipping detection")
        return []

    existing_ids = {g.id for g in live_groups}
    # Map name -> live ids so a source recreated under a NEW id (same name) is
    # recognised as still present, not stale. Dispatcharr group names (e.g.
    # "USA | NCAA BASEBALL ⚾") are specific enough to identify the source.
    groups_by_name: dict[str, list[Any]] = {}
    for g in live_groups:
        groups_by_name.setdefault(g.name, []).append(g)

    try:
        live_accounts = conn_dc.m3u.list_accounts()
        account_ids_by_name = {a.name: a.id for a in live_accounts}
        account_names_by_id = {a.id: a.name for a in live_accounts}
    except Exception:
        account_ids_by_name = {}
        account_names_by_id = {}

    with db_factory() as conn:
        rows = conn.execute(
            """
            SELECT id, name, m3u_group_id, m3u_group_name, m3u_account_id, m3u_account_name
            FROM event_epg_groups
            WHERE enabled = 1
              AND m3u_group_id IS NOT NULL
              AND COALESCE(is_channel_source, 0) = 0
            """
        ).fetchall()
        bound_accounts: dict[int, dict[int, int]] = {}
        for group_id, source_id, account_id in conn.execute(
            """
            SELECT m3u_group_id, id, m3u_account_id FROM event_epg_groups
            WHERE m3u_group_id IS NOT NULL AND COALESCE(is_channel_source, 0) = 0
            """
        ):
            bound_accounts.setdefault(group_id, {})[source_id] = account_key(account_id)
        dismissed_ids, _ = dismissed_groups(conn)
        accepted_candidates = {
            r["source_group_id"]: r["id"]
            for r in conn.execute(
                """
                SELECT id, source_group_id FROM source_candidates
                WHERE status = 'accepted' AND source_group_id IS NOT NULL
                """
            ).fetchall()
        }

        def can_rebind(group: Any, acc_key: int) -> bool:
            # An unscoped source reads all accounts; scoped sources can share a group.
            taken = bound_accounts.get(group.id, {}).values()
            if 0 in taken or acc_key in taken or (acc_key == 0 and taken):
                return False
            if (group.id, acc_key) in dismissed_ids or (group.id, 0) in dismissed_ids:
                return False
            accounts = _group_account_ids(group)
            return not acc_key or not accounts or acc_key in accounts

        def rebind(row: Any, group: Any, acc_id: int | None) -> bool:
            candidate_id = accepted_candidates.get(row["id"])
            if candidate_id is not None and not move_accepted_candidate(
                conn,
                candidate_id,
                ScanEvidence(
                    m3u_group_id=group.id,
                    m3u_group_name=group.name,
                    m3u_account_id=acc_id,
                ),
            ):
                return False
            conn.execute(
                "UPDATE event_epg_groups SET m3u_group_id = ?, m3u_group_name = ? WHERE id = ?",
                (group.id, group.name, row["id"]),
            )
            mark_group_source_seen(conn, row["id"])
            bound_accounts[row["m3u_group_id"]].pop(row["id"])
            bound_accounts.setdefault(group.id, {})[row["id"]] = account_key(acc_id)
            logger.info(
                "[STALE_GROUPS] Healed '%s' source %s (%r) -> %s (%r)",
                row["name"],
                row["m3u_group_id"],
                row["m3u_group_name"],
                group.id,
                group.name,
            )
            return True

        for row in rows:
            source_acc_id = row["m3u_account_id"]
            account_name = account_names_by_id.get(source_acc_id)
            if account_name and account_name != row["m3u_account_name"]:
                conn.execute(
                    "UPDATE event_epg_groups SET m3u_account_name = ? WHERE id = ?",
                    (account_name, row["id"]),
                )
            # Auto-heal stale m3u_account_id if account ID no longer exists but name matches
            if (
                source_acc_id
                and account_names_by_id
                and source_acc_id not in account_names_by_id
            ):
                target_acc_id = account_ids_by_name.get(row["m3u_account_name"] or "")
                if target_acc_id:
                    conn.execute(
                        "UPDATE event_epg_groups SET m3u_account_id = ? WHERE id = ?",
                        (target_acc_id, row["id"]),
                    )
                    logger.info(
                        "[STALE_GROUPS] Healed '%s' account id %s -> %s",
                        row["name"],
                        source_acc_id,
                        target_acc_id,
                    )
                    source_acc_id = target_acc_id
                    bound_accounts[row["m3u_group_id"]][row["id"]] = account_key(target_acc_id)

            if row["m3u_group_id"] in existing_ids:
                mark_group_source_seen(conn, row["id"])
                continue
            # Prefer a same-named replacement, but only among eligible groups.
            # A same-named group on another account must not hide a rotation.
            acc_key = account_key(source_acc_id)
            old_name = row["m3u_group_name"] or ""
            same_name = [g for g in groups_by_name.get(old_name, []) if can_rebind(g, acc_key)]
            if len(same_name) > 1:
                # Preserve the existing ambiguous-exact-name behavior.
                mark_group_source_seen(conn, row["id"])
                continue
            if same_name and rebind(row, same_name[0], source_acc_id):
                continue

            rot_key = rotating_group_key(old_name)
            if rot_key is not None:
                rot_candidates = [
                    g
                    for g in live_groups
                    if g.name != old_name
                    and rotating_group_key(g.name or "") == rot_key
                    and can_rebind(g, acc_key)
                ]
                if len(rot_candidates) == 1 and rebind(row, rot_candidates[0], source_acc_id):
                    continue

            mark_group_source_missing(conn, row["id"])

        # Channel-source rows (#542) read a Dispatcharr channel group by id.
        # One whose group was deleted stays selected and keeps running under
        # its last name, fetching nothing, with nothing telling the user
        # (#1046). Flag it the same way; it never enters the stale list, which
        # is the M3U rebind/delete flow. The catch-all row (NULL id) reads
        # every group and is always present.
        for row in conn.execute(
            """
            SELECT id, dispatcharr_channel_group_id AS dp_id
            FROM event_epg_groups
            WHERE enabled = 1 AND COALESCE(is_channel_source, 0) = 1
            """
        ).fetchall():
            if row["dp_id"] is None or row["dp_id"] in existing_ids:
                mark_group_source_seen(conn, row["id"])
            else:
                mark_group_source_missing(conn, row["id"])
        _delete_long_missing(conn, load_policy(conn))
        stale = get_stale_groups(conn)

    if stale:
        logger.info(
            "[STALE_GROUPS] %d group(s) have a missing Dispatcharr source: %s",
            len(stale),
            ", ".join(g["name"] for g in stale),
        )
    return stale


def _delete_long_missing(conn: Any, policy: SourceLifecyclePolicy) -> int:
    """Delete hand-made sources whose group has been missing for the policy's days.

    Off by default (0 = never): deleting a source drops its league scope,
    keywords and overrides, so the user opts in. Only an enabled, hand-made
    (not managed, not channel-source) row with a recorded last-seen time is
    eligible — a row never seen since the column existed is left alone rather
    than guessed. Managed sources have their own window in the daily pass.
    Deleting here is the same path as the Sources page delete: the row and its
    channels go, and its discovery candidate is dismissed so the group is not
    suggested straight back.
    """
    days = policy.missing_delete_days
    if days <= 0:
        return 0
    from teamarr.database.groups import delete_group
    from teamarr.database.source_candidates import dismiss_candidate_for_source

    now = now_utc()
    removed = 0
    rows = conn.execute(
        """
        SELECT id, name, source_last_seen FROM event_epg_groups
        WHERE enabled = 1 AND source_missing = 1 AND source_last_seen IS NOT NULL
          AND COALESCE(managed, 0) = 0 AND COALESCE(is_channel_source, 0) = 0
        """
    ).fetchall()
    for row in rows:
        seen = parse_db_timestamp(row["source_last_seen"])
        if seen is None:
            continue
        missing_for = (now - seen).total_seconds() / 86400
        if missing_for < days:
            continue
        delete_group(conn, row["id"])
        dismiss_candidate_for_source(conn, row["id"])
        removed += 1
        logger.info(
            "[STALE_GROUPS] Deleted source %r: group missing from Dispatcharr for %d days",
            row["name"],
            int(missing_for),
        )
    return removed
