"""Create share-safe diagnostic exports for support requests."""
# ruff: noqa: E501

import io
import json
import os
import re
import sqlite3
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from teamarr.config import BASE_VERSION
from teamarr.database.channels.types import ManagedChannelStream
from teamarr.database.connection import get_connection
from teamarr.database.stats import get_failed_matches, get_matched_streams, get_recent_runs
from teamarr.services.stream_ordering import get_stream_ordering_service
from teamarr.utilities.logging import _get_log_dir

SCHEMA_VERSION = 1
RUN_LIMIT = 100
MATCH_DETAIL_LIMIT = 500
CHANNEL_LIMIT = 2_000
LOG_BYTES = 256 * 1024
REDACTED = "[REDACTED]"

_SECRET_KEY = re.compile(
    r"(?:pass(?:word)?|api[_-]?key|token|authorization|secret|stream[_-]?url)", re.I
)
_URL = re.compile(r"(?:https?|rtmp|rtsp)://[^\s\"'<>]+", re.I)
_TOKEN_VALUE = re.compile(r"(?:sb_(?:publishable|secret)_[\w.-]+|bearer\s+\S+)", re.I)


class SupportBundleService:
    """Build a bounded ZIP without exposing source credentials or account names."""

    def __init__(self, db_path: Path | str | None = None, log_dir: Path | None = None):
        self.db_path = db_path
        self.log_dir = log_dir or _get_log_dir()
        self._account_names: set[str] = set()

    def create(self) -> bytes:
        conn = get_connection(self.db_path)
        try:
            self._account_names = self._account_names_from(conn)
            report, recent_runs, run_details = self._collect(conn)
        finally:
            conn.close()

        guide = self._guide(report)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("AGENTS.md", guide)
            archive.writestr("support-report.json", self._json(report))
            archive.writestr("recent-runs.json", self._json(recent_runs))
            archive.writestr("recent-run-stream-details.json", self._json(run_details))
            for name in ("teamarr.log", "teamarr_errors.log"):
                content = self._log_tail(name)
                if content is not None:
                    archive.writestr(f"logs/{name.replace('.log', '-recent.log')}", content)
        return output.getvalue()

    def _collect(
        self, conn: sqlite3.Connection
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        errors: list[str] = []
        settings = self._singleton(conn, "settings", errors)
        sources = self._rows(conn, "event_epg_groups", errors)
        teams = self._rows(conn, "teams", errors)
        channels = self._channels(conn, errors)
        runs = [run.to_dict() for run in get_recent_runs(conn, limit=RUN_LIMIT)]
        details = self._run_details(conn, runs, errors)
        templates = self._template_inventory(conn, teams, sources, errors)
        report = {
            "schema_version": SCHEMA_VERSION,
            "summary": {
                "captured_at": datetime.now(UTC).isoformat(),
                "teamarr_version": BASE_VERSION,
                "python_version": sys.version.split()[0],
                "platform": sys.platform,
            },
            "signals": self._signals(settings, sources, teams, channels, runs),
            "configuration": {
                "settings": settings,
                "aliases": self._rows(conn, "team_aliases", errors),
                "detection_keywords": self._rows(conn, "detection_keywords", errors),
                "exception_keywords": self._rows(conn, "consolidation_exception_keywords", errors),
                "condition_presets": self._rows(conn, "condition_presets", errors),
                "stream_ordering": self._safe_stream_ordering(conn, errors),
            },
            "templates": templates,
            "sources_and_subscriptions": {
                "sources": sources,
                "sports_subscription": self._singleton(conn, "sports_subscription", errors),
                "league_config": self._rows(conn, "subscription_league_config", errors),
                "leagues": self._rows(conn, "leagues", errors),
                "source_template_mappings": self._rows(conn, "group_templates", errors),
            },
            "channels": channels,
            "generation": {"recent_run_count": len(runs), "run_limit": RUN_LIMIT},
            "matching": {
                "detail_limit_per_run": MATCH_DETAIL_LIMIT,
                "persistent_corrections": self._rows(conn, "match_corrections", errors),
                "user_corrected_cache_entries": self._corrected_cache_entries(conn, errors),
            },
            "reconciliation": {"note": "Run reconciliation separately; this bundle is read-only."},
            "environment": {"log_directory_configured": bool(os.getenv("LOG_DIR"))},
            "collection_errors": errors,
        }
        return (
            self._sanitize(report),
            self._sanitize({"runs": runs, "limit": RUN_LIMIT}),
            self._sanitize(details),
        )

    def _corrected_cache_entries(
        self, conn: sqlite3.Connection, errors: list[str]
    ) -> list[dict[str, Any]]:
        try:
            rows = conn.execute(
                "SELECT * FROM stream_match_cache WHERE user_corrected = 1 LIMIT ?",
                (CHANNEL_LIMIT,),
            ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            errors.append(f"Could not collect user-corrected match cache entries: {exc}")
            return []

    def _singleton(
        self, conn: sqlite3.Connection, table: str, errors: list[str]
    ) -> dict[str, Any] | None:
        rows = self._query(conn, table, errors, limit=1)
        return rows[0] if rows else None

    def _rows(
        self, conn: sqlite3.Connection, table: str, errors: list[str]
    ) -> list[dict[str, Any]]:
        return self._query(conn, table, errors)

    def _query(
        self, conn: sqlite3.Connection, table: str, errors: list[str], limit: int = CHANNEL_LIMIT
    ) -> list[dict[str, Any]]:
        try:
            rows = conn.execute(f"SELECT * FROM [{table}] LIMIT ?", (limit,)).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            errors.append(f"Could not collect {table}: {exc}")
            return []

    def _account_names_from(self, conn: sqlite3.Connection) -> set[str]:
        try:
            rows = conn.execute(
                "SELECT DISTINCT m3u_account_name FROM managed_channel_streams "
                "WHERE m3u_account_name IS NOT NULL"
            ).fetchall()
            return {str(row[0]) for row in rows if row[0]}
        except sqlite3.Error:
            return set()

    def _template_inventory(
        self,
        conn: sqlite3.Connection,
        teams: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        errors: list[str],
    ) -> dict[str, Any]:
        templates = self._query(conn, "templates", errors)
        inventory = [
            {
                key: template.get(key)
                for key in (
                    "id",
                    "name",
                    "template_type",
                    "sport",
                    "league",
                    "created_at",
                    "updated_at",
                )
            }
            for template in templates
        ]
        known_ids = {template["id"] for template in inventory}
        missing = sorted(
            {
                row["template_id"]
                for row in [*teams, *sources]
                if row.get("template_id") is not None and row["template_id"] not in known_ids
            }
        )
        return {
            "inventory": inventory,
            "team_assignments": [
                {
                    "team_id": team.get("id"),
                    "team_name": team.get("team_name"),
                    "template_id": team.get("template_id"),
                }
                for team in teams
            ],
            "source_assignments": [
                {
                    "source_id": source.get("id"),
                    "source_name": source.get("name"),
                    "template_id": source.get("template_id"),
                }
                for source in sources
            ],
            "missing_template_ids": missing,
        }

    def _channels(self, conn: sqlite3.Connection, errors: list[str]) -> dict[str, Any]:
        channels = self._query(conn, "managed_channels", errors)
        stream_rows = self._query(conn, "managed_channel_streams", errors)
        groups = {
            row["id"]: row.get("name") for row in self._query(conn, "event_epg_groups", errors)
        }
        ordering = self._safe_stream_ordering(conn, errors)
        by_channel: dict[int, list[dict[str, Any]]] = {}
        for stream in stream_rows:
            model = ManagedChannelStream.from_row(stream)
            stream.pop("m3u_account_name", None)
            stream.pop("m3u_account_id", None)
            stream["source_group_name"] = groups.get(stream.get("source_group_id"))
            stream["matched_rules"] = self._matched_rules(
                ordering, model, stream.get("source_group_name")
            )
            channel_id = stream.get("managed_channel_id")
            if isinstance(channel_id, int):
                by_channel.setdefault(channel_id, []).append(stream)

        channel_entries = []
        for channel in channels:
            channel_id = channel.get("id")
            stream_assignments = (
                by_channel.get(channel_id, []) if isinstance(channel_id, int) else []
            )
            channel_entries.append({**channel, "streams": stream_assignments})
        return {
            "total": len(channels),
            "channels": channel_entries,
        }

    def _safe_stream_ordering(self, conn: sqlite3.Connection, errors: list[str]) -> Any:
        try:
            service = get_stream_ordering_service(conn)
            return [
                {
                    "type": rule.type,
                    "value": rule.value,
                    "priority": rule.priority,
                    "mode": rule.mode,
                    "points": rule.points,
                }
                for rule in service.rules
            ]
        except Exception as exc:  # Optional diagnostics must not block export.
            errors.append(f"Could not collect stream ordering: {exc}")
            return []

    @staticmethod
    def _matched_rules(
        rules: Any, stream: ManagedChannelStream, group_name: str | None
    ) -> list[dict[str, Any]]:
        try:
            return [
                {
                    "type": evaluation.type,
                    "value": evaluation.value,
                    "band": evaluation.priority,
                    "mode": evaluation.mode,
                    "points": evaluation.points,
                    "is_band_winner": evaluation.is_winner,
                }
                for evaluation in rules.evaluate_rules(stream, group_name)
            ]
        except Exception:
            return []

    def _run_details(
        self, conn: sqlite3.Connection, runs: list[dict[str, Any]], errors: list[str]
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"runs": {}, "limit_per_run": MATCH_DETAIL_LIMIT}
        for run in runs:
            run_id = run.get("id")
            if run_id is None:
                continue
            try:
                result["runs"][str(run_id)] = {
                    "matched": get_matched_streams(conn, run_id=run_id, limit=MATCH_DETAIL_LIMIT),
                    "failed": get_failed_matches(conn, run_id=run_id, limit=MATCH_DETAIL_LIMIT),
                }
            except sqlite3.Error as exc:
                errors.append(f"Could not collect match details for run {run_id}: {exc}")
        return result

    def _signals(
        self,
        settings: dict[str, Any] | None,
        sources: list[dict[str, Any]],
        teams: list[dict[str, Any]],
        channels: dict[str, Any],
        runs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        if not settings or not settings.get("dispatcharr_enabled"):
            signals.append(
                {
                    "code": "dispatcharr_disabled",
                    "severity": "warning",
                    "message": "Dispatcharr integration is disabled.",
                }
            )
        if not any(source.get("enabled") for source in sources):
            signals.append(
                {
                    "code": "no_enabled_sources",
                    "severity": "critical",
                    "message": "No enabled event sources are configured.",
                }
            )
        unassigned = [
            team.get("team_name")
            for team in teams
            if team.get("active") and not team.get("template_id")
        ]
        if unassigned:
            signals.append(
                {
                    "code": "teams_without_template",
                    "severity": "warning",
                    "message": "Active teams have no template assigned.",
                    "evidence": {"teams": unassigned},
                }
            )
        if runs and runs[0].get("status") in {"failed", "cancelled", "partial"}:
            signals.append(
                {
                    "code": "latest_run_not_completed",
                    "severity": "warning",
                    "message": "The latest generation did not complete.",
                    "evidence": {"run_id": runs[0].get("id"), "status": runs[0].get("status")},
                }
            )
        if not channels.get("total"):
            signals.append(
                {
                    "code": "no_managed_channels",
                    "severity": "info",
                    "message": "No managed channels are currently stored.",
                }
            )
        rank = {"critical": 0, "warning": 1, "info": 2}
        return sorted(signals, key=lambda item: (rank[item["severity"]], item["code"]))

    def _sanitize(self, value: Any, key: str | None = None) -> Any:
        if key and (_SECRET_KEY.search(key) or "m3u_account" in key.lower()):
            return REDACTED
        if isinstance(value, sqlite3.Row):
            value = dict(value)
        if isinstance(value, dict):
            return {str(k): self._sanitize(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        if isinstance(value, (datetime, Path)):
            return str(value)
        if isinstance(value, str):
            sanitized = _TOKEN_VALUE.sub(REDACTED, _URL.sub(REDACTED, value))
            for account_name in self._account_names:
                sanitized = sanitized.replace(account_name, REDACTED)
            return sanitized
        return value

    def _log_tail(self, filename: str) -> str | None:
        path = self.log_dir / filename
        try:
            with path.open("rb") as handle:
                handle.seek(max(0, path.stat().st_size - LOG_BYTES))
                return self._sanitize(handle.read().decode("utf-8", errors="replace"))
        except OSError:
            return None

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, indent=2, sort_keys=False, default=str) + "\n"

    def _guide(self, report: dict[str, Any]) -> str:
        signals = report["signals"]
        lines = [
            "---",
            f"bundle_schema_version: {SCHEMA_VERSION}",
            "report_path: support-report.json",
            "report_format: json",
            "redaction: stream URLs, M3U account names, and credentials are excluded",
            f"captured_at: {report['summary']['captured_at']}",
            "---",
            "",
            "# Support Bundle",
            "",
            "## Read First",
            "Read `support-report.json` first. Use `recent-runs.json` and `recent-run-stream-details.json` for run evidence.",
            "",
            "## Signal Summary",
        ]
        if signals:
            lines.extend(
                f"- **{signal['severity']}** `{signal['code']}`: {signal['message']}"
                for signal in signals
            )
        else:
            lines.append("- No automatic signals were found.")
        lines.extend(
            [
                "",
                "## Report Layout",
                "`support-report.json` contains summary, signals, configuration, templates, sources_and_subscriptions, channels, generation, matching, reconciliation, environment, and collection_errors.",
                "",
                "## Collection Limits",
                f"Recent runs: {RUN_LIMIT}; matched/failed stream details per run: {MATCH_DETAIL_LIMIT}; log tail per file: {LOG_BYTES} bytes.",
                "",
                "## Privacy and Exclusions",
                "Stream URLs, M3U account names, credentials, tokens, raw template bodies, raw XMLTV, and provider cache payloads are excluded.",
                "",
                "## Suggested Triage",
                "Review critical signals, collection_errors, recent failed runs and logs, source subscription overrides/template mappings, then managed channels and stream ordering evidence.",
                "",
            ]
        )
        return "\n".join(lines)
