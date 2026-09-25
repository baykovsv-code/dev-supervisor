#!/usr/bin/env python3
"""Conservative local supervisor for one-ticket-at-a-time Codex development."""

from __future__ import annotations

import argparse
import base64
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterable, Protocol
from urllib.parse import urlsplit
import uuid


TOOL_DIR = Path(__file__).resolve().parent
PROJECT_POLICY_NAME = "dev-supervisor.json"
ENGINE_BINDING_NAME = "engine.json"
ENGINE_BINDING_VERSION = 2
ENGINE_PROTOCOL_VERSION = 1
ENGINE_ARCHIVES_DIRECTORY = "engine-archives"
ENGINE_UPDATE_NAME = "engine-update.json"
LEGACY_CUTOVER_NAME = "legacy-cutover.json"
LEGACY_CUTOVER_ARCHIVES_DIRECTORY = "legacy-cutover-archives"
HOST_OWNER_NAME = "host-owner.json"
REPORT_FIELDS = {
    "role", "ticket", "status", "acceptance_passed", "tests_passed",
    "architecture_deviation", "ambiguity", "product_decision_required",
    "next_ticket_safe", "files_changed", "summary", "blockers", "checks_run",
}
# Keep this list aligned with the strict Structured Outputs subset used by
# `codex exec --output-schema`. The recursive preflight below rejects every
# unknown keyword as well; these names document especially easy JSON Schema
# features to accidentally add even though the API response format forbids them.
CODEX_UNSUPPORTED_SCHEMA_KEYWORDS = frozenset({
    "allOf", "not", "dependentRequired", "dependentSchemas", "if", "then", "else",
    "oneOf", "uniqueItems", "minLength", "maxLength", "patternProperties",
    "minProperties", "maxProperties", "propertyNames", "contains", "minContains",
    "maxContains", "prefixItems", "additionalItems", "unevaluatedItems",
    "unevaluatedProperties",
})
CODEX_SUPPORTED_SCHEMA_KEYWORDS = frozenset({
    "$schema", "$defs", "$ref", "title", "description", "type", "enum", "const",
    "properties", "required", "additionalProperties", "items", "anyOf", "pattern",
    "format", "multipleOf", "minimum", "maximum", "exclusiveMinimum",
    "exclusiveMaximum", "minItems", "maxItems",
})
DEFAULT_SUPERVISOR_CONTROL_PATHS = ("dev", PROJECT_POLICY_NAME)
POLICY_VERSION = 3
HOST_CAPABILITIES_NAME = "host-capabilities.json"
CAPABILITY_NAMES = (
    "self_modification",
    "user_requested_modification",
    "repository_push",
)
DIAGNOSTIC_CLASSIFICATIONS = frozenset({
    "PRODUCT_FIX", "HOST_VERIFICATION_REQUIRED", "SUPERVISOR_BUG",
    "ARCHITECTURE_DECISION", "HUMAN_DECISION_REQUIRED",
})
TERMINAL_STATES = {
    "HUMAN_GATE", "QUOTA_CHECK_REQUIRED", "QUOTA_LOW", "QUOTA_EXHAUSTED",
    "VERIFICATION_FAILED", "GIT_BLOCKED", "SCOPE_BLOCKED", "REPORT_INVALID",
    "INVOCATION_FAILED", "IMPLEMENTATION_FAILED", "ARCHITECTURE_FAILED",
    "PERIODIC_CHECKPOINT", "INTERRUPTED", "DIAGNOSTIC_FAILED",
    "SUPERVISOR_REPAIR_FAILED", "PLAN_COMPLETED", "MIGRATION_BLOCKED",
}
STATE_VERSION = 7
STATE_PREDECESSORS_DIRECTORY = "state-predecessors"
COLD_START_STATE_NAME = "cold-start.json"
COLD_START_DIRECTORY = "cold-start"
COLD_START_PHASES = {"REQUIREMENTS_REVIEW", "ARCHITECTURE_REVIEW", "PLAN_READY"}
ADMISSION_STATE_NAME = "admission.json"
ADMISSION_DIRECTORY = "admission"
ADMISSION_SCENARIOS = {"A", "B"}
ADMISSION_STATUSES = {"compatible", "conditionally_compatible", "incompatible"}
ADMISSION_DOCUMENT_FIELDS = {"path", "external_id", "digest"}
ADMISSION_MANIFEST_FIELDS = {"version", "source_documents", "external_identifiers", "mapping"}
ADMISSION_MAPPING_FIELDS = {"status", "covered_requirements", "gaps", "contradictions", "unknowns"}
BACKLOG_CYCLE_STATE_NAME = "backlog-cycle.json"
BACKLOG_CYCLE_DIRECTORY = "backlog-cycles"
BACKLOG_CYCLE_PHASES = {"BACKLOG_REVIEW", "ARCHITECTURE_REVIEW", "APPROVAL_WAIT", "READY_EPOCH"}
IMPROVEMENT_STATE_NAME = "improvement.json"
IMPROVEMENT_DIRECTORY = "improvements"
IMPROVEMENT_KINDS = {"user_improvement", "self_development"}
IMPROVEMENT_PHASES = {
    "ARCHITECTURE_IMPACT", "APPROVAL_WAIT", "BOUNDED_PLAN_READY",
    "SUCCESSOR_STAGED", "ESCALATED_NORMAL_CYCLE",
}
QUOTA_STATES = {"QUOTA_CHECK_REQUIRED", "QUOTA_LOW", "QUOTA_EXHAUSTED"}
RATE_LIMIT_MARKERS = (
    "rate limit", "rate_limit", "usage limit", "usage_limit", "quota exhausted",
    "insufficient quota", "too many requests", "429",
)
NETWORK_FAILURE_MARKERS = (
    "network error", "connection reset", "connection refused", "connection closed",
    "dns", "timed out", "timeout connecting", "transport error",
)


class SupervisorError(RuntimeError):
    """A fail-closed supervisor error suitable for display."""


def _capability_values(value: Any, *, source: str) -> dict[str, bool]:
    """Validate one capability map; absence is deliberately an all-deny map."""
    denied = dict.fromkeys(CAPABILITY_NAMES, False)
    if value is None:
        return denied
    if not isinstance(value, dict) or set(value) - set(CAPABILITY_NAMES):
        raise SupervisorError(f"{source} capabilities must contain only supported capability names")
    for name, enabled in value.items():
        if not isinstance(enabled, bool):
            raise SupervisorError(f"{source} capability {name!r} must be a boolean")
        denied[name] = enabled
    return denied


def _observed_quota_policy(legacy: dict[str, Any]) -> dict[str, Any]:
    """Make the explicit v3 ranges corresponding to a v1/v2 reserve policy."""
    roles = ("implementation", "architecture", "diagnostic", "supervisor_repair")
    result: dict[str, Any] = {
        "provider": "manual", "account_id": "manual-observation",
        "high_reuse_ttl_minutes": 30, "high_reuse_invocation_count": 1,
        "roles": {},
    }
    for role in roles:
        reserve = legacy.get(role, {}) if isinstance(legacy, dict) else {}
        result["roles"][role] = {}
        for window, old_key in (("five_hour", "five_hour_percent_left"), ("weekly", "weekly_percent_left")):
            medium = reserve.get(old_key, 100) if isinstance(reserve, dict) else 100
            if isinstance(medium, bool) or not isinstance(medium, (int, float)) or not math.isfinite(medium):
                medium = 100
            medium = max(1, min(99, int(medium)))
            result["roles"][role][window] = {
                "low": {"minimum_percent": 0, "maximum_percent": medium - 1},
                "medium": {"minimum_percent": medium, "maximum_percent": min(99, medium + 29)},
                "high": {"minimum_percent": min(100, medium + 30), "maximum_percent": 100},
            }
    return result


def _default_improvement_policy() -> dict[str, Any]:
    """Conservative bounds for an explicitly requested out-of-plan review."""
    return {
        "max_tickets": 1,
        "max_description_characters": 2000,
        "successor_directory": ".dev-supervisor/successors",
    }


def migrate_legacy_policy(policy: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return an in-memory v3 policy and an explicit, non-writing migration report."""
    if policy.get("version") not in {1, 2}:
        raise SupervisorError("legacy policy migration only supports versions 1 and 2")
    source_version = policy["version"]
    migrated = deepcopy(policy)
    migrated["version"] = POLICY_VERSION
    # Preserve the 1.x absence semantics: only an explicit ``external`` selected
    # the external repair boundary.
    migrated.setdefault("supervisor_repair_repository", "embedded")
    migrated["capabilities"] = _capability_values(policy.get("capabilities"), source="legacy project")
    removed: list[str] = []
    migrated.pop("forecast", None)
    removed.append("forecast")
    migrated["quota"] = _observed_quota_policy(policy.get("quota", {}))
    migrated.setdefault("improvement", _default_improvement_policy())
    return migrated, {
        "from_version": source_version,
        "to_version": POLICY_VERSION,
        "removed_fields": removed,
        "writes_required": True,
    }


def validate_project_policy(policy: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Validate the versioned policy before it can authorize any operation."""
    version = policy.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise SupervisorError(f"unsupported project policy version: {version!r}")
    if version in {1, 2}:
        migrated, migration = migrate_legacy_policy(policy)
        validated, _ = validate_project_policy(migrated)
        return validated, migration
    if version != POLICY_VERSION:
        raise SupervisorError(f"unsupported project policy version: {version!r}")
    required = {
        "version", "expected_branch", "bootstrap_ticket", "initial_completed_tickets",
        "implementation_plan", "authoritative_documents", "supervisor_control_paths",
        "supervisor_repair_repository", "models", "quota", "diagnostic",
        "periodic_checkpoint", "model_watchdog", "milestones",
        "verification_commands", "supervisor_repair_verification_commands",
        "host_verification_capabilities", "ticket_verification_commands",
        "evidence_check_commands", "human_evidence_gates", "implementation_forbidden_paths",
        "architecture_allowed_paths", "capabilities",
        "improvement",
    }
    unknown = set(policy) - required
    missing = required - set(policy)
    if unknown or missing:
        raise SupervisorError(
            "project policy has unknown or missing keys: "
            + ", ".join(sorted(unknown | missing))
        )
    capabilities = _capability_values(policy["capabilities"], source="project")
    if policy["capabilities"] != capabilities:
        raise SupervisorError("project policy capabilities must explicitly declare every capability")
    roles = {"implementation", "architecture", "diagnostic", "supervisor_repair"}
    if not isinstance(policy["models"], dict) or set(policy["models"]) != roles:
        raise SupervisorError("project policy models must declare exactly the supported roles")
    for role, model in policy["models"].items():
        if (
            not isinstance(model, dict) or set(model) != {"model", "reasoning_effort"}
            or not all(isinstance(model.get(key), str) and model[key] for key in model)
        ):
            raise SupervisorError(f"model policy for {role!r} is malformed")
    quota = policy["quota"]
    if not isinstance(quota, dict) or set(quota) != {"provider", "account_id", "high_reuse_ttl_minutes", "high_reuse_invocation_count", "roles"}:
        raise SupervisorError("quota policy has unknown or missing keys")
    if quota["provider"] != "manual" or not isinstance(quota["account_id"], str) or not quota["account_id"]:
        raise SupervisorError("unsupported quota provider")
    for name in ("high_reuse_ttl_minutes", "high_reuse_invocation_count"):
        if isinstance(quota[name], bool) or not isinstance(quota[name], int) or quota[name] < 1:
            raise SupervisorError(f"quota.{name} must be a positive integer")
    if not isinstance(quota["roles"], dict) or set(quota["roles"]) != roles:
        raise SupervisorError("quota ranges must declare exactly the supported roles")
    for role, windows in quota["roles"].items():
        if not isinstance(windows, dict) or set(windows) != {"five_hour", "weekly"}:
            raise SupervisorError(f"quota ranges for {role!r} must declare five_hour and weekly")
        for window, ranges in windows.items():
            if not isinstance(ranges, dict) or set(ranges) != {"low", "medium", "high"}:
                raise SupervisorError(f"quota ranges for {role}.{window} are malformed")
            expected_minimum = 0
            for level in ("low", "medium", "high"):
                bounds = ranges[level]
                if not isinstance(bounds, dict) or set(bounds) != {"minimum_percent", "maximum_percent"}:
                    raise SupervisorError(f"quota {role}.{window}.{level} bounds are malformed")
                low, high = bounds["minimum_percent"], bounds["maximum_percent"]
                if any(isinstance(item, bool) or not isinstance(item, int) for item in (low, high)) or low != expected_minimum or not 0 <= low <= high <= 100:
                    raise SupervisorError(f"quota {role}.{window} ranges must be contiguous integer percentages")
                expected_minimum = high + 1
            if expected_minimum != 101:
                raise SupervisorError(f"quota {role}.{window} ranges must cover 0 through 100")
    watchdog = policy["model_watchdog"]
    if not isinstance(watchdog, dict) or set(watchdog) != {"warning_seconds", "hard_timeout_seconds", "terminate_grace_seconds"}:
        raise SupervisorError("model_watchdog has unknown or missing keys")
    if any(isinstance(watchdog[key], bool) or not isinstance(watchdog[key], int) or watchdog[key] < 0 for key in watchdog):
        raise SupervisorError("model_watchdog values must be nonnegative integers")
    if watchdog["warning_seconds"] > watchdog["hard_timeout_seconds"]:
        raise SupervisorError("model_watchdog warning_seconds cannot exceed hard_timeout_seconds")
    improvement = policy["improvement"]
    if not isinstance(improvement, dict) or set(improvement) != {
        "max_tickets", "max_description_characters", "successor_directory",
    }:
        raise SupervisorError("improvement policy has unknown or missing keys")
    for key in ("max_tickets", "max_description_characters"):
        if isinstance(improvement[key], bool) or not isinstance(improvement[key], int) or improvement[key] < 1:
            raise SupervisorError(f"improvement.{key} must be a positive integer")
    successor_directory = improvement["successor_directory"]
    if (
        not isinstance(successor_directory, str) or not successor_directory
        or Path(successor_directory).is_absolute() or ".." in Path(successor_directory).parts
    ):
        raise SupervisorError("improvement.successor_directory must be a safe relative path")
    return deepcopy(policy), None


def _validate_push_target(value: Any) -> dict[str, str]:
    """Validate a credential-free host-owned Git destination without probing it."""
    if not isinstance(value, dict) or set(value) != {"remote", "url", "branch"}:
        raise SupervisorError("host push target must contain only remote, url, and branch")
    remote, url, branch = value.get("remote"), value.get("url"), value.get("branch")
    if not all(isinstance(item, str) and item for item in (remote, url, branch)):
        raise SupervisorError("host push target values must be nonempty strings")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", remote) or remote.startswith("-"):
        raise SupervisorError("host push target remote name is malformed")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch) or branch.startswith("-") or ".." in branch or branch.endswith("."):
        raise SupervisorError("host push target branch is malformed")
    if any(character.isspace() or ord(character) < 32 for character in url):
        raise SupervisorError("host push target URL is malformed")
    parsed = urlsplit(url)
    if parsed.scheme in {"http", "https", "git"} and (parsed.username or parsed.password):
        raise SupervisorError("host push target URL must not contain credentials")
    if parsed.password is not None or parsed.query or parsed.fragment:
        raise SupervisorError("host push target URL must not contain credentials or query data")
    scp_style = re.fullmatch(r"(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9._-]+:[^\\s:]+", url)
    if parsed.scheme not in {"ssh", "https", "http", "file"} and not scp_style:
        raise SupervisorError("host push target URL has an unsupported identity format")
    if parsed.scheme and not parsed.netloc and parsed.scheme != "file":
        raise SupervisorError("host push target URL is malformed")
    if parsed.scheme == "file" and (not parsed.path or parsed.netloc not in {"", "localhost"}):
        raise SupervisorError("host push target file URL is malformed")
    return {"remote": remote, "url": url, "branch": branch}


def load_host_capability_grants(path: Path) -> tuple[dict[str, bool], dict[str, Any], dict[str, str] | None]:
    """Read host-only grants. Any absent or invalid grant fails closed, never raises authority."""
    denied = dict.fromkeys(CAPABILITY_NAMES, False)
    if not path.exists():
        return denied, {"source": str(path), "status": "absent"}, None
    try:
        value = read_json(path)
        if (
            not isinstance(value.get("version"), int)
            or set(value) not in ({"version", "capabilities"}, {"version", "capabilities", "push_target"})
            or isinstance(value.get("version"), bool)
            or value.get("version") not in {1, 2}
        ):
            raise SupervisorError("host capability grants have an unsupported version or keys")
        if value["version"] == 1 and set(value) != {"version", "capabilities"}:
            raise SupervisorError("v1 host capability grants cannot define a push target")
        if value["version"] == 2 and set(value) != {"version", "capabilities", "push_target"}:
            raise SupervisorError("v2 host capability grants require an explicit push target")
        grants = _capability_values(value["capabilities"], source="host")
        if value["capabilities"] != grants:
            raise SupervisorError("host capabilities must explicitly declare every capability")
        target = _validate_push_target(value["push_target"]) if value["version"] == 2 else None
        return grants, {"source": str(path), "status": "valid", "version": value["version"]}, target
    except SupervisorError as error:
        return denied, {"source": str(path), "status": "invalid", "error": str(error)}, None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise SupervisorError(f"invalid ISO8601 timestamp: {value!r}") from error
    if parsed.tzinfo is None:
        raise SupervisorError(f"timestamp must include a timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SupervisorError(f"missing file: {path}") from error
    except json.JSONDecodeError as error:
        raise SupervisorError(f"invalid JSON in {path}: {error}") from error
    if not isinstance(value, dict):
        raise SupervisorError(f"expected a JSON object in {path}")
    return value


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def canonical_json_bytes(value: Any) -> bytes:
    """Stable bytes for content identities; never use presentation JSON as identity."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def content_checksum(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def audit_event(kind: str, payload: dict[str, Any], predecessor_checksum: str | None = None) -> dict[str, Any]:
    """Create a self-verifying, append-only audit record without a journal service."""
    material = {"version": 1, "predecessor_checksum": predecessor_checksum, "kind": kind, "payload": payload}
    return {"event_id": content_checksum(material), **material}


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


class QuotaProvider(Protocol):
    """Provider boundary for future machine-readable quota sources."""

    def snapshot(self) -> dict[str, Any] | None:
        ...

    def evaluate(self, role: str, policy: dict[str, Any]) -> tuple[str, str]:
        ...

    def consume(
        self, observation_id: str, *, role: str, ticket: str,
        invocation_id: str, recovery: bool, policy: dict[str, Any],
    ) -> dict[str, Any]:
        ...

    def invalidate(self, observation_id: str, reason: str) -> None:
        ...


class ManualQuotaProvider:
    """Quota provider backed only by a user-observed, repository-local snapshot."""

    def __init__(self, path: Path, now: Callable[[], datetime] = utc_now, *, models: dict[str, Any] | None = None, quota_policy: dict[str, Any] | None = None):
        self.path = path
        self.now = now
        self.models = models or {}
        self.quota_policy = quota_policy or {}

    def snapshot(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        ledger = read_json(self.path)
        expected = {"version", "current_observation_id", "observations"}
        if set(ledger) != expected and set(ledger) != expected | {"predecessor"}:
            raise SupervisorError("quota ledger is missing durable observation-consumption state")
        if ledger.get("version") not in {2, 3} or not isinstance(ledger.get("observations"), list):
            raise SupervisorError("quota ledger has an unsupported version or malformed observations")
        current_id = ledger.get("current_observation_id")
        observations = ledger["observations"]
        identifiers = [
            item.get("observation_id") if isinstance(item, dict) else None
            for item in observations
        ]
        if (
            not isinstance(current_id, str)
            or not current_id
            or any(not isinstance(item, str) or not item for item in identifiers)
            or len(identifiers) != len(set(identifiers))
            or identifiers.count(current_id) != 1
        ):
            raise SupervisorError("quota ledger observation identity is missing, duplicate, or ambiguous")
        return dict(observations[identifiers.index(current_id)])

    def set(self, five_hour: float, weekly: float | None = None) -> dict[str, Any]:
        if five_hour is None:
            raise SupervisorError("five-hour percentage is required")
        for name, value in (("five-hour", five_hour), ("weekly", weekly)):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0 or value > 100
            ):
                raise SupervisorError(f"{name} percentage must be a finite number between 0 and 100")
        value: dict[str, Any] = {
            "observation_id": uuid.uuid4().hex,
            "observed_at": isoformat(self.now()),
            "five_hour_percent_left": five_hour,
            "weekly_percent_left": weekly,
            "source": "manual",
            "provider": self.quota_policy.get("provider"),
            "account_id": self.quota_policy.get("account_id"),
            "models": {role: config.get("model") for role, config in self.models.items()},
            "authorizations": [],
        }
        observations: list[dict[str, Any]] = []
        if self.path.exists():
            existing = read_json(self.path)
            if existing.get("version") == 2:
                raise SupervisorError(
                    "legacy quota ledger is inspection-only; run quota migration-dry-run "
                    "and quota migration-apply before recording a new observation"
                )
            if (
                existing.get("version") != 3
                or not isinstance(existing.get("observations"), list)
            ):
                raise SupervisorError("quota ledger is malformed; refusing to overwrite it")
            observations = list(existing["observations"])
        observations.append(value)
        atomic_write_json(self.path, {
            "version": 3,
            "current_observation_id": value["observation_id"],
            "observations": observations,
        })
        return value

    def migration_dry_run(self) -> dict[str, Any]:
        """Describe the only supported ledger conversion without modifying legacy evidence."""
        if not self.path.exists():
            raise SupervisorError("quota migration requires an existing ledger")
        source = read_json(self.path)
        if source.get("version") == 3:
            return {"status": "already_applied", "from_version": 3, "to_version": 3, "writes_required": False}
        if source.get("version") != 2 or not isinstance(source.get("observations"), list):
            raise SupervisorError("unsupported quota ledger migration source")
        target = self._convert_v2(source)
        checksum = content_checksum(source)
        return {"status": "supported", "from_version": 2, "to_version": 3, "writes_required": True,
                "source_checksum": checksum, "target_checksum": content_checksum(target),
                "archive": f"quota-predecessors/{checksum}.json"}

    def _convert_v2(self, source: dict[str, Any]) -> dict[str, Any]:
        observations = []
        for legacy in source["observations"]:
            if not isinstance(legacy, dict) or not isinstance(legacy.get("observation_id"), str):
                raise SupervisorError("legacy quota ledger observation is malformed")
            observations.append({
                "observation_id": legacy["observation_id"], "observed_at": legacy.get("observed_at"),
                "five_hour_percent_left": legacy.get("five_hour_percent_left"),
                "weekly_percent_left": legacy.get("weekly_percent_left"), "source": "manual",
                "provider": self.quota_policy.get("provider"), "account_id": self.quota_policy.get("account_id"),
                "models": {role: config.get("model") for role, config in self.models.items()},
                "authorizations": [{"status": "invalidated", "invalidated_at": legacy.get("observed_at"), "reason": "legacy_conversion_requires_fresh_observation"}],
            })
        return {"version": 3, "current_observation_id": source.get("current_observation_id"), "observations": observations,
                "predecessor": {"version": 2, "checksum": content_checksum(source)}}

    def apply_migration(self) -> dict[str, Any]:
        report = self.migration_dry_run()
        if not report["writes_required"]:
            return report
        source = read_json(self.path)
        if content_checksum(source) != report["source_checksum"]:
            raise SupervisorError("quota ledger changed after migration dry-run")
        archive = self.path.parent / report["archive"]
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            atomic_write_json(archive, source)
        target = self._convert_v2(source)
        if content_checksum(target) != report["target_checksum"]:
            raise SupervisorError("quota migration transformation was not deterministic")
        atomic_write_json(self.path, target)
        return report

    def rollback_migration(self) -> dict[str, Any]:
        current = read_json(self.path)
        predecessor = current.get("predecessor")
        if current.get("version") != 3 or not isinstance(predecessor, dict) or set(predecessor) != {"version", "checksum"}:
            raise SupervisorError("quota rollback requires a converted v3 ledger")
        archive = self.path.parent / "quota-predecessors" / f"{predecessor['checksum']}.json"
        source = read_json(archive)
        if source.get("version") != 2 or content_checksum(source) != predecessor["checksum"]:
            raise SupervisorError("quota predecessor archive is missing or inconsistent")
        atomic_write_json(self.path, source)
        return {"status": "rolled_back", "from_version": 3, "to_version": 2, "writes_required": True}

    def _validated_v3(self, value: dict[str, Any], role: str, policy: dict[str, Any]) -> tuple[datetime, str, int] | str:
        required = {"observation_id", "observed_at", "five_hour_percent_left", "weekly_percent_left", "source", "provider", "account_id", "models", "authorizations"}
        if set(value) != required or value["source"] != "manual" or value["provider"] != policy["provider"] or value["account_id"] != policy["account_id"]:
            return "quota observation provider or account context is contradictory"
        if not isinstance(value["models"], dict) or value["models"].get(role) != self.models.get(role, {}).get("model"):
            return "quota observation model context changed or is unknown"
        try:
            observed = parse_datetime(value["observed_at"])
            percentages = {"five_hour": value["five_hour_percent_left"], "weekly": value["weekly_percent_left"]}
            levels: list[str] = []
            for window, raw in percentages.items():
                if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or not 0 <= raw <= 100:
                    return "quota observation is malformed"
                ranges = policy["roles"][role][window]
                level = next((name for name in ("low", "medium", "high") if ranges[name]["minimum_percent"] <= raw <= ranges[name]["maximum_percent"]), None)
                if level is None:
                    return "quota observation range is contradictory"
                levels.append(level)
            if not isinstance(value["authorizations"], list):
                return "quota observation authorization audit is malformed"
        except (SupervisorError, TypeError, KeyError):
            return "quota observation is malformed"
        if any(item.get("status") == "invalidated" for item in value["authorizations"] if isinstance(item, dict)):
            return "quota observation was invalidated by a provider rate/usage signal"
        level = "low" if "low" in levels else "medium" if "medium" in levels else "high"
        return observed, level, sum(1 for item in value["authorizations"] if isinstance(item, dict) and item.get("status") == "consumed")

    def evaluate(self, role: str, policy: dict[str, Any]) -> tuple[str, str]:
        try:
            value = self.snapshot()
        except SupervisorError as error:
            return "unknown", f"{error}.\n" + quota_refresh_instructions(None)
        refresh = quota_refresh_instructions(value)
        if value is None:
            return "unknown", "No trusted quota snapshot exists.\n" + refresh
        validated = self._validated_v3(value, role, policy)
        if isinstance(validated, str):
            return "unknown", validated + ".\n" + refresh
        observed, level, uses = validated
        if level == "low":
            return "low", "quota observation is in the configured low range"
        if level == "medium":
            if uses:
                return "unknown", "medium-range observations require a fresh trusted observation per call.\n" + refresh
            return "ok", f"medium observed quota authorizes one {role} call (observation {value['observation_id']})"
        ttl = timedelta(minutes=policy["high_reuse_ttl_minutes"])
        if self.now() > observed + ttl:
            return "unknown", "high-range observation TTL expired.\n" + refresh
        if uses >= policy["high_reuse_invocation_count"]:
            return "unknown", "high-range observation reuse count is exhausted.\n" + refresh
        return "ok", f"high observed quota authorizes reuse {uses + 1}/{policy['high_reuse_invocation_count']} (observation {value['observation_id']})"

    def consume(
        self, observation_id: str, *, role: str, ticket: str,
        invocation_id: str, recovery: bool, policy: dict[str, Any],
    ) -> dict[str, Any]:
        ledger = read_json(self.path)
        current = self.snapshot()
        if current is None or current.get("observation_id") != observation_id:
            raise SupervisorError("quota observation changed after authorization; a fresh quota check is required")
        for item in current.get("authorizations", []):
            if isinstance(item, dict) and item.get("invocation_id") == invocation_id:
                if (
                    item.get("status") != "consumed"
                    or item.get("role") != role
                    or item.get("ticket") != ticket
                    or item.get("recovery") is not recovery
                ):
                    raise SupervisorError("quota invocation identity is contradictory; refusing double consumption")
                return {"observation_id": observation_id, **item}
        result, message = self.evaluate(role, policy)
        if result != "ok":
            raise SupervisorError("quota authorization became unusable before model start: " + message)
        authorization = {
            "status": "consumed",
            "consumed_at": isoformat(self.now()),
            "invocation_id": invocation_id,
            "role": role,
            "ticket": ticket,
            "recovery": recovery,
        }
        observations = list(ledger["observations"])
        matches = [
            index for index, item in enumerate(observations)
            if isinstance(item, dict) and item.get("observation_id") == observation_id
        ]
        if len(matches) != 1 or ledger.get("current_observation_id") != observation_id:
            raise SupervisorError("quota observation identity is inconsistent; refusing model start")
        consumed = dict(observations[matches[0]])
        consumed["authorizations"] = [*consumed["authorizations"], authorization]
        observations[matches[0]] = consumed
        ledger["observations"] = observations
        atomic_write_json(self.path, ledger)
        return {
            "observation_id": observation_id,
            **authorization,
        }

    def invalidate(self, observation_id: str, reason: str) -> None:
        """Durably make an observation unusable after a provider usage/rate signal."""
        ledger = read_json(self.path)
        observations = list(ledger.get("observations", []))
        matches = [index for index, item in enumerate(observations) if isinstance(item, dict) and item.get("observation_id") == observation_id]
        if len(matches) != 1:
            raise SupervisorError("quota observation identity is inconsistent while invalidating")
        observation = dict(observations[matches[0]])
        if ledger.get("version") != 3 or "authorizations" not in observation:
            return  # Legacy ledgers are intentionally readable but never mutated.
        observation["authorizations"] = [
            *observation["authorizations"],
            {"status": "invalidated", "invalidated_at": isoformat(self.now()), "reason": reason},
        ]
        observations[matches[0]] = observation
        ledger["observations"] = observations
        atomic_write_json(self.path, ledger)


def quota_refresh_instructions(_existing: dict[str, Any] | None) -> str:
    return (
        "Refresh from a trusted interactive Codex /status observation, then run:\n"
        "./dev quota set --five-hour <percent>"
    )


def default_project_policy(expected_branch: str) -> dict[str, Any]:
    """Return the smallest currently supported policy for a newly controlled repository."""
    return {
        "version": POLICY_VERSION,
        "expected_branch": expected_branch,
        "bootstrap_ticket": "T01",
        "initial_completed_tickets": [],
        "implementation_plan": "docs/architecture/implementation-plan.md",
        "authoritative_documents": ["docs/architecture/implementation-plan.md"],
        "supervisor_control_paths": ["dev", PROJECT_POLICY_NAME],
        "supervisor_repair_repository": "external",
        "models": {
            "implementation": {"model": "gpt-5.6-terra", "reasoning_effort": "medium"},
            "architecture": {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
            "diagnostic": {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
            "supervisor_repair": {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
        },
        "quota": _observed_quota_policy({
            "implementation": {"five_hour_percent_left": 20, "weekly_percent_left": 15},
            "architecture": {"five_hour_percent_left": 30, "weekly_percent_left": 20},
            "diagnostic": {"five_hour_percent_left": 30, "weekly_percent_left": 20},
            "supervisor_repair": {"five_hour_percent_left": 30, "weekly_percent_left": 20},
        }),
        "diagnostic": {
            "completed_same_ticket_recoveries": 2, "max_recent_runs": 4,
            "max_history_entries": 80, "max_artifact_bytes": 16000,
            "max_check_logs_per_run": 2, "max_ticket_context_bytes": 24000,
            "max_adr_documents": 3,
        },
        "periodic_checkpoint": {
            "max_completed_tickets": 3, "max_active_runtime_seconds": 10800,
            "max_model_invocations": 4,
        },
        "model_watchdog": {
            "warning_seconds": 2700, "hard_timeout_seconds": 5400,
            "terminate_grace_seconds": 10,
        },
        "capabilities": dict.fromkeys(CAPABILITY_NAMES, False),
        "improvement": _default_improvement_policy(),
        "milestones": [],
        "verification_commands": [{"name": "Git diff check", "command": ["git", "diff", "--check"]}],
        "supervisor_repair_verification_commands": [],
        "host_verification_capabilities": {},
        "ticket_verification_commands": {},
        "evidence_check_commands": {},
        "human_evidence_gates": {},
        "implementation_forbidden_paths": [
            "docs/architecture/", PROJECT_POLICY_NAME, "dev",
        ],
        "architecture_allowed_paths": ["docs/architecture/"],
    }


def project_launcher_text() -> str:
    return '''#!/usr/bin/env python3
"""Lightweight launcher for an externally managed development supervisor."""

import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
binding_path = ROOT / ".dev-supervisor" / "engine.json"
if "DEV_SUPERVISOR_HOST_ID" not in os.environ:
    for machine_id_path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            machine_id = machine_id_path.read_bytes().strip()
        except OSError:
            continue
        if machine_id:
            material = machine_id + b"\\0" + str(os.getuid()).encode("ascii")
            os.environ["DEV_SUPERVISOR_HOST_ID"] = (
                "machine-v1-" + hashlib.sha256(material).hexdigest()
            )
            break
engine_override = os.environ.get("DEV_SUPERVISOR_HOME")
if engine_override:
    engine_root = Path(engine_override).expanduser().resolve()
else:
    try:
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        engine_root = Path(binding["engine_root"])
        # v1 path-only bindings deliberately remain readable for the T00
        # compatibility/status path.  A v2 binding is an immutable receipt,
        # not an instruction to trust whatever now happens to be at a path.
        if binding.get("version") == 2:
            identity = binding["identity"]
            digest = hashlib.sha256()
            for child in sorted(item for item in engine_root.rglob("*") if item.is_file()
                                and ".git" not in item.relative_to(engine_root).parts
                                and "__pycache__" not in item.relative_to(engine_root).parts
                                and item.suffix != ".pyc"):
                digest.update(child.relative_to(engine_root).as_posix().encode() + b"\\0")
                digest.update(child.read_bytes())
            if digest.hexdigest() != identity["build_id"]:
                raise ValueError("engine build digest does not match binding")
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=engine_root, text=True,
                capture_output=True, check=True,
            ).stdout.strip()
            if revision != identity["revision"]:
                raise ValueError("engine revision does not match binding")
    except (FileNotFoundError, KeyError, json.JSONDecodeError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        print(
            "dev supervisor: engine binding is missing; run the standalone supervisor init command "
            "or set DEV_SUPERVISOR_HOME",
            file=sys.stderr,
        )
        raise SystemExit(2) from error
os.environ["DEV_SUPERVISOR_PROJECT_ROOT"] = str(ROOT)
runpy.run_path(str(engine_root / "supervisor.py"), run_name="__main__")
'''


def initialize_repository(
    target: Path, policy_path: Path | None = None, specification_path: Path | None = None,
) -> dict[str, Any]:
    """Install launch/config/runtime scaffolding without copying or packaging the engine."""
    root = target.expanduser().resolve()
    git = GitRepo(root)
    git.require_repository()
    launcher = root / "dev"
    project_policy = root / PROJECT_POLICY_NAME
    if launcher.exists() or project_policy.exists():
        raise SupervisorError("refusing to overwrite existing dev or dev-supervisor.json")
    branch = git.branch() or "master"
    cold_start = specification_path is not None
    if policy_path is not None:
        policy, _migration = validate_project_policy(read_json(policy_path.expanduser().resolve()))
    else:
        policy = default_project_policy(branch)
        plan = root / "docs/architecture/implementation-plan.md"
        ticket = root / "docs/architecture/tickets/01-initial-task.md"
        if plan.exists() or ticket.exists():
            raise SupervisorError(
                "default initialization would collide with existing architecture files; supply --policy"
            )
        if not cold_start:
            atomic_write_text(
                plan,
                "# Implementation plan\n\n| Milestone | Tickets | Gate |\n|---|---|---|\n| 1 foundation | 01 | none |\n",
            )
            atomic_write_text(
                ticket,
                "# T01: Initial task\n\nDefine the first bounded project-owned implementation task.\n",
            )
    policy["expected_branch"] = branch
    policy.setdefault("supervisor_control_paths", ["dev", PROJECT_POLICY_NAME])
    policy["supervisor_repair_repository"] = "external"
    policy, _migration = validate_project_policy(policy)
    atomic_write_json(project_policy, policy)
    atomic_write_text(launcher, project_launcher_text())
    launcher.chmod(0o755)
    ignore_path = root / ".gitignore"
    ignore = ignore_path.read_text(encoding="utf-8") if ignore_path.exists() else ""
    lines = ignore.splitlines()
    if ".dev-supervisor/" not in lines:
        atomic_write_text(ignore_path, ignore + ("" if not ignore or ignore.endswith("\n") else "\n") + ".dev-supervisor/\n")
    runtime = root / ".dev-supervisor"
    runtime.mkdir(parents=True, exist_ok=True)
    # Keep initialization compatible with the T00 launcher contract.  A v2
    # receipt is created only by the explicit staged-update cutover below.
    atomic_write_json(runtime / ENGINE_BINDING_NAME, {"engine_root": str(TOOL_DIR)})
    supervisor = Supervisor(root, policy=policy)
    if cold_start:
        supervisor.begin_cold_start(specification_path)
    elif not supervisor.state_path.exists():
        supervisor.save_state(supervisor.initial_state())
    result = {
        "repository": str(root),
        "engine_root": str(TOOL_DIR),
        "launcher": "dev",
        "policy": PROJECT_POLICY_NAME,
        "runtime": ".dev-supervisor/",
    }
    if cold_start:
        result["cold_start"] = COLD_START_STATE_NAME
    return result


class GitRepo:
    def __init__(self, root: Path):
        self.root = root

    def run(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        process = subprocess.run(
            ["git", *arguments], cwd=self.root, text=True, capture_output=True,
        )
        if check and process.returncode:
            detail = process.stderr.strip() or process.stdout.strip()
            raise SupervisorError(f"git {' '.join(arguments)} failed: {detail}")
        return process

    def require_repository(self) -> None:
        if self.run("rev-parse", "--is-inside-work-tree", check=False).stdout.strip() != "true":
            raise SupervisorError(f"not a Git repository: {self.root}")

    def head(self) -> str:
        return self.run("rev-parse", "HEAD").stdout.strip()

    def branch(self) -> str:
        return self.run("branch", "--show-current").stdout.strip()

    def status_entries(self) -> list[tuple[str, str]]:
        raw = self.run("status", "--porcelain=v1", "--untracked-files=all", "-z").stdout
        entries: list[tuple[str, str]] = []
        pieces = raw.split("\0")
        index = 0
        while index < len(pieces) and pieces[index]:
            item = pieces[index]
            status, path = item[:2], item[3:]
            if status[0] in "RC" or status[1] in "RC":
                index += 1
            entries.append((status, path))
            index += 1
        return entries

    def changed_files(self) -> list[str]:
        return sorted({path for _, path in self.status_entries()})

    def is_clean(self) -> bool:
        return not self.status_entries()

    def diff_summary(self) -> str:
        tracked = self.run("diff", "--stat", "HEAD", check=False).stdout
        untracked = [path for status, path in self.status_entries() if status == "??"]
        if untracked:
            tracked += "Untracked:\n" + "\n".join(f"  {item}" for item in untracked) + "\n"
        return tracked or "(no changes)\n"

    def diff_check(self) -> tuple[bool, str]:
        result = self.run("diff", "--check", check=False)
        return result.returncode == 0, result.stdout + result.stderr

    def cached_diff_check(self) -> tuple[bool, str]:
        result = self.run("diff", "--cached", "--check", check=False)
        return result.returncode == 0, result.stdout + result.stderr

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for _, relative in self.status_entries():
            digest.update(relative.encode())
            digest.update(b"\0")
            path = self.root / relative
            if path.is_file() and not path.is_symlink():
                digest.update(path.read_bytes())
            elif path.is_symlink():
                digest.update(os.readlink(path).encode())
        return digest.hexdigest()

    def stage_all(self) -> None:
        self.run("add", "--all")

    def commit_staged(self, message: str) -> str:
        self.run("commit", "-m", message)
        return self.head()

    def commit_subject(self, revision: str = "HEAD") -> str:
        return self.run("show", "-s", "--format=%s", revision).stdout.strip()

    def parent(self, revision: str = "HEAD") -> str:
        return self.run("rev-parse", f"{revision}^").stdout.strip()

    def is_ancestor(self, ancestor: str, descendant: str = "HEAD") -> bool:
        return self.run("merge-base", "--is-ancestor", ancestor, descendant, check=False).returncode == 0

    def changed_files_between(self, older: str, newer: str = "HEAD") -> list[str]:
        raw = self.run("diff", "--name-only", "-z", older, newer).stdout
        return sorted(path for path in raw.split("\0") if path)

    def stage_paths(self, paths: list[str]) -> None:
        if not paths:
            raise SupervisorError("refusing to stage an empty path set")
        self.run("add", "--", *paths)

    def cached_files(self) -> list[str]:
        raw = self.run("diff", "--cached", "--name-only", "-z").stdout
        return sorted(path for path in raw.split("\0") if path)

    def remote_urls(self, remote: str) -> tuple[list[str], list[str]]:
        """Read configured fetch and push URLs without contacting a remote."""
        fetch = self.run("config", "--get-all", f"remote.{remote}.url", check=False)
        push = self.run("config", "--get-all", f"remote.{remote}.pushurl", check=False)
        fetch_urls = [item for item in fetch.stdout.splitlines() if item]
        push_urls = [item for item in push.stdout.splitlines() if item]
        return fetch_urls, push_urls or fetch_urls

    def push_exact(self, remote: str, commit: str, branch: str) -> bool:
        return self.run("push", remote, f"{commit}:refs/heads/{branch}", check=False).returncode == 0

    def remote_branch_commit(self, remote: str, branch: str) -> str | None:
        result = self.run("ls-remote", "--refs", remote, f"refs/heads/{branch}", check=False)
        if result.returncode:
            return None
        fields = result.stdout.strip().split()
        return fields[0] if len(fields) == 2 and re.fullmatch(r"[0-9a-f]{40,64}", fields[0]) else None


def _admission_relative_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    if not value or candidate.is_absolute() or ".." in candidate.parts:
        raise SupervisorError("admission document paths must be nonempty safe repository-relative paths")
    resolved = (root / candidate).resolve()
    if root not in resolved.parents and resolved != root:
        raise SupervisorError("admission document path escapes the repository")
    return resolved


def _admission_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shallow_inventory(root: Path) -> dict[str, Any]:
    """Collect bounded observable facts without writing the assessed repository."""
    root = root.expanduser().resolve()
    git = GitRepo(root)
    git.require_repository()
    ignored = {".git", ".dev-supervisor", "node_modules", "__pycache__", ".venv", "venv"}
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and not any(part in ignored for part in path.relative_to(root).parts)
    )
    extension_languages = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
        ".jsx": "JavaScript", ".go": "Go", ".rs": "Rust", ".java": "Java",
        ".kt": "Kotlin", ".rb": "Ruby", ".php": "PHP", ".cs": "C#",
        ".c": "C", ".h": "C/C++", ".cc": "C++", ".cpp": "C++", ".swift": "Swift",
        ".sh": "Shell", ".sql": "SQL",
    }
    language_paths: dict[str, list[str]] = {}
    for path in files:
        language = extension_languages.get(path.suffix.lower())
        if language:
            language_paths.setdefault(language, []).append(path.relative_to(root).as_posix())
    names = {path.name.lower(): path.relative_to(root).as_posix() for path in files}
    dependency_names = {
        "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "pyproject.toml",
        "requirements.txt", "poetry.lock", "pipfile", "go.mod", "cargo.toml", "pom.xml", "build.gradle",
    }
    build_names = {"makefile", "justfile", "dockerfile", "compose.yml", "docker-compose.yml", "build.gradle", "pom.xml"}
    test_names = {"pytest.ini", "tox.ini", "jest.config.js", "vitest.config.ts", "conftest.py"}
    deploy_names = {"dockerfile", "compose.yml", "docker-compose.yml", "helmfile.yaml", "chart.yaml"}
    document_suffixes = {".md", ".rst", ".txt", ".adoc"}
    documents = [
        {"path": path.relative_to(root).as_posix(), "digest": _admission_digest(path)}
        for path in files if path.suffix.lower() in document_suffixes
    ]
    entry_points = [
        path.relative_to(root).as_posix() for path in files
        if path.name in {"main.py", "app.py", "manage.py", "server.py", "index.js", "index.ts", "main.go", "main.rs"}
        or os.access(path, os.X_OK)
    ]
    integration_markers = ("terraform", "kubernetes", ".github", "docker", "compose", "openapi", "swagger")
    integrations = sorted({
        path.relative_to(root).as_posix().split("/")[0]
        for path in files if any(marker in path.relative_to(root).as_posix().lower() for marker in integration_markers)
    })
    evidence = [
        {"input": item["path"], "digest": item["digest"]} for item in documents
    ]
    evidence.extend({"input": path, "digest": _admission_digest(root / path)} for path in sorted(set(entry_points)))
    return {
        "version": 1,
        "kind": "shallow_inventory",
        "repository": str(root),
        "git": {"head": git.head(), "branch": git.branch(), "status": git.status_entries()},
        "languages": {name: paths for name, paths in sorted(language_paths.items())},
        "entry_points": sorted(set(entry_points)),
        "dependencies": sorted(path for name, path in names.items() if name in dependency_names),
        "surfaces": {
            "build": sorted(path for name, path in names.items() if name in build_names),
            "test": sorted(path for name, path in names.items() if name in test_names or "test" in name),
            "deploy": sorted(path for name, path in names.items() if name in deploy_names),
        },
        "components": sorted({path.relative_to(root).parts[0] for path in files if len(path.relative_to(root).parts) > 1}),
        "integrations": integrations,
        "documents": documents,
        "risks": ["Inventory is shallow and does not establish product architecture or intent."],
        "unknowns": [
            "Runtime behavior, ownership, authority, and undocumented integrations are not inferred from inventory.",
            "Dependency semantics and component boundaries require project-owned evidence.",
        ],
        "evidence": sorted(evidence, key=lambda item: item["input"]),
        "inferences": ["Languages and surfaces are inferred solely from file names and extensions."],
    }


def _validate_admission_manifest(root: Path, value: Any) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(value, dict) or set(value) != ADMISSION_MANIFEST_FIELDS or value.get("version") != 1:
        raise SupervisorError("admission manifest has an unsupported version or keys")
    documents = value.get("source_documents")
    identifiers = value.get("external_identifiers")
    mapping = value.get("mapping")
    if not isinstance(documents, list) or not documents:
        raise SupervisorError("admission manifest requires a finite nonempty source_documents list")
    if not isinstance(identifiers, list) or any(not isinstance(item, str) or not item.strip() for item in identifiers):
        raise SupervisorError("admission manifest external_identifiers must be an array of nonempty strings")
    if not isinstance(mapping, dict) or set(mapping) != ADMISSION_MAPPING_FIELDS or mapping.get("status") not in ADMISSION_STATUSES:
        raise SupervisorError("admission manifest mapping has unsupported keys or status")
    for field in ADMISSION_MAPPING_FIELDS - {"status"}:
        if not isinstance(mapping[field], list) or any(not isinstance(item, str) or not item.strip() for item in mapping[field]):
            raise SupervisorError(f"admission manifest mapping {field!r} must be an array of nonempty strings")
    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    gaps: list[str] = list(mapping["gaps"]) + list(mapping["contradictions"]) + list(mapping["unknowns"])
    for document in documents:
        if not isinstance(document, dict) or set(document) != ADMISSION_DOCUMENT_FIELDS:
            raise SupervisorError("each admission source document must contain only path, external_id, and digest")
        path, external_id, digest = document.get("path"), document.get("external_id"), document.get("digest")
        if not isinstance(path, str) or not isinstance(external_id, str) or not external_id.strip() or not isinstance(digest, str):
            raise SupervisorError("admission source document provenance is malformed")
        if path in seen_paths or external_id in seen_ids:
            raise SupervisorError("admission source document paths and external identifiers must be unique")
        seen_paths.add(path)
        seen_ids.add(external_id)
        candidate = _admission_relative_path(root, path)
        if not candidate.is_file():
            gaps.append(f"missing source document: {path}")
        elif not re.fullmatch(r"[0-9a-f]{64}", digest) or _admission_digest(candidate) != digest:
            gaps.append(f"source document changed: {path}")
    missing_ids = sorted(seen_ids - set(identifiers))
    if missing_ids:
        gaps.extend(f"unlisted external identifier: {item}" for item in missing_ids)
    return deepcopy(value), sorted(set(gaps))


def assess_existing_project(root: Path, scenario: str, manifest_path: Path | None = None) -> dict[str, Any]:
    """Return a deterministic read-only admission finding for scenarios A and B."""
    if scenario not in ADMISSION_SCENARIOS:
        raise SupervisorError("admission scenario must be A or B")
    root = root.expanduser().resolve()
    inventory = shallow_inventory(root)
    controlled = (root / PROJECT_POLICY_NAME).exists() or (root / "dev").exists()
    if controlled:
        return {
            "version": 1, "scenario": scenario, "status": "incompatible", "inventory": inventory,
            "evidence": inventory["evidence"], "inferences": [],
            "gaps": ["repository already has Supervisor control material; admission is not entered"],
            "recommendation": "Use the existing controlled-project status/reconciliation path.",
        }
    if scenario == "A":
        checklist = [
            "Project owner supplies reviewed requirements and architecture documents with stable identifiers.",
            "Project owner records authority, unresolved contradictions, and a bounded implementation plan.",
            "A human approves the exact corrected document digests before any Supervisor-compatible index is materialized.",
        ]
        return {
            "version": 1, "scenario": "A", "status": "incompatible", "inventory": inventory,
            "evidence": inventory["evidence"], "inferences": inventory["inferences"], "gaps": checklist,
            "recommendation": "Perform an independent external architecture stage; Supervisor will not reconstruct AS-IS architecture.",
        }
    if manifest_path is None:
        gaps = ["missing authority: a project-owned foreign-document mapping manifest is required"]
        return {
            "version": 1, "scenario": "B", "status": "incompatible", "inventory": inventory,
            "evidence": inventory["evidence"], "inferences": inventory["inferences"], "gaps": gaps,
            "recommendation": "Provide corrected project-owned documents and an explicit generic provenance/mapping manifest.",
        }
    manifest = read_json(manifest_path.expanduser().resolve())
    manifest, gaps = _validate_admission_manifest(root, manifest)
    status = manifest["mapping"]["status"]
    if gaps:
        status = "incompatible"
    return {
        "version": 1, "scenario": "B", "status": status, "inventory": inventory,
        "manifest": manifest, "manifest_digest": content_checksum(manifest),
        "evidence": inventory["evidence"] + [
            {"input": document["path"], "digest": document["digest"]}
            for document in manifest["source_documents"]
        ],
        "inferences": inventory["inferences"], "gaps": gaps,
        "recommendation": (
            "Exact approval may permit compatible-index materialization."
            if status == "compatible" else "Resolve the finite project-owned mapping gaps before approval."
        ),
    }


class AdmissionReview:
    """Persist only approval/provenance records; inventory itself remains read-only."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.state_path = self.root / ".dev-supervisor" / ADMISSION_STATE_NAME

    def _load(self) -> dict[str, Any]:
        state = read_json(self.state_path)
        required = {"version", "scenario", "assessment", "assessment_digest", "manifest", "manifest_digest", "approval", "index"}
        if set(state) != required or state.get("version") != 1 or state.get("scenario") not in ADMISSION_SCENARIOS:
            raise SupervisorError("admission review state is malformed or has an unsupported version")
        if content_checksum(state["assessment"]) != state.get("assessment_digest"):
            raise SupervisorError("admission assessment provenance does not match its recorded digest")
        if content_checksum(state["manifest"]) != state.get("manifest_digest"):
            raise SupervisorError("admission manifest provenance does not match its recorded digest")
        _manifest, gaps = _validate_admission_manifest(self.root, state["manifest"])
        if state["approval"] is not None:
            if not isinstance(state["approval"], dict) or set(state["approval"]) != {"assessment_digest", "manifest_digest"}:
                raise SupervisorError("admission approval is malformed")
            if state["approval"] != {"assessment_digest": state["assessment_digest"], "manifest_digest": state["manifest_digest"]}:
                raise SupervisorError("admission approval does not name the exact reviewed inputs")
            if gaps:
                raise SupervisorError("approved admission inputs changed or have unresolved finite gaps")
        if state["index"] is not None and state["approval"] is None:
            raise SupervisorError("admission index exists without exact approval")
        return state

    def begin(self, scenario: str, manifest_path: Path) -> dict[str, Any]:
        if self.state_path.exists():
            raise SupervisorError("an admission review already exists; resume or discard it outside Supervisor")
        # Scenario A's initial assessment deliberately has no foreign documents to
        # interpret.  Once its external stage is complete, it uses the same generic
        # provenance revalidation as B; this remains an index, not an architecture
        # reconstruction.
        finding = assess_existing_project(self.root, "B" if scenario == "A" else scenario, manifest_path)
        finding["scenario"] = scenario
        if finding["status"] != "compatible":
            raise SupervisorError("admission cannot begin until the mapping is compatible with no finite gaps")
        manifest = finding["manifest"]
        state = {
            "version": 1, "scenario": scenario, "assessment": finding,
            "assessment_digest": content_checksum(finding), "manifest": manifest,
            "manifest_digest": content_checksum(manifest), "approval": None, "index": None,
        }
        atomic_write_json(self.state_path, state)
        return state

    def approve(self, assessment_digest: str, manifest_digest: str) -> dict[str, Any]:
        state = self._load()
        if assessment_digest != state["assessment_digest"] or manifest_digest != state["manifest_digest"]:
            raise SupervisorError("admission approval must name the exact assessment and manifest digests")
        _manifest, gaps = _validate_admission_manifest(self.root, state["manifest"])
        if gaps:
            raise SupervisorError("admission approval fails closed until all finite source-document gaps are corrected")
        state["approval"] = {"assessment_digest": assessment_digest, "manifest_digest": manifest_digest}
        atomic_write_json(self.state_path, state)
        return state

    def materialize_index(self, destination: str) -> dict[str, Any]:
        state = self._load()
        if state["approval"] is None:
            raise SupervisorError("a Supervisor-compatible index requires exact approval")
        if state["index"] is not None:
            raise SupervisorError("a Supervisor-compatible index has already been materialized")
        target = _admission_relative_path(self.root, destination)
        if target.exists():
            raise SupervisorError("refusing to overwrite an existing Supervisor-compatible index")
        manifest, gaps = _validate_admission_manifest(self.root, state["manifest"])
        if gaps or manifest["mapping"]["status"] != "compatible":
            raise SupervisorError("index materialization fails closed until the exact compatible inputs revalidate")
        index = {
            "version": 1, "kind": "supervisor_compatible_admission_index",
            "scenario": state["scenario"], "assessment_digest": state["assessment_digest"],
            "manifest_digest": state["manifest_digest"],
            "source_documents": manifest["source_documents"],
            "external_identifiers": manifest["external_identifiers"], "mapping": manifest["mapping"],
        }
        atomic_write_json(target, index)
        state["index"] = {"path": destination, "digest": _admission_digest(target)}
        atomic_write_json(self.state_path, state)
        return state

    def status(self) -> dict[str, Any]:
        state = self._load()
        return {**state, "required_human_action": (
            "approve the exact assessment and manifest digests" if state["approval"] is None
            else "materialize one Supervisor-compatible index" if state["index"] is None
            else "review the materialized index before separately initializing any controlled workflow"
        )}


def validate_report(report: Any, role: str, ticket: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["final report is not a JSON object"]
    missing = REPORT_FIELDS - set(report)
    extra = set(report) - REPORT_FIELDS
    if missing:
        errors.append("missing fields: " + ", ".join(sorted(missing)))
    if extra:
        errors.append("unexpected fields: " + ", ".join(sorted(extra)))
    if errors:
        return errors
    if report["role"] != role:
        errors.append(f"role must be {role!r}")
    if report["ticket"] != ticket:
        errors.append(f"ticket must be {ticket!r}")
    if report["status"] not in {"pass", "blocked", "environment_blocked", "fail"}:
        errors.append("status must be pass, blocked, environment_blocked, or fail")
    for field in (
        "acceptance_passed", "tests_passed", "architecture_deviation", "ambiguity",
        "product_decision_required", "next_ticket_safe",
    ):
        if type(report[field]) is not bool:
            errors.append(f"{field} must be boolean")
    if not isinstance(report["summary"], str) or not report["summary"].strip():
        errors.append("summary must be a nonempty string")
    for field in ("files_changed", "blockers", "checks_run"):
        value = report[field]
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            errors.append(f"{field} must be an array of nonempty strings")
    files = report["files_changed"]
    if (
        isinstance(files, list)
        and all(isinstance(item, str) for item in files)
        and len(files) != len(set(files))
    ):
        errors.append("files_changed must be unique")
    return errors


def validate_diagnostic_report(
    report: Any, ticket: str, supplied_run_ids: list[str],
) -> list[str]:
    """Validate the only model-controlled input to diagnostic transitions."""
    if not isinstance(report, dict):
        return ["diagnostic report is not a JSON object"]
    required = {"role", "ticket", "classification", "rationale_summary", "evidence_run_ids"}
    errors: list[str] = []
    if set(report) != required:
        missing = required - set(report)
        extra = set(report) - required
        if missing:
            errors.append("missing fields: " + ", ".join(sorted(missing)))
        if extra:
            errors.append("unexpected fields: " + ", ".join(sorted(extra)))
        return errors
    if report.get("role") != "diagnostic":
        errors.append("role must be 'diagnostic'")
    if report.get("ticket") != ticket:
        errors.append(f"ticket must be {ticket!r}")
    if report.get("classification") not in DIAGNOSTIC_CLASSIFICATIONS:
        errors.append("classification is not a recognized closed-set value")
    rationale = report.get("rationale_summary")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 2000:
        errors.append("rationale_summary must contain 1-2000 characters")
    run_ids = report.get("evidence_run_ids")
    if (
        not isinstance(run_ids, list)
        or any(not isinstance(item, str) or not item for item in run_ids)
        or len(run_ids) != len(set(run_ids))
    ):
        errors.append("evidence_run_ids must be an array of unique nonempty strings")
    elif run_ids != supplied_run_ids:
        errors.append("evidence_run_ids must exactly match the ordered run IDs supplied")
    return errors


def validate_supervisor_repair_report(report: Any, ticket: str) -> list[str]:
    if not isinstance(report, dict):
        return ["supervisor repair report is not a JSON object"]
    required = {"role", "ticket", "status", "summary", "files_changed", "checks_run"}
    errors: list[str] = []
    if set(report) != required:
        missing = required - set(report)
        extra = set(report) - required
        if missing:
            errors.append("missing fields: " + ", ".join(sorted(missing)))
        if extra:
            errors.append("unexpected fields: " + ", ".join(sorted(extra)))
        return errors
    if report.get("role") != "supervisor_repair":
        errors.append("role must be 'supervisor_repair'")
    if report.get("ticket") != ticket:
        errors.append(f"ticket must be {ticket!r}")
    if report.get("status") not in {"repaired", "blocked"}:
        errors.append("status must be repaired or blocked")
    if not isinstance(report.get("summary"), str) or not report["summary"].strip():
        errors.append("summary must be a nonempty string")
    for field in ("files_changed", "checks_run"):
        value = report.get(field)
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) or not item for item in value)
            or len(value) != len(set(value))
        ):
            errors.append(f"{field} must be an array of unique nonempty strings")
    return errors


def validate_codex_output_schema(schema: Any) -> list[str]:
    """Validate the strict JSON Schema subset accepted by Codex Structured Outputs."""
    if not isinstance(schema, dict):
        return ["schema root must be an object"]
    errors: list[str] = []

    def location(parts: list[str]) -> str:
        return "$" + "".join(f".{part}" for part in parts)

    def visit(node: Any, parts: list[str]) -> None:
        if not isinstance(node, dict):
            errors.append(f"{location(parts)} must be a schema object")
            return
        for keyword in node:
            if keyword in CODEX_UNSUPPORTED_SCHEMA_KEYWORDS:
                errors.append(f"{location(parts)} uses unsupported keyword {keyword!r}")
            elif keyword not in CODEX_SUPPORTED_SCHEMA_KEYWORDS:
                errors.append(f"{location(parts)} uses unknown or unsupported keyword {keyword!r}")

        schema_type = node.get("type")
        allowed_types = {"string", "number", "boolean", "integer", "object", "array", "null"}
        if schema_type is not None:
            type_values = schema_type if isinstance(schema_type, list) else [schema_type]
            if (
                not type_values
                or any(not isinstance(item, str) or item not in allowed_types for item in type_values)
                or len(type_values) != len(set(type_values))
            ):
                errors.append(f"{location(parts)} has an invalid or unsupported type")

        properties = node.get("properties")
        if schema_type == "object" or properties is not None:
            if not isinstance(properties, dict):
                errors.append(f"{location(parts)} object must declare properties")
            else:
                if schema_type != "object":
                    errors.append(f"{location(parts)} with properties must have type 'object'")
                if node.get("additionalProperties") is not False:
                    errors.append(f"{location(parts)} object must set additionalProperties to false")
                required = node.get("required")
                if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
                    errors.append(f"{location(parts)} object must have a string-array required list")
                elif set(required) != set(properties):
                    errors.append(f"{location(parts)} must require every declared property exactly once")
                elif len(required) != len(set(required)):
                    errors.append(f"{location(parts)} required list must not contain duplicates")
                for name, child in properties.items():
                    visit(child, parts + ["properties", str(name)])

        if schema_type == "array" and "items" not in node:
            errors.append(f"{location(parts)} array must declare items")
        if "items" in node:
            visit(node["items"], parts + ["items"])
        for keyword in ("anyOf",):
            if keyword not in node:
                continue
            branches = node[keyword]
            if not isinstance(branches, list) or not branches:
                errors.append(f"{location(parts)}.{keyword} must be a nonempty array")
            else:
                for index, child in enumerate(branches):
                    visit(child, parts + [keyword, str(index)])
        definitions = node.get("$defs")
        if definitions is not None:
            if not isinstance(definitions, dict):
                errors.append(f"{location(parts)}.$defs must be an object")
            else:
                for name, child in definitions.items():
                    visit(child, parts + ["$defs", str(name)])

    if schema.get("type") != "object":
        errors.append("schema root must have type 'object'")
    if "anyOf" in schema:
        errors.append("schema root must not use anyOf")
    visit(schema, [])
    return errors


def require_codex_output_schema(path: Path) -> dict[str, Any]:
    schema = read_json(path)
    errors = validate_codex_output_schema(schema)
    if errors:
        raise SupervisorError("Codex output schema is incompatible: " + "; ".join(errors))
    return schema


def _jsonl_objects(path: Path) -> Iterable[dict[str, Any]]:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            yield value


def parse_usage_lines(lines: Iterable[str]) -> dict[str, Any]:
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
    totals = {key: 0 for key in keys}
    events: list[dict[str, int]] = []
    for line in lines:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(event, dict) or event.get("type") != "turn.completed":
            continue
        usage = event.get("usage")
        if not isinstance(usage, dict):
            continue
        parsed: dict[str, int] = {}
        for key in keys:
            value = usage.get(key, 0)
            parsed[key] = value if type(value) is int and value >= 0 else 0
            totals[key] += parsed[key]
        events.append(parsed)
    return {**totals, "turn_completed_events": events}


def rate_limit_in_output(event_path: Path, stderr: str) -> bool:
    fragments = [stderr.lower()]
    if event_path.exists():
        for line in event_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and (
                "error" in str(event.get("type", "")).lower() or event.get("type") == "turn.failed"
            ):
                fragments.append(json.dumps(event, ensure_ascii=False).lower())
    text = "\n".join(fragments)
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


@dataclass
class InvocationResult:
    exit_code: int
    report: dict[str, Any] | None
    usage: dict[str, Any]
    rate_limited: bool = False
    error: str = ""
    duration_seconds: float = 0.0
    warning_emitted: bool = False
    interrupted: bool = False
    interrupt_reason: str = ""


@dataclass
class ProcessOutcome:
    exit_code: int
    duration_seconds: float
    child_pid: int
    warning_emitted: bool = False
    interrupted: bool = False
    interrupt_reason: str = ""


@dataclass
class CommandResult:
    exit_code: int
    duration_seconds: float = 0.0
    interrupted: bool = False
    interrupt_reason: str = ""


def _terminate_process_group(process: subprocess.Popen[Any], grace_seconds: float) -> None:
    """Terminate the child session, escalating only after a bounded grace period."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=max(0.0, grace_seconds))
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_process_with_watchdog(
    command: list[str], *, cwd: Path, stdout: Any, stderr: Any,
    input_text: str | None = None, warning_seconds: float | None = None,
    hard_timeout_seconds: float | None = None, terminate_grace_seconds: float = 10,
    stop_path: Path | None = None, notify: Callable[[str], None] | None = None,
) -> ProcessOutcome:
    """Run a child in its own process group with warning, timeout, stop and Ctrl+C handling."""
    started = time.monotonic()
    process = subprocess.Popen(
        command, cwd=cwd, text=True, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=stdout, stderr=stderr, start_new_session=True,
    )
    if input_text is not None and process.stdin is not None:
        try:
            process.stdin.write(input_text)
            process.stdin.close()
        except BrokenPipeError:
            pass
    warned = False
    reason = ""
    try:
        while process.poll() is None:
            elapsed = time.monotonic() - started
            if warning_seconds is not None and not warned and elapsed >= warning_seconds:
                warned = True
                if notify:
                    notify(f"WARNING · model invocation exceeded {format_duration(elapsed)}; it is still running")
            if hard_timeout_seconds is not None and elapsed >= hard_timeout_seconds:
                reason = "watchdog_timeout"
                _terminate_process_group(process, terminate_grace_seconds)
                break
            if stop_path is not None and stop_path.exists():
                reason = "operator_stop"
                _terminate_process_group(process, terminate_grace_seconds)
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        reason = "keyboard_interrupt"
        _terminate_process_group(process, terminate_grace_seconds)
    duration = time.monotonic() - started
    if warning_seconds is not None and not warned and duration >= warning_seconds:
        warned = True
        if notify:
            notify(f"WARNING · model invocation exceeded {format_duration(duration)}; it has now completed")
    return ProcessOutcome(
        process.returncode if process.returncode is not None else 1,
        duration,
        process.pid,
        warning_emitted=warned,
        interrupted=bool(reason),
        interrupt_reason=reason,
    )


class ModelRunner(Protocol):
    def invoke(
        self, role: str, ticket: str, prompt: str, run_dir: Path,
        start_head: str, policy: dict[str, Any], schema_path: Path,
    ) -> InvocationResult:
        ...


class CodexRunner:
    """Runs one real Codex process and captures its structured artifacts."""

    def __init__(self, root: Path, notify: Callable[[str], None] | None = None):
        self.root = root
        self.notify = notify

    def invoke(
        self, role: str, ticket: str, prompt: str, run_dir: Path,
        start_head: str, policy: dict[str, Any], schema_path: Path,
    ) -> InvocationResult:
        model = policy["models"][role]
        event_path = run_dir / "events.jsonl"
        report_path = run_dir / "final-report.json"
        stderr_path = run_dir / "stderr.log"
        command = [
            "codex", "--ask-for-approval", "never", "exec",
            "--model", model["model"],
            "--config", f'model_reasoning_effort="{model["reasoning_effort"]}"',
            "--sandbox", "workspace-write",
            "--json",
            "--output-schema", str(schema_path),
            "--output-last-message", str(report_path),
            "--cd", str(self.root),
            "-",
        ]
        atomic_write_json(run_dir / "command.json", {
            "argv": command, "role": role, "ticket": ticket, "starting_head": start_head,
            "model": model["model"], "reasoning_effort": model["reasoning_effort"],
        })
        watchdog_notices: list[str] = []

        def watchdog_notice(message: str) -> None:
            watchdog_notices.append(f"{isoformat(utc_now())} {message}")
            atomic_write_text(run_dir / "watchdog-warning.log", "\n".join(watchdog_notices) + "\n")
            if self.notify:
                self.notify(message)

        watchdog = policy["model_watchdog"]
        with event_path.open("w", encoding="utf-8") as events, stderr_path.open("w", encoding="utf-8") as errors:
            outcome = run_process_with_watchdog(
                command,
                cwd=self.root,
                input_text=prompt,
                stdout=events,
                stderr=errors,
                warning_seconds=float(watchdog["warning_seconds"]),
                hard_timeout_seconds=float(watchdog["hard_timeout_seconds"]),
                terminate_grace_seconds=float(watchdog["terminate_grace_seconds"]),
                stop_path=self.root / ".dev-supervisor" / "stop-request.json",
                notify=watchdog_notice,
            )
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
        if outcome.warning_emitted or outcome.interrupted:
            atomic_write_json(run_dir / "watchdog.json", {
                "warning_emitted": outcome.warning_emitted,
                "interrupted": outcome.interrupted,
                "interrupt_reason": outcome.interrupt_reason,
                "duration_seconds": outcome.duration_seconds,
            })
        usage = parse_usage_lines(event_path.read_text(encoding="utf-8", errors="replace").splitlines())
        report: dict[str, Any] | None = None
        report_error = ""
        if report_path.exists():
            try:
                candidate = json.loads(report_path.read_text(encoding="utf-8"))
                if isinstance(candidate, dict):
                    report = candidate
                else:
                    report_error = "final report is not an object"
            except json.JSONDecodeError as error:
                report_error = f"final report is invalid JSON: {error}"
        else:
            report_error = "final report file was not created"
        network_interrupted = (
            not outcome.interrupted and outcome.exit_code != 0
            and any(marker in stderr.lower() for marker in NETWORK_FAILURE_MARKERS)
        )
        result = InvocationResult(
            exit_code=outcome.exit_code,
            report=report,
            usage=usage,
            rate_limited=rate_limit_in_output(event_path, stderr),
            error=report_error or stderr.strip(),
            duration_seconds=outcome.duration_seconds,
            warning_emitted=outcome.warning_emitted,
            interrupted=outcome.interrupted or network_interrupted,
            interrupt_reason=outcome.interrupt_reason or ("network_failure" if network_interrupted else ""),
        )
        atomic_write_json(run_dir / "process-outcome.json", {
            "completed": not result.interrupted,
            "interrupted": result.interrupted,
            "interrupt_reason": result.interrupt_reason,
            "exit_status": result.exit_code,
            "rate_limited": result.rate_limited,
            "error": result.error,
            "duration_seconds": result.duration_seconds,
            "warning_emitted": result.warning_emitted,
        })
        return result


class CommandRunner(Protocol):
    def run(self, command: list[str], cwd: Path, output_path: Path) -> int | CommandResult:
        ...


class SubprocessCommandRunner:
    def run(self, command: list[str], cwd: Path, output_path: Path) -> CommandResult:
        with output_path.open("w", encoding="utf-8") as output:
            outcome = run_process_with_watchdog(
                command,
                cwd=cwd,
                stdout=output,
                stderr=subprocess.STDOUT,
                stop_path=cwd / ".dev-supervisor" / "stop-request.json",
            )
        return CommandResult(
            outcome.exit_code, outcome.duration_seconds,
            interrupted=outcome.interrupted, interrupt_reason=outcome.interrupt_reason,
        )


class Supervisor:
    def __init__(
        self,
        root: Path,
        *,
        policy: dict[str, Any] | None = None,
        assets_dir: Path = TOOL_DIR,
        model_runner: ModelRunner | None = None,
        supervisor_repair_runner: ModelRunner | None = None,
        command_runner: CommandRunner | None = None,
        quota_provider: QuotaProvider | None = None,
        progress: Callable[[str], None] | None = None,
        now: Callable[[], datetime] = utc_now,
    ):
        self.root = root.resolve()
        self.assets_dir = assets_dir.resolve()
        supplied_policy = policy or read_json(self.root / PROJECT_POLICY_NAME)
        self.policy, self.legacy_policy_migration = validate_project_policy(supplied_policy)
        self.runtime = self.root / ".dev-supervisor"
        self.state_path = self.runtime / "state.json"
        self.runs_dir = self.runtime / "runs"
        self.timing_path = self.runtime / "timing-history.json"
        self.stop_path = self.runtime / "stop-request.json"
        self.host_capabilities_path = self.runtime / HOST_CAPABILITIES_NAME
        self.engine_binding_path = self.runtime / ENGINE_BINDING_NAME
        self.host_owner_path = self.runtime / HOST_OWNER_NAME
        self.engine_update_path = self.runtime / ENGINE_UPDATE_NAME
        self.legacy_cutover_path = self.runtime / LEGACY_CUTOVER_NAME
        self.host_capability_grants, self.host_capability_provenance, self.host_push_target = load_host_capability_grants(
            self.host_capabilities_path
        )
        self.effective_capabilities = {
            name: (
                self.policy["capabilities"][name]
                and self.host_capability_grants[name]
                and (name != "repository_push" or self.host_push_target is not None)
            )
            for name in CAPABILITY_NAMES
        }
        self.git = GitRepo(self.root)
        self.now = now
        self.progress = progress or (lambda _message: None)
        if quota_provider is None and self.policy["quota"].get("provider") != "manual":
            raise SupervisorError(f"unsupported quota provider: {self.policy['quota'].get('provider')!r}")
        self.quota: QuotaProvider = quota_provider or ManualQuotaProvider(
            self.runtime / "quota.json", now, models=self.policy["models"], quota_policy=self.policy["quota"],
        )
        self.model_runner = model_runner or CodexRunner(self.root, notify=self._emit_raw)
        self.supervisor_repair_runner = supervisor_repair_runner or (
            CodexRunner(self.assets_dir, notify=self._emit_raw)
            if self._uses_external_supervisor_repair() else self.model_runner
        )
        self.command_runner = command_runner or SubprocessCommandRunner()

    def capability_allowed(self, capability: str) -> bool:
        if capability not in CAPABILITY_NAMES:
            raise SupervisorError(f"unsupported capability: {capability!r}")
        return self.effective_capabilities[capability]

    def require_capability(self, capability: str) -> None:
        """Future mutation paths must call this before model or Git mutation."""
        if not self.capability_allowed(capability):
            raise SupervisorError(f"capability {capability!r} is disabled by project restriction or host grant")

    def effective_configuration(self) -> dict[str, Any]:
        """A secret-free status/audit representation of authority and its provenance."""
        return {
            "policy_version": self.policy["version"],
            "capabilities": {
                name: {
                    "effective": self.effective_capabilities[name],
                    "project_restriction": self.policy["capabilities"][name],
                    "host_grant": self.host_capability_grants[name],
                }
                for name in CAPABILITY_NAMES
            },
            "provenance": {
                "project_policy": str(self.root / PROJECT_POLICY_NAME),
                "host_capability_grants": self.host_capability_provenance,
                "host_push_target": self.host_push_target,
                "legacy_migration": self.legacy_policy_migration,
            },
        }

    def _supervisor_control_paths(self) -> tuple[str, ...]:
        configured = self.policy.get("supervisor_control_paths", list(DEFAULT_SUPERVISOR_CONTROL_PATHS))
        if (
            not isinstance(configured, list)
            or any(not isinstance(path, str) or not path for path in configured)
        ):
            raise SupervisorError("supervisor_control_paths must be an array of nonempty repository paths")
        return tuple(configured)

    def _is_supervisor_control_path(self, path: str) -> bool:
        return any(
            path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")
            for prefix in self._supervisor_control_paths()
        )

    def _uses_external_supervisor_repair(self) -> bool:
        return self.policy.get("supervisor_repair_repository") == "external"

    @staticmethod
    def _is_engine_repair_path(path: str) -> bool:
        allowed_files = {"README.md", "MIGRATION.md", "supervisor", "supervisor.py"}
        allowed_prefixes = ("prompts/", "schemas/", "tests/")
        return path in allowed_files or path.startswith(allowed_prefixes)

    def _repair_commit_is_current(self, diagnostic: dict[str, Any]) -> bool:
        commit = diagnostic.get("repair_commit")
        if not isinstance(commit, str) or not commit:
            return False
        repository = diagnostic.get("repair_repository")
        if repository == "external":
            engine_git = GitRepo(self.assets_dir)
            return engine_git.is_ancestor(commit, engine_git.head())
        return self.git.is_ancestor(commit, self.git.head())

    def _emit_raw(self, message: str) -> None:
        self.progress(f"[{self.now().astimezone().strftime('%H:%M:%S')}] {message}")

    def _emit(self, ticket: str, stage: str, result: str) -> None:
        self._emit_raw(f"{ticket} · {stage:<28} {result}")

    @contextmanager
    def operation_lock(self):
        """Prevent two CLI supervisors from advancing the same state concurrently."""
        self.runtime.mkdir(parents=True, exist_ok=True)
        path = self.runtime / "supervisor.lock"
        with path.open("a+", encoding="utf-8") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise SupervisorError("another development supervisor process is already running") from error
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _engine_identity(self, root: Path) -> dict[str, Any]:
        """Return a receipt for a clean immutable engine checkout."""
        root = root.resolve()
        git = GitRepo(root)
        git.require_repository()
        if not git.is_clean():
            raise SupervisorError("staged engine checkout must be clean")
        revision = git.head()
        if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
            raise SupervisorError("staged engine revision is not immutable")
        required = (root / "supervisor.py", root / "schemas", root / "tests")
        if any(not path.exists() for path in required):
            raise SupervisorError("staged engine is missing supervisor.py, schemas, or tests")
        return {
            "revision": revision,
            "build_id": self._directory_digest(root),
            "schema_version": STATE_VERSION,
            "protocol_version": ENGINE_PROTOCOL_VERSION,
        }

    @staticmethod
    def _compatibility_range(value: Any, *, name: str) -> tuple[int, int]:
        if not isinstance(value, dict) or set(value) != {"minimum", "maximum"}:
            raise SupervisorError(f"engine binding {name} compatibility range is malformed")
        lower, upper = value["minimum"], value["maximum"]
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in (lower, upper)) or lower > upper:
            raise SupervisorError(f"engine binding {name} compatibility range is invalid")
        return lower, upper

    def _load_engine_binding(self) -> dict[str, Any]:
        binding = read_json(self.engine_binding_path)
        # The exact T00 shape remains a compatibility reader only.  It cannot
        # establish mutable multi-host ownership and is never upgraded in place.
        if set(binding) == {"engine_root"} and isinstance(binding["engine_root"], str):
            return {"kind": "legacy", **binding}
        required = {"version", "engine_root", "identity", "compatibility"}
        if set(binding) != required or binding.get("version") != ENGINE_BINDING_VERSION:
            raise SupervisorError("engine binding has an unsupported version or fields")
        if not isinstance(binding["engine_root"], str) or not binding["engine_root"]:
            raise SupervisorError("engine binding root is malformed")
        identity = binding["identity"]
        if not isinstance(identity, dict) or set(identity) != {"revision", "build_id", "schema_version", "protocol_version"}:
            raise SupervisorError("engine binding identity is malformed")
        if not re.fullmatch(r"[0-9a-f]{40,64}", str(identity["revision"])) or not re.fullmatch(r"[0-9a-f]{64}", str(identity["build_id"])):
            raise SupervisorError("engine binding identity is not immutable")
        if identity["schema_version"] != STATE_VERSION or identity["protocol_version"] != ENGINE_PROTOCOL_VERSION:
            raise SupervisorError("engine binding names unsupported schema or protocol")
        compatibility = binding["compatibility"]
        if not isinstance(compatibility, dict) or set(compatibility) != {"state", "policy", "protocol"}:
            raise SupervisorError("engine binding compatibility is malformed")
        for name in ("state", "policy", "protocol"):
            self._compatibility_range(compatibility[name], name=name)
        return {"kind": "v2", **binding}

    def _assert_engine_binding(self, state: dict[str, Any] | None = None) -> dict[str, Any]:
        binding = self._load_engine_binding()
        if binding["kind"] == "legacy":
            return binding
        if Path(binding["engine_root"]).expanduser().resolve() != self.assets_dir:
            raise SupervisorError("active engine path does not match immutable binding")
        actual = self._engine_identity(self.assets_dir)
        if actual != binding["identity"]:
            raise SupervisorError("active engine provenance or integrity does not match immutable binding")
        current = state if state is not None else read_json(self.state_path)
        version = current.get("version")
        for name, value in (("state", version), ("policy", self.policy["version"]), ("protocol", ENGINE_PROTOCOL_VERSION)):
            lower, upper = self._compatibility_range(binding["compatibility"][name], name=name)
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise SupervisorError(f"active {name} version is incompatible with engine binding")
        required = current.get("engine_requirement")
        if required is not None and required != binding["identity"]:
            raise SupervisorError("host engine is stale or incompatible with the required engine identity")
        return binding

    def _assert_writer_lease(self, binding: dict[str, Any]) -> None:
        if binding["kind"] == "legacy":
            return
        owner = read_json(self.host_owner_path)
        if set(owner) != {"version", "host_id", "lease_id", "engine_build_id"} or owner.get("version") != 1:
            raise SupervisorError("host writer ownership is missing or malformed")
        host_id = os.environ.get("DEV_SUPERVISOR_HOST_ID")
        if not host_id or owner.get("host_id") != host_id:
            raise SupervisorError("host-local writer ownership does not match DEV_SUPERVISOR_HOST_ID")
        if not isinstance(owner.get("lease_id"), str) or not owner["lease_id"]:
            raise SupervisorError("host writer lease is malformed")
        if owner.get("engine_build_id") != binding["identity"]["build_id"]:
            raise SupervisorError("host writer lease is for a different engine build")

    def engine_update_dry_run(self, candidate: Path, *, run_tests: bool = True) -> dict[str, Any]:
        """Qualify an isolated checkout without touching the active binding/state."""
        candidate = candidate.expanduser().resolve()
        if candidate == self.assets_dir:
            raise SupervisorError("candidate engine must be staged outside the active controller")
        identity = self._engine_identity(candidate)
        state = self.load_state(read_only=True)
        if state.get("version") != STATE_VERSION:
            raise SupervisorError("engine update requires an explicitly migrated current state")
        snapshot = self._product_snapshot()
        tests: dict[str, Any] = {"ran": False, "passed": None}
        if run_tests:
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=candidate,
                text=True, capture_output=True, timeout=120,
            )
            tests = {"ran": True, "passed": result.returncode == 0, "returncode": result.returncode,
                     "output_digest": hashlib.sha256((result.stdout + result.stderr).encode()).hexdigest()}
            if result.returncode:
                raise SupervisorError("staged engine tests failed")
        report = {
            "version": 1, "status": "qualified", "candidate_root": str(candidate),
            "identity": identity,
            "compatibility": {"state": {"minimum": STATE_VERSION, "maximum": STATE_VERSION},
                              "policy": {"minimum": self.policy["version"], "maximum": self.policy["version"]},
                              "protocol": {"minimum": ENGINE_PROTOCOL_VERSION, "maximum": ENGINE_PROTOCOL_VERSION}},
            "state_migration": {"status": "not_required", "writes_required": False,
                                "source_version": state["version"]},
            "product_snapshot": snapshot, "tests": tests,
        }
        return report

    def _engine_update_is_quiescent(self, state: dict[str, Any]) -> None:
        if state.get("active_run") is not None or state.get("pending_push") is not None:
            raise SupervisorError("engine switch requires a quiescent state with no active or pending control")
        if state.get("phase") not in TERMINAL_STATES:
            raise SupervisorError("engine switch requires a quiescent terminal checkpoint")

    def activate_engine_update(self, candidate: Path, *, go: bool) -> dict[str, Any]:
        if not go:
            raise SupervisorError("engine activation requires an explicit human go decision")
        report = self.engine_update_dry_run(candidate)
        state = self.load_state(read_only=True)
        self._engine_update_is_quiescent(state)
        proposed_binding = {"kind": "v2", "identity": report["identity"]}
        # Ownership is checked before either archive or binding mutation.  A
        # synchronized checkout without its operator-local lease therefore
        # cannot even begin a cutover.
        self._assert_writer_lease(proposed_binding)
        before = self._product_snapshot()
        binding = self._load_engine_binding()
        archive = {"version": 1, "binding": binding, "state_checksum": content_checksum(state),
                   "product_snapshot": before}
        archive_path = self.runtime / ENGINE_ARCHIVES_DIRECTORY / (content_checksum(archive) + ".json")
        if archive_path.exists():
            raise SupervisorError("engine archive collision; refusing to overwrite rollback material")
        # Archive is durable before the atomic binding replacement.  The staged
        # directory is never copied or modified, so the active process cannot
        # observe a partially updated tree.
        atomic_write_json(archive_path, archive)
        new_binding = {"version": ENGINE_BINDING_VERSION, "engine_root": report["candidate_root"],
                       "identity": report["identity"], "compatibility": report["compatibility"]}
        atomic_write_json(self.engine_binding_path, new_binding)
        # Reconciliation is intentionally read-only: it proves that switching
        # changed neither product HEAD/fingerprint nor the state snapshot.
        if self._product_snapshot() != before or content_checksum(read_json(self.state_path)) != archive["state_checksum"]:
            atomic_write_json(self.engine_binding_path, binding)
            raise SupervisorError("post-switch read-only reconciliation failed; prior binding was restored")
        updated = deepcopy(state)
        updated["engine_requirement"] = report["identity"]
        # This is the one handoff write performed by the retiring generation.
        # It cannot use save_state because that deliberately refuses a process
        # whose own code is no longer the newly bound generation.
        updated["updated_at"] = isoformat(self.now())
        atomic_write_json(self.state_path, updated)
        result = {"status": "activated", "archive": str(archive_path.relative_to(self.runtime)),
                  "identity": report["identity"], "product_snapshot": before}
        atomic_write_json(self.engine_update_path, result)
        return result

    def rollback_engine_update(self) -> dict[str, Any]:
        record = read_json(self.engine_update_path)
        archive_ref = record.get("archive")
        if not isinstance(archive_ref, str) or Path(archive_ref).is_absolute() or ".." in Path(archive_ref).parts:
            raise SupervisorError("engine update rollback record is malformed")
        archive = read_json(self.runtime / archive_ref)
        state = self.load_state(read_only=True)
        self._engine_update_is_quiescent(state)
        before = self._product_snapshot()
        current = self._assert_engine_binding(state)
        self._assert_writer_lease(current)
        prior = archive.get("binding")
        if not isinstance(prior, dict) or state.get("engine_requirement") != current.get("identity"):
            raise SupervisorError("engine rollback archive does not match current quiescent state")
        atomic_write_json(self.engine_binding_path, prior)
        restored = deepcopy(state)
        restored.pop("engine_requirement", None)
        restored["updated_at"] = isoformat(self.now())
        atomic_write_json(self.state_path, restored)
        if self._product_snapshot() != before:
            atomic_write_json(self.engine_binding_path, current)
            raise SupervisorError("rollback changed product state; active binding was restored")
        result = {"status": "rolled_back", "archive": archive_ref, "product_snapshot": before}
        atomic_write_json(self.engine_update_path, result)
        return result

    def _legacy_cutover_artifacts(self) -> dict[str, dict[str, str]]:
        """Return exact, bounded-by-runtime evidence for legacy run artifacts.

        The source runtime is operator-local and ignored by Git.  Encoding each
        regular artifact in the archive (rather than retaining a path reference)
        means a rollback does not depend on an unchanged legacy runtime directory.
        """
        artifacts: dict[str, dict[str, str]] = {}
        runs = self.runs_dir
        if not runs.exists():
            return artifacts
        if not runs.is_dir():
            raise SupervisorError("legacy run-artifact location is not a directory")
        for path in sorted(runs.rglob("*")):
            if path.is_symlink() or not path.is_file():
                if path.is_symlink():
                    raise SupervisorError("legacy run artifacts may not contain symbolic links")
                continue
            relative = path.relative_to(self.runtime).as_posix()
            raw = path.read_bytes()
            artifacts[relative] = {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "base64": base64.b64encode(raw).decode("ascii"),
            }
        return artifacts

    @staticmethod
    def _legacy_cutover_bytes(path: Path) -> dict[str, str]:
        raw = path.read_bytes()
        return {"sha256": hashlib.sha256(raw).hexdigest(), "base64": base64.b64encode(raw).decode("ascii")}

    def _legacy_cutover_engine_identity(self, root: Path) -> dict[str, Any]:
        """Receipt the pinned AS-IS engine, retaining its documented safety guard."""
        root = root.resolve()
        git = GitRepo(root)
        git.require_repository()
        unexpected = [entry for entry in git.status_entries() if entry != ("??", ".self-repair-disabled")]
        if unexpected:
            raise SupervisorError("legacy source engine has unsupported dirty files")
        guard = root / ".self-repair-disabled"
        if guard.exists() and (not guard.is_file() or guard.is_symlink()):
            raise SupervisorError("legacy source engine self-repair guard is malformed")
        revision = git.head()
        if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
            raise SupervisorError("legacy source engine revision is not immutable")
        required = (root / "supervisor.py", root / "schemas", root / "tests")
        if any(not path.exists() for path in required):
            raise SupervisorError("legacy source engine is missing supervisor.py, schemas, or tests")
        return {
            "revision": revision, "build_id": self._directory_digest(root),
            "schema_version": 4, "protocol_version": ENGINE_PROTOCOL_VERSION,
            "self_repair_guard_sha256": hashlib.sha256(guard.read_bytes()).hexdigest() if guard.exists() else None,
        }

    def _legacy_cutover_source(self) -> dict[str, Any]:
        """Validate the one supported 1.x checkpoint without writing anything."""
        if not self.engine_binding_path.exists():
            raise SupervisorError("legacy cutover requires a path-only 1.x engine binding")
        binding = self._load_engine_binding()
        if binding["kind"] != "legacy":
            raise SupervisorError("legacy cutover source is already bound to a versioned engine")
        source_engine = Path(binding["engine_root"]).expanduser().resolve()
        if source_engine == self.assets_dir:
            raise SupervisorError("legacy cutover source engine must differ from the candidate controller")
        engine = self._legacy_cutover_engine_identity(source_engine)
        state = read_json(self.state_path)
        # The historical T30 gate is the only qualified 1.x source.  In
        # particular, conversion of an active run, verification, commit, or a
        # guessed terminal state is deliberately outside the supported surface.
        if state.get("version") != 4:
            raise SupervisorError("unsupported legacy source state version; only 1.x v4 HUMAN_GATE is qualified")
        if state.get("phase") != "HUMAN_GATE":
            raise SupervisorError("legacy source is active or unsupported; only HUMAN_GATE is qualified")
        if state.get("active_run") is not None or state.get("pending_commit") is not None:
            raise SupervisorError("legacy source has active model/check/commit control and cannot be cut over")
        gate = state.get("gate")
        if not isinstance(gate, dict) or gate.get("ticket") != state.get("current_ticket"):
            raise SupervisorError("legacy HUMAN_GATE ownership is missing or ambiguous")
        actual_head = self.git.head()
        actual_fingerprint = self.git.fingerprint()
        recorded_fingerprint = gate.get("fingerprint")
        history = state.get("history")
        last_transition = history[-1] if isinstance(history, list) and history else None
        exact_clean_milestone_without_fingerprint = (
            recorded_fingerprint is None
            and self.git.is_clean()
            and actual_fingerprint == hashlib.sha256(b"").hexdigest()
            and set(gate) == {"head", "kind", "name", "ticket"}
            and gate.get("kind") == "milestone"
            and isinstance(gate.get("name"), str)
            and bool(gate["name"].strip())
            and state.get("last_commit") == actual_head
            and isinstance(last_transition, dict)
            and last_transition.get("from") == "COMMITTING"
            and last_transition.get("to") == "HUMAN_GATE"
            and last_transition.get("message") == state.get("message")
        )
        if (
            gate.get("head") != actual_head
            or (
                recorded_fingerprint != actual_fingerprint
                and not exact_clean_milestone_without_fingerprint
            )
        ):
            raise SupervisorError("legacy dirty state is unsupported because its preserved gate fingerprint disagrees")
        if not isinstance(state.get("current_ticket"), str) or not isinstance(state.get("completed_tickets"), list):
            raise SupervisorError("legacy source ticket lineage is malformed or ambiguous")
        raw_policy = read_json(self.root / PROJECT_POLICY_NAME)
        if raw_policy.get("version") not in {1, 2}:
            raise SupervisorError("unsupported legacy policy version")
        policy, policy_report = migrate_legacy_policy(raw_policy)
        validate_project_policy(policy)
        raw_quota = read_json(self.runtime / "quota.json")
        if raw_quota.get("version") != 2:
            raise SupervisorError("unsupported legacy quota ledger version")
        quota_target = self.quota._convert_v2(raw_quota) if isinstance(self.quota, ManualQuotaProvider) else None
        if quota_target is None:
            raise SupervisorError("legacy cutover requires the manual quota ledger provider")
        product = self._product_snapshot()
        archive = {
            "version": 1,
            "kind": "qualified_1x_predecessor",
            "engine": engine,
            "binding": binding,
            "policy": raw_policy,
            "state": state,
            "quota": raw_quota,
            "source_files": {
                PROJECT_POLICY_NAME: self._legacy_cutover_bytes(self.root / PROJECT_POLICY_NAME),
                "state.json": self._legacy_cutover_bytes(self.state_path),
                "quota.json": self._legacy_cutover_bytes(self.runtime / "quota.json"),
            },
            "artifacts": self._legacy_cutover_artifacts(),
            "git": {"head": self.git.head(), "branch": self.git.branch(), "fingerprint": self.git.fingerprint(),
                    "product_snapshot": product},
            "lock_ownership": {"authority": "legacy supervisor.lock", "owner": "current cutover operation"},
        }
        return {
            "archive": archive, "source_checksum": content_checksum(archive), "binding": binding,
            "state": state, "policy": policy, "policy_report": policy_report,
            "quota": quota_target, "product_snapshot": product,
        }

    def legacy_cutover_dry_run(self, candidate: Path) -> dict[str, Any]:
        """Qualify a supported 1.x gate and produce an entirely non-writing receipt."""
        candidate = candidate.expanduser().resolve()
        source = self._legacy_cutover_source()
        identity = self._engine_identity(candidate)
        if candidate == Path(source["binding"]["engine_root"]).expanduser().resolve():
            raise SupervisorError("legacy cutover candidate must be a separate immutable 2.0 checkout")
        migrated, state_report = self._legacy_cutover_migrated_state(source)
        archive_ref = f"{LEGACY_CUTOVER_ARCHIVES_DIRECTORY}/{source['source_checksum']}.json"
        migrated["legacy_cutover"] = {"version": 1, "checksum": source["source_checksum"], "archive": archive_ref}
        migrated.setdefault("audit_events", [])
        prior = migrated["audit_events"][-1]["event_id"] if migrated["audit_events"] else None
        migrated["audit_events"].append(audit_event("legacy_cutover_converted", {
            "predecessor_checksum": source["source_checksum"], "from_engine_revision": source["archive"]["engine"]["revision"],
        }, prior))
        compatibility = {"state": {"minimum": STATE_VERSION, "maximum": STATE_VERSION},
                         "policy": {"minimum": POLICY_VERSION, "maximum": POLICY_VERSION},
                         "protocol": {"minimum": ENGINE_PROTOCOL_VERSION, "maximum": ENGINE_PROTOCOL_VERSION}}
        return {
            "version": 1, "status": "supported", "writes_required": True,
            "source_checksum": source["source_checksum"], "archive": archive_ref,
            "candidate": {"root": str(candidate), "identity": identity, "compatibility": compatibility},
            "policy": source["policy_report"], "state": {**state_report, "target_checksum": content_checksum(migrated)},
            "quota": {"from_version": 2, "to_version": 3, "source_checksum": content_checksum(source["archive"]["quota"]),
                      "target_checksum": content_checksum(source["quota"]), "consumed_authorizations": "invalidated; never reusable"},
            "product_snapshot": source["product_snapshot"],
            "rejection_boundary": "Only an exact v4 HUMAN_GATE with matching gate HEAD/fingerprint and no active control is supported.",
        }

    def _legacy_cutover_migrated_state(self, source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Make the v4 epoch conversion repeatable from archived source bytes."""
        updated_at = source["state"].get("updated_at")
        if not isinstance(updated_at, str):
            raise SupervisorError("legacy HUMAN_GATE lacks a durable update timestamp for deterministic conversion")
        migrated, report = self._migrate_state_v4(source["state"])
        # _new_plan_epoch normally makes a new UUID/time for a new plan.  A
        # conversion must instead have the same target for dry-run and apply.
        epoch = migrated["plan_epochs"][0]
        epoch["epoch_id"] = source["source_checksum"][:32]
        epoch["created_at"] = updated_at
        migrated["current_plan_epoch_id"] = epoch["epoch_id"]
        return migrated, report

    def apply_legacy_cutover(self, candidate: Path, *, source_checksum: str, go: bool) -> dict[str, Any]:
        if not go:
            raise SupervisorError("legacy cutover binding switch requires an explicit human go decision")
        report = self.legacy_cutover_dry_run(candidate)
        if source_checksum != report["source_checksum"]:
            raise SupervisorError("legacy cutover source changed or does not match the reviewed dry-run receipt")
        proposed = {"kind": "v2", "identity": report["candidate"]["identity"]}
        self._assert_writer_lease(proposed)
        source = self._legacy_cutover_source()
        archive_path = self.runtime / report["archive"]
        if archive_path.exists():
            raise SupervisorError("legacy predecessor archive already exists; use rollback or investigate, never overwrite it")
        migrated, _state_report = self._legacy_cutover_migrated_state(source)
        migrated["legacy_cutover"] = {"version": 1, "checksum": report["source_checksum"], "archive": report["archive"]}
        migrated.setdefault("audit_events", [])
        prior = migrated["audit_events"][-1]["event_id"] if migrated["audit_events"] else None
        migrated["audit_events"].append(audit_event("legacy_cutover_converted", {
            "predecessor_checksum": report["source_checksum"], "from_engine_revision": source["archive"]["engine"]["revision"],
        }, prior))
        if content_checksum(migrated) != report["state"]["target_checksum"]:
            raise SupervisorError("legacy state conversion was not deterministic")
        before = source["product_snapshot"]
        # Archive precedes every conversion write.  It includes exact policy, state,
        # quota, artifacts, Git identity, and the authority observed under this lock.
        atomic_write_json(archive_path, source["archive"])
        atomic_write_json(self.root / PROJECT_POLICY_NAME, source["policy"])
        atomic_write_json(self.runtime / "quota.json", source["quota"])
        migrated["engine_requirement"] = report["candidate"]["identity"]
        atomic_write_json(self.state_path, migrated)
        new_binding = {"version": ENGINE_BINDING_VERSION, "engine_root": report["candidate"]["root"],
                       "identity": report["candidate"]["identity"], "compatibility": report["candidate"]["compatibility"]}
        # This single replace is the authority handoff.  Nothing auto-selects it:
        # the reviewed receipt and explicit --go are both required.
        atomic_write_json(self.engine_binding_path, new_binding)
        reconciled = self._product_snapshot() == before and self.git.head() == source["archive"]["git"]["head"]
        if not reconciled:
            atomic_write_json(self.engine_binding_path, source["binding"])
            raise SupervisorError("cutover reconciliation changed product HEAD or working tree; legacy binding was restored")
        result = {"status": "cutover_applied", "archive": report["archive"], "source_checksum": report["source_checksum"],
                  "identity": report["candidate"]["identity"], "product_snapshot": before,
                  "required_human_action": "Run read-only status with the new controller, then record go/no-go; use legacy-cutover rollback for no-go."}
        atomic_write_json(self.legacy_cutover_path, result)
        return result

    def rollback_legacy_cutover(self) -> dict[str, Any]:
        record = read_json(self.legacy_cutover_path)
        if record.get("status") != "cutover_applied":
            raise SupervisorError(
                "legacy rollback is closed after cutover acceptance; preserve the predecessor archive for explicit recovery"
            )
        archive_ref = record.get("archive")
        if not isinstance(archive_ref, str) or Path(archive_ref).is_absolute() or ".." in Path(archive_ref).parts:
            raise SupervisorError("legacy cutover rollback record is malformed")
        archive = read_json(self.runtime / archive_ref)
        if archive.get("kind") != "qualified_1x_predecessor" or content_checksum(archive) != record.get("source_checksum"):
            raise SupervisorError("legacy cutover predecessor archive is missing or inconsistent")
        state = self.load_state(read_only=True)
        self._engine_update_is_quiescent(state)
        if state.get("phase") != "HUMAN_GATE" or self._current_epoch(state).get("completion") is not None:
            raise SupervisorError("legacy rollback is closed after cutover acceptance")
        current = self._assert_engine_binding(state)
        self._assert_writer_lease(current)
        before = self._product_snapshot()
        atomic_write_json(self.engine_binding_path, archive["binding"])
        atomic_write_json(self.root / PROJECT_POLICY_NAME, archive["policy"])
        atomic_write_json(self.runtime / "quota.json", archive["quota"])
        atomic_write_json(self.state_path, archive["state"])
        if self._product_snapshot() != before or self.git.head() != archive["git"]["head"]:
            raise SupervisorError("legacy rollback changed product HEAD or working tree; preserve evidence and stop")
        result = {"status": "rolled_back", "archive": archive_ref, "product_snapshot": before}
        atomic_write_json(self.legacy_cutover_path, result)
        return result

    def accept_legacy_cutover(self, note: str) -> dict[str, Any]:
        """Close an exact migrated sentinel after the new generation was accepted.

        This is deliberately narrower than a general state override: it applies only
        to the quiescent HUMAN_GATE produced by the qualified 1.x cutover, preserves
        the predecessor archive, and never invokes a model or creates a Git commit.
        """
        note = note.strip()
        if not note or len(note) > 2000:
            raise SupervisorError("cutover acceptance note must contain 1 to 2000 characters")
        state = self.load_state()
        if state.get("version") != STATE_VERSION or state.get("phase") not in {"HUMAN_GATE", "PLAN_COMPLETED"}:
            raise SupervisorError("cutover acceptance requires the exact quiescent final milestone sentinel")
        epoch = self._current_epoch(state)
        existing_completion = epoch.get("completion")
        record = read_json(self.legacy_cutover_path)
        if (
            state.get("phase") == "PLAN_COMPLETED"
            and isinstance(existing_completion, dict)
            and existing_completion.get("reason") == "qualified legacy cutover accepted by the operator"
        ):
            if record.get("status") == "cutover_accepted" and record.get("acceptance") == existing_completion:
                return state
            if (
                record.get("status") == "cutover_applied"
                and record.get("source_checksum") == existing_completion.get("cutover_checksum")
                and record.get("archive") == existing_completion.get("archive")
            ):
                event = next(
                    (item for item in state.get("audit_events", [])
                     if item.get("kind") == "legacy_cutover_accepted"
                     and item.get("payload") == existing_completion),
                    None,
                )
                if event is None:
                    raise SupervisorError("accepted cutover state lacks its audit event")
                atomic_write_json(self.legacy_cutover_path, {
                    **record, "status": "cutover_accepted", "acceptance": existing_completion,
                    "audit_event_id": event["event_id"],
                })
                return state
            raise SupervisorError("accepted cutover state contradicts its durable cutover record")
        ticket = state.get("current_ticket")
        gate = state.get("gate")
        if (
            state.get("version") != STATE_VERSION
            or state.get("phase") != "HUMAN_GATE"
            or not isinstance(gate, dict)
            or gate.get("kind") != "milestone"
            or gate.get("ticket") != ticket
            or state.get("active_run") is not None
            or state.get("pending_commit") is not None
            or state.get("starting_head") is not None
        ):
            raise SupervisorError("cutover acceptance requires the exact quiescent final milestone sentinel")
        if ticket != epoch["tickets"][-1]:
            raise SupervisorError("cutover acceptance requires the exact quiescent final milestone sentinel")
        expected_completed = epoch["tickets"][:-1]
        if state.get("completed_tickets") != expected_completed:
            raise SupervisorError("cutover acceptance requires the exact completed predecessor ticket prefix")
        actual_head = self.git.head()
        gate_head = gate.get("head")
        cutover = state.get("legacy_cutover")
        if (
            not isinstance(cutover, dict)
            or cutover.get("version") != 1
            or record.get("status") != "cutover_applied"
            or record.get("source_checksum") != cutover.get("checksum")
            or record.get("archive") != cutover.get("archive")
        ):
            raise SupervisorError("cutover acceptance lacks the exact applied predecessor record")
        archive = read_json(self.runtime / cutover["archive"])
        if (
            archive.get("kind") != "qualified_1x_predecessor"
            or content_checksum(archive) != cutover["checksum"]
        ):
            raise SupervisorError("cutover acceptance predecessor archive is missing or inconsistent")
        binding = self._assert_engine_binding(state)
        exact_gate_head = gate_head == actual_head
        qualified_bootstrap_descendant = (
            isinstance(gate_head, str)
            and self.git.is_ancestor(gate_head, actual_head)
            and binding["identity"]["revision"] == actual_head
        )
        if not exact_gate_head and not qualified_bootstrap_descendant:
            raise SupervisorError(
                "cutover acceptance requires the gate HEAD or its exact activated immutable bootstrap successor"
            )
        evidence = {
            "commit": gate_head,
            "acceptance_head": actual_head,
            "ticket": ticket,
            "reason": "qualified legacy cutover accepted by the operator",
            "cutover_checksum": cutover["checksum"],
            "archive": cutover["archive"],
            "note": note,
        }
        epoch["completion"] = evidence
        state["completed_tickets"].append(ticket)
        event = self._append_audit_event(state, "legacy_cutover_accepted", evidence)
        self.transition(
            state, "PLAN_COMPLETED",
            f"Legacy plan epoch {epoch['epoch_id']} closed after accepted cutover; new work requires a separately approved epoch.",
            gate=None, active_run=None, pending_commit=None, starting_head=None,
            completion_reason=evidence["reason"], final_result=evidence,
        )
        atomic_write_json(self.legacy_cutover_path, {
            **record, "status": "cutover_accepted", "acceptance": evidence,
            "audit_event_id": event["event_id"],
        })
        return state

    @property
    def cold_start_path(self) -> Path:
        """The cold-start record is separate from execution state by design."""
        return self.runtime / COLD_START_STATE_NAME

    def _cold_start_artifact_path(self, relative: str) -> Path:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise SupervisorError("cold-start artifact path is unsafe")
        return self.runtime / COLD_START_DIRECTORY / candidate

    @staticmethod
    def _cold_start_digest(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    def _load_cold_start(self) -> dict[str, Any]:
        state = read_json(self.cold_start_path)
        required = {"version", "phase", "source_specification", "revisions", "approval", "plan"}
        if set(state) != required or state.get("version") != 1 or state.get("phase") not in COLD_START_PHASES:
            raise SupervisorError("cold-start state is malformed or has an unsupported version")
        source = state.get("source_specification")
        if (
            not isinstance(source, dict) or set(source) != {"path", "digest"}
            or not isinstance(source.get("path"), str) or not isinstance(source.get("digest"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", source["digest"])
        ):
            raise SupervisorError("cold-start source specification identity is malformed")
        artifact = self._cold_start_artifact_path(source["path"])
        if not artifact.is_file() or self._cold_start_digest(artifact.read_bytes()) != source["digest"]:
            raise SupervisorError("cold-start source specification artifact is missing or changed")
        revisions = state.get("revisions")
        if not isinstance(revisions, list) or any(not isinstance(item, dict) for item in revisions):
            raise SupervisorError("cold-start revision lineage is malformed")
        latest_requirements: str | None = None
        latest_architecture: dict[str, Any] | None = None
        for revision in revisions:
            required_revision = {
                "kind", "digest", "parent_digest", "source_specification_digest", "artifact",
            }
            if (
                set(revision) != required_revision or revision.get("kind") not in {"requirements", "architecture"}
                or not all(isinstance(revision.get(key), str) for key in required_revision - {"kind"})
                or not re.fullmatch(r"[0-9a-f]{64}", revision["digest"])
                or revision["source_specification_digest"] != source["digest"]
            ):
                raise SupervisorError("cold-start revision identity is malformed")
            proposal_path = self._cold_start_artifact_path(revision["artifact"])
            proposal = read_json(proposal_path)
            if content_checksum(proposal) != revision["digest"] or proposal.get("kind") != revision["kind"]:
                raise SupervisorError("cold-start revision artifact was changed or does not match its digest")
            if proposal.get("source_specification_digest") != source["digest"] or proposal.get("parent_revision_digest") != revision["parent_digest"]:
                raise SupervisorError("cold-start revision artifact lineage does not match its record")
            content_error = self._cold_start_content_error(revision["kind"], proposal.get("content"))
            if content_error is not None:
                raise SupervisorError(content_error)
            expected_parent = latest_requirements or source["digest"]
            if revision["kind"] == "requirements":
                if revision["parent_digest"] != expected_parent:
                    raise SupervisorError("cold-start requirements lineage is broken")
                latest_requirements = revision["digest"]
            else:
                if latest_requirements is None or revision["parent_digest"] != latest_requirements:
                    raise SupervisorError("cold-start architecture lineage is broken")
                latest_architecture = revision
        approval = state.get("approval")
        if state["phase"] == "REQUIREMENTS_REVIEW" and approval is not None:
            raise SupervisorError("requirements review cannot retain an approval")
        if state["phase"] == "ARCHITECTURE_REVIEW":
            if (
                not isinstance(approval, dict) or set(approval) != {"requirements_revision_digest"}
                or approval.get("requirements_revision_digest") != latest_requirements
            ):
                raise SupervisorError("architecture review requires the exact approved requirements revision")
        if state["phase"] == "PLAN_READY":
            if (
                not isinstance(approval, dict)
                or set(approval) != {"requirements_revision_digest", "architecture_revision_digest"}
                or approval.get("requirements_revision_digest") != latest_requirements
                or latest_architecture is None
                or approval.get("architecture_revision_digest") != latest_architecture.get("digest")
            ):
                raise SupervisorError("plan readiness requires exact current requirements and architecture approval")
        return state

    def _save_cold_start(self, state: dict[str, Any]) -> None:
        atomic_write_json(self.cold_start_path, state)

    def begin_cold_start(self, specification_path: Path) -> dict[str, Any]:
        """Capture an immutable user specification before any plan or ticket exists."""
        if self.cold_start_path.exists():
            raise SupervisorError("a cold-start review already exists; resume its recorded review state")
        source = specification_path.expanduser().resolve()
        try:
            contents = source.read_bytes()
        except OSError as error:
            raise SupervisorError("cannot read the source specification") from error
        if not contents:
            raise SupervisorError("the source specification must not be empty")
        plan = self.root / self.policy["implementation_plan"]
        tickets = self.root / "docs" / "architecture" / "tickets"
        if plan.exists() or tickets.exists():
            raise SupervisorError("cold start requires no pre-existing implementation plan or tickets")
        artifact_relative = "source-specification.bin"
        artifact = self._cold_start_artifact_path(artifact_relative)
        atomic_write_text(artifact, contents.decode("utf-8")) if self._is_utf8(contents) else self._write_cold_start_bytes(artifact, contents)
        state = {
            "version": 1,
            "phase": "REQUIREMENTS_REVIEW",
            "source_specification": {"path": artifact_relative, "digest": self._cold_start_digest(contents)},
            "revisions": [],
            "approval": None,
            "plan": None,
        }
        self._save_cold_start(state)
        return state

    @staticmethod
    def _is_utf8(value: bytes) -> bool:
        try:
            value.decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False

    @staticmethod
    def _write_cold_start_bytes(path: Path, value: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @staticmethod
    def _cold_start_content_error(kind: str, content: Any) -> str | None:
        required = {
            "requirements": {"goals", "constraints", "unknowns", "conflicts", "non_goals"},
            "architecture": {
                "alternatives", "selected_design", "complexity_rationale", "system_boundaries",
                "data_integrations", "risks",
            },
        }.get(kind)
        if required is None or not isinstance(content, dict) or set(content) != required:
            return f"{kind} revision must contain exactly the required review fields"
        for name, value in content.items():
            if name in {"selected_design", "complexity_rationale"}:
                if not isinstance(value, str) or not value.strip():
                    return f"{kind} field {name!r} must be a nonempty string"
            elif (
                not isinstance(value, list)
                or any(not isinstance(item, str) or not item.strip() for item in value)
            ):
                return f"{kind} field {name!r} must be an array of nonempty strings"
        return None

    def submit_cold_start_revision(self, proposal_path: Path) -> dict[str, Any]:
        """Archive one immutable human/model proposal; this never grants approval."""
        state = self._load_cold_start()
        if state["phase"] not in {"REQUIREMENTS_REVIEW", "ARCHITECTURE_REVIEW"}:
            raise SupervisorError("cold-start proposals are closed after architecture approval")
        try:
            proposal = read_json(proposal_path.expanduser().resolve())
        except SupervisorError as error:
            raise SupervisorError("cold-start proposal must be a JSON object") from error
        required = {"version", "kind", "source_specification_digest", "parent_revision_digest", "content"}
        if set(proposal) != required or proposal.get("version") != 1 or proposal.get("kind") not in {"requirements", "architecture"}:
            raise SupervisorError("cold-start proposal has an unsupported version, kind, or keys")
        kind = proposal["kind"]
        expected_kind = "requirements" if state["phase"] == "REQUIREMENTS_REVIEW" else "architecture"
        if kind != expected_kind:
            raise SupervisorError(f"{expected_kind} review requires a {expected_kind} proposal")
        if proposal.get("source_specification_digest") != state["source_specification"]["digest"]:
            raise SupervisorError("cold-start proposal does not name the captured source specification")
        previous = state["revisions"][-1] if state["revisions"] else None
        prior_requirements = next(
            (item for item in reversed(state["revisions"]) if item.get("kind") == "requirements"), None,
        )
        expected_parent = (
            prior_requirements["digest"] if kind == "requirements" and prior_requirements is not None
            else state["source_specification"]["digest"] if kind == "requirements"
            else state["approval"]["requirements_revision_digest"]
        )
        if proposal.get("parent_revision_digest") != expected_parent:
            raise SupervisorError("cold-start proposal parent does not match the reviewed lineage")
        content_error = self._cold_start_content_error(kind, proposal.get("content"))
        if content_error is not None:
            raise SupervisorError(content_error)
        digest = content_checksum(proposal)
        revision = {
            "kind": kind, "digest": digest, "parent_digest": expected_parent,
            "source_specification_digest": state["source_specification"]["digest"],
            "artifact": f"revisions/{digest}.json",
        }
        if previous and previous.get("digest") == digest:
            return state
        artifact = self._cold_start_artifact_path(revision["artifact"])
        if artifact.exists() and artifact.read_bytes() != canonical_json_bytes(proposal):
            raise SupervisorError("cold-start revision digest collides with different content")
        self._write_cold_start_bytes(artifact, canonical_json_bytes(proposal))
        state["revisions"].append(revision)
        # A new revision always invalidates any approval that could have named an older one.
        state["approval"] = (
            None if kind == "requirements"
            else {"requirements_revision_digest": state["approval"]["requirements_revision_digest"]}
        )
        self._save_cold_start(state)
        return state

    def correct_cold_start(self, stage: str) -> dict[str, Any]:
        """Return to an exact review stage without deleting prior approved lineage."""
        state = self._load_cold_start()
        phases = {"requirements": "REQUIREMENTS_REVIEW", "architecture": "ARCHITECTURE_REVIEW"}
        if stage not in phases:
            raise SupervisorError("cold-start correction stage must be requirements or architecture")
        if stage == "architecture" and not isinstance(state.get("approval"), dict):
            raise SupervisorError("architecture correction requires an approved requirements revision")
        state["phase"] = phases[stage]
        if stage == "requirements":
            state["approval"] = None
        else:
            state["approval"] = {
                "requirements_revision_digest": state["approval"]["requirements_revision_digest"],
            }
        self._save_cold_start(state)
        return state

    def approve_cold_start_requirements(self, revision_digest: str) -> dict[str, Any]:
        state = self._load_cold_start()
        if state["phase"] != "REQUIREMENTS_REVIEW":
            raise SupervisorError("requirements approval is only valid during REQUIREMENTS_REVIEW")
        revision = state["revisions"][-1] if state["revisions"] else None
        if not isinstance(revision, dict) or revision.get("kind") != "requirements" or revision.get("digest") != revision_digest:
            raise SupervisorError("requirements approval must name the exact current requirements revision")
        state["approval"] = {"requirements_revision_digest": revision_digest}
        state["phase"] = "ARCHITECTURE_REVIEW"
        self._save_cold_start(state)
        return state

    def approve_cold_start_architecture(self, requirements_digest: str, architecture_digest: str) -> dict[str, Any]:
        state = self._load_cold_start()
        approval = state.get("approval")
        revision = state["revisions"][-1] if state["revisions"] else None
        if (
            state["phase"] != "ARCHITECTURE_REVIEW" or not isinstance(approval, dict)
            or approval.get("requirements_revision_digest") != requirements_digest
            or not isinstance(revision, dict) or revision.get("kind") != "architecture"
            or revision.get("digest") != architecture_digest
        ):
            raise SupervisorError("architecture approval must name the exact current requirements and architecture revisions")
        state["approval"] = {
            "requirements_revision_digest": requirements_digest,
            "architecture_revision_digest": architecture_digest,
        }
        state["phase"] = "PLAN_READY"
        self._save_cold_start(state)
        return state

    def materialize_cold_start_plan(
        self, plan_source: Path, requirements_digest: str, architecture_digest: str,
    ) -> dict[str, Any]:
        """Write a plan only from the two exact versions explicitly approved by a human."""
        state = self._load_cold_start()
        approval = state.get("approval")
        if (
            state["phase"] != "PLAN_READY" or not isinstance(approval, dict)
            or approval.get("requirements_revision_digest") != requirements_digest
            or approval.get("architecture_revision_digest") != architecture_digest
        ):
            raise SupervisorError("a plan requires explicit approval of the exact requirements and architecture revisions")
        if state.get("plan") is not None:
            raise SupervisorError("cold-start plan has already been materialized")
        destination = self.root / self.policy["implementation_plan"]
        if destination.exists():
            raise SupervisorError("refusing to overwrite an existing implementation plan")
        try:
            contents = plan_source.expanduser().resolve().read_bytes()
        except OSError as error:
            raise SupervisorError("cannot read the approved plan source") from error
        if not contents:
            raise SupervisorError("the approved plan source must not be empty")
        self._write_cold_start_bytes(destination, contents)
        state["plan"] = {"path": self.policy["implementation_plan"], "digest": self._cold_start_digest(contents)}
        self._save_cold_start(state)
        return state

    def cold_start_status(self) -> dict[str, Any]:
        state = self._load_cold_start()
        action = {
            "REQUIREMENTS_REVIEW": "submit or explicitly approve the exact current requirements revision",
            "ARCHITECTURE_REVIEW": "submit or explicitly approve the exact current architecture revision",
            "PLAN_READY": "materialize a plan using the exact approved requirements and architecture revisions",
        }[state["phase"]]
        return {**state, "required_human_action": action}

    # Backlog review is deliberately a separate record from the immutable plan
    # epoch.  In particular, a completed plan never becomes executable merely
    # because somebody has put text in BACKLOG.md.
    @property
    def backlog_cycle_path(self) -> Path:
        return self.runtime / BACKLOG_CYCLE_STATE_NAME

    def _backlog_cycle_artifact(self, relative: str) -> Path:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise SupervisorError("backlog-cycle artifact path is unsafe")
        return self.runtime / BACKLOG_CYCLE_DIRECTORY / candidate

    @staticmethod
    def _backlog_content_error(kind: str, content: Any, selected: set[str]) -> str | None:
        if kind == "requirements":
            required = {"requirements", "dependencies", "duplicates", "readiness", "architecture_impact", "outcomes"}
            if not isinstance(content, dict) or set(content) != required:
                return "backlog requirements revision must contain exactly the required analysis fields"
            for name in required - {"outcomes"}:
                if not isinstance(content[name], list) or any(not isinstance(item, str) or not item.strip() for item in content[name]):
                    return f"backlog requirements field {name!r} must be an array of nonempty strings"
            outcomes = content["outcomes"]
            if not isinstance(outcomes, list) or len(outcomes) != len(selected):
                return "backlog outcomes must give exactly one disposition for every selected item"
            seen: set[str] = set()
            for outcome in outcomes:
                if not isinstance(outcome, dict) or set(outcome) != {"item_id", "disposition", "reason"}:
                    return "backlog outcome must contain item_id, disposition, and reason"
                if outcome.get("item_id") not in selected or outcome["item_id"] in seen:
                    return "backlog outcomes must name each selected item exactly once"
                if outcome.get("disposition") not in {"accepted", "rejected", "deferred", "duplicate", "missing_information"}:
                    return "backlog outcome has an unsupported disposition"
                if not isinstance(outcome.get("reason"), str) or not outcome["reason"].strip():
                    return "backlog outcome reason must be nonempty"
                seen.add(outcome["item_id"])
            return None if seen == selected else "backlog outcomes omit a selected item"
        required = {"alternatives", "selected_design", "complexity_rationale", "architecture_delta", "risks"}
        if not isinstance(content, dict) or set(content) != required:
            return "backlog architecture revision must contain exactly the required delta fields"
        if not isinstance(content["selected_design"], str) or not content["selected_design"].strip():
            return "backlog architecture selected_design must be nonempty"
        if not isinstance(content["complexity_rationale"], str) or not content["complexity_rationale"].strip():
            return "backlog architecture complexity_rationale must be nonempty"
        for name in required - {"selected_design", "complexity_rationale"}:
            if not isinstance(content[name], list) or any(not isinstance(item, str) or not item.strip() for item in content[name]):
                return f"backlog architecture field {name!r} must be an array of nonempty strings"
        return None

    def _load_backlog_cycle(self) -> dict[str, Any]:
        value = read_json(self.backlog_cycle_path)
        required = {"version", "phase", "prior_epoch_id", "selection", "revisions", "approval", "materialization"}
        if set(value) != required or value.get("version") != 1 or value.get("phase") not in BACKLOG_CYCLE_PHASES:
            raise SupervisorError("backlog-cycle state is malformed or has an unsupported version")
        selection = value.get("selection")
        if not isinstance(selection, dict) or set(selection) != {"digest", "items"} or not re.fullmatch(r"[0-9a-f]{64}", str(selection.get("digest"))):
            raise SupervisorError("backlog selection identity is malformed")
        items = selection.get("items")
        if not isinstance(items, list) or not items:
            raise SupervisorError("backlog selection must be a nonempty bounded list")
        ids: set[str] = set()
        for item in items:
            if not isinstance(item, dict) or set(item) != {"id", "source", "source_digest", "summary"}:
                raise SupervisorError("backlog selection item is malformed")
            if not isinstance(item["id"], str) or not item["id"].strip() or item["id"] in ids:
                raise SupervisorError("backlog selection item identifiers must be unique and nonempty")
            if not isinstance(item["source"], str) or not isinstance(item["summary"], str) or not item["summary"].strip() or not re.fullmatch(r"[0-9a-f]{64}", str(item["source_digest"])):
                raise SupervisorError("backlog selection item lineage is malformed")
            source = Path(item["source"])
            if source.is_absolute() or ".." in source.parts or not (self.root / source).is_file() or hashlib.sha256((self.root / source).read_bytes()).hexdigest() != item["source_digest"]:
                raise SupervisorError("backlog source changed after selection; begin a new bounded review")
            ids.add(item["id"])
        if content_checksum(items) != selection["digest"]:
            raise SupervisorError("backlog selection was changed after review began")
        revisions = value.get("revisions")
        if not isinstance(revisions, list):
            raise SupervisorError("backlog revision lineage is malformed")
        last_requirements = None
        last_architecture = None
        for revision in revisions:
            if not isinstance(revision, dict) or set(revision) != {"kind", "digest", "parent_digest", "selection_digest", "artifact"}:
                raise SupervisorError("backlog revision identity is malformed")
            if revision.get("kind") not in {"requirements", "architecture"} or revision.get("selection_digest") != selection["digest"]:
                raise SupervisorError("backlog revision kind or selection identity is malformed")
            proposal = read_json(self._backlog_cycle_artifact(revision["artifact"]))
            if content_checksum(proposal) != revision.get("digest") or proposal.get("kind") != revision["kind"]:
                raise SupervisorError("backlog revision artifact was changed or does not match its digest")
            expected = selection["digest"] if revision["kind"] == "requirements" else last_requirements
            if revision.get("parent_digest") != expected:
                raise SupervisorError("backlog revision lineage is broken")
            error = self._backlog_content_error(revision["kind"], proposal.get("content"), ids)
            if error:
                raise SupervisorError(error)
            if revision["kind"] == "requirements": last_requirements = revision["digest"]
            else: last_architecture = revision["digest"]
        approval = value.get("approval")
        if approval is not None and (
            not isinstance(approval, dict) or set(approval) != {"requirements_digest", "architecture_digest"}
            or approval.get("requirements_digest") != last_requirements
            or approval.get("architecture_digest") not in ({None, last_architecture} if last_architecture is not None else {None})
        ):
            raise SupervisorError("backlog approval does not name the exact current revisions")
        if value["phase"] == "READY_EPOCH" and (approval is None or not isinstance(value.get("materialization"), dict)):
            raise SupervisorError("ready backlog epoch requires exact approval and materialization evidence")
        return value

    def begin_backlog_cycle(self, selection_path: Path) -> dict[str, Any]:
        state = self.load_state()
        if state.get("version") != STATE_VERSION or state.get("phase") != "PLAN_COMPLETED":
            raise SupervisorError("backlog intake requires a completed immutable plan epoch")
        if self.backlog_cycle_path.exists():
            raise SupervisorError("a backlog cycle already exists; resume or materialize its recorded review")
        raw = read_json(selection_path.expanduser().resolve())
        if set(raw) != {"version", "items"} or raw.get("version") != 1 or not isinstance(raw.get("items"), list) or not raw["items"]:
            raise SupervisorError("backlog selection must be a version 1 nonempty items object")
        items = []
        for supplied in raw["items"]:
            if not isinstance(supplied, dict) or set(supplied) != {"id", "source", "summary"}:
                raise SupervisorError("backlog selection items must contain id, source, and summary")
            if not all(isinstance(supplied.get(key), str) and supplied[key].strip() for key in ("id", "source", "summary")):
                raise SupervisorError("backlog selection item id, source, and summary must be nonempty strings")
            source = Path(supplied["source"])
            if source.is_absolute() or ".." in source.parts or not (self.root / source).is_file():
                raise SupervisorError("backlog selection source must be an existing safe repository-relative file")
            items.append({**supplied, "source_digest": hashlib.sha256((self.root / source).read_bytes()).hexdigest()})
        if len({item["id"] for item in items}) != len(items):
            raise SupervisorError("backlog selection item identifiers must be unique")
        cycle = {"version": 1, "phase": "BACKLOG_REVIEW", "prior_epoch_id": self._current_epoch(state)["epoch_id"],
                 "selection": {"digest": content_checksum(items), "items": items}, "revisions": [], "approval": None, "materialization": None}
        atomic_write_json(self.backlog_cycle_path, cycle)
        return cycle

    def submit_backlog_revision(self, proposal_path: Path) -> dict[str, Any]:
        cycle = self._load_backlog_cycle()
        if cycle["phase"] not in {"BACKLOG_REVIEW", "ARCHITECTURE_REVIEW", "APPROVAL_WAIT"}:
            raise SupervisorError("backlog proposals are closed after a ready epoch")
        proposal = read_json(proposal_path.expanduser().resolve())
        expected_kind = "architecture" if cycle["phase"] == "ARCHITECTURE_REVIEW" else "requirements"
        if set(proposal) != {"version", "kind", "selection_digest", "parent_revision_digest", "content"} or proposal.get("version") != 1 or proposal.get("kind") != expected_kind:
            raise SupervisorError(f"backlog {expected_kind} review requires a matching version 1 proposal")
        if proposal.get("selection_digest") != cycle["selection"]["digest"]:
            raise SupervisorError("backlog proposal does not name the bounded selected scope")
        previous = cycle["revisions"][-1] if cycle["revisions"] else None
        expected_parent = cycle["selection"]["digest"] if expected_kind == "requirements" else cycle["approval"]["requirements_digest"]
        if proposal.get("parent_revision_digest") != expected_parent:
            raise SupervisorError("backlog proposal parent does not match reviewed lineage")
        error = self._backlog_content_error(expected_kind, proposal.get("content"), {item["id"] for item in cycle["selection"]["items"]})
        if error: raise SupervisorError(error)
        digest = content_checksum(proposal)
        if previous and previous.get("digest") == digest: return cycle
        artifact = f"revisions/{digest}.json"
        self._write_cold_start_bytes(self._backlog_cycle_artifact(artifact), canonical_json_bytes(proposal))
        cycle["revisions"].append({"kind": expected_kind, "digest": digest, "parent_digest": expected_parent, "selection_digest": cycle["selection"]["digest"], "artifact": artifact})
        # A new requirements revision changes scope analysis and invalidates all
        # approvals.  An architecture revision remains explicitly rooted in the
        # already approved requirements version, so retain only that identity.
        cycle["approval"] = (
            {"requirements_digest": expected_parent, "architecture_digest": None}
            if expected_kind == "architecture" else None
        )
        cycle["phase"] = "APPROVAL_WAIT"
        atomic_write_json(self.backlog_cycle_path, cycle)
        return cycle

    def approve_backlog_requirements(self, requirements_digest: str) -> dict[str, Any]:
        cycle = self._load_backlog_cycle()
        revision = cycle["revisions"][-1] if cycle["revisions"] else None
        if cycle["phase"] != "APPROVAL_WAIT" or not isinstance(revision, dict) or revision.get("kind") != "requirements" or revision.get("digest") != requirements_digest:
            raise SupervisorError("backlog requirements approval must name the exact current requirements revision")
        cycle["approval"] = {"requirements_digest": requirements_digest, "architecture_digest": None}
        cycle["phase"] = "ARCHITECTURE_REVIEW"
        atomic_write_json(self.backlog_cycle_path, cycle)
        return cycle

    def approve_backlog_architecture(self, requirements_digest: str, architecture_digest: str) -> dict[str, Any]:
        cycle = self._load_backlog_cycle()
        revision = cycle["revisions"][-1] if cycle["revisions"] else None
        approval = cycle.get("approval")
        if cycle["phase"] != "APPROVAL_WAIT" or not isinstance(approval, dict) or approval.get("requirements_digest") != requirements_digest or not isinstance(revision, dict) or revision.get("kind") != "architecture" or revision.get("digest") != architecture_digest:
            raise SupervisorError("backlog architecture approval must name exact requirements and architecture revisions")
        cycle["approval"] = {"requirements_digest": requirements_digest, "architecture_digest": architecture_digest}
        atomic_write_json(self.backlog_cycle_path, cycle)
        return cycle

    def materialize_backlog_epoch(self, plan_source: Path, index_source: Path, tickets_directory: Path, lineage_path: Path) -> dict[str, Any]:
        """Create a new immutable execution frontier only after exact approval."""
        cycle = self._load_backlog_cycle()
        approval = cycle.get("approval")
        if cycle["phase"] != "APPROVAL_WAIT" or not isinstance(approval, dict) or not isinstance(approval.get("architecture_digest"), str):
            raise SupervisorError("backlog epoch materialization requires exact approved requirements and architecture revisions")
        state = self.load_state()
        if state.get("phase") != "PLAN_COMPLETED" or self._current_epoch(state)["epoch_id"] != cycle["prior_epoch_id"]:
            raise SupervisorError("backlog epoch materialization requires the unchanged completed source epoch")
        plan_bytes = plan_source.expanduser().resolve().read_bytes()
        index_bytes = index_source.expanduser().resolve().read_bytes()
        if not plan_bytes or not index_bytes or not tickets_directory.is_dir():
            raise SupervisorError("backlog epoch requires nonempty plan/index sources and a ticket directory")
        tickets = self._parse_plan_tickets(plan_bytes.decode("utf-8"))
        lineage = read_json(lineage_path.expanduser().resolve())
        if set(lineage) != {"version", "ticket_sources"} or lineage.get("version") != 1 or not isinstance(lineage.get("ticket_sources"), dict) or set(lineage["ticket_sources"]) != set(tickets):
            raise SupervisorError("backlog ticket lineage must map every new plan ticket exactly once")
        requirements_revision = next((item for item in reversed(cycle["revisions"]) if item["kind"] == "requirements"), None)
        if requirements_revision is None:
            raise SupervisorError("backlog materialization has no reviewed requirements disposition")
        accepted = {
            outcome["item_id"] for outcome in read_json(
                self._backlog_cycle_artifact(requirements_revision["artifact"])
            )["content"]["outcomes"] if outcome["disposition"] == "accepted"
        }
        for ticket, sources in lineage["ticket_sources"].items():
            if not isinstance(sources, list) or not sources or any(source not in accepted for source in sources):
                raise SupervisorError("every new ticket must have lineage only to accepted selected backlog items")
            source_ticket = tickets_directory / f"{ticket[1:]}"  # accept the established 06-name prefix convention below
            matches = list(tickets_directory.glob(f"{ticket[1:]}-*.md"))
            if source_ticket.exists() or len(matches) != 1:
                raise SupervisorError(f"backlog ticket source directory must contain exactly one {ticket} ticket file")
        epoch_id = uuid.uuid4().hex
        base = f"{epoch_id}"
        self._write_cold_start_bytes(self._backlog_cycle_artifact(f"{base}/implementation-plan.md"), plan_bytes)
        self._write_cold_start_bytes(self._backlog_cycle_artifact(f"{base}/requirements-index.md"), index_bytes)
        for ticket in tickets:
            source = next(tickets_directory.glob(f"{ticket[1:]}-*.md"))
            self._write_cold_start_bytes(self._backlog_cycle_artifact(f"{base}/tickets/{source.name}"), source.read_bytes())
        materialization = {"epoch_id": epoch_id, "plan": f"{base}/implementation-plan.md", "index": f"{base}/requirements-index.md", "tickets": f"{base}/tickets", "ticket_sources": lineage["ticket_sources"], "plan_digest": hashlib.sha256(plan_bytes).hexdigest(), "index_digest": hashlib.sha256(index_bytes).hexdigest()}
        # Do not change either completed epoch; append a new linked epoch and
        # make it ready only after all immutable artifacts have been written.
        state["plan_epochs"].append({"epoch_id": epoch_id, "prior_epoch_id": cycle["prior_epoch_id"], "created_at": isoformat(self.now()), "plan_digest": materialization["plan_digest"], "tickets": tickets, "completion": None})
        state["current_plan_epoch_id"] = epoch_id
        state["completed_tickets"] = []
        self.transition(state, "READY", f"Approved backlog epoch {epoch_id} is ready; no implementation was started.", current_ticket=tickets[0], active_run=None, pending_commit=None, starting_head=None)
        cycle["materialization"] = materialization
        cycle["phase"] = "READY_EPOCH"
        atomic_write_json(self.backlog_cycle_path, cycle)
        return cycle

    def backlog_cycle_status(self) -> dict[str, Any]:
        cycle = self._load_backlog_cycle()
        action = {
            "BACKLOG_REVIEW": "submit a bounded requirements/dependency/readiness analysis",
            "ARCHITECTURE_REVIEW": "submit an architecture-delta correction for the approved requirements revision",
            "APPROVAL_WAIT": "supply the exact version-bound human approval required by the latest revision",
            "READY_EPOCH": "the approved next epoch is ready; implementation remains separately controlled",
        }[cycle["phase"]]
        return {**cycle, "required_human_action": action}

    # An improvement is intentionally not a backlog item and cannot become
    # executable merely because it was requested.  This separate, append-only
    # review record makes feature work, defect repair, and engine development
    # distinguishable in both state and audit evidence.
    @property
    def improvement_path(self) -> Path:
        return self.runtime / IMPROVEMENT_STATE_NAME

    def _improvement_artifact(self, request_id: str, relative: str) -> Path:
        candidate = Path(relative)
        if not re.fullmatch(r"[0-9a-f]{32}", request_id) or candidate.is_absolute() or ".." in candidate.parts:
            raise SupervisorError("improvement artifact path is unsafe")
        return self.runtime / IMPROVEMENT_DIRECTORY / request_id / candidate

    @staticmethod
    def _improvement_capability(kind: str) -> str:
        if kind not in IMPROVEMENT_KINDS:
            raise SupervisorError("improvement kind must be user_improvement or self_development")
        return "self_modification" if kind == "self_development" else "user_requested_modification"

    def _append_improvement_audit(self, action: str, record: dict[str, Any]) -> None:
        state = self.load_state()
        state.setdefault("improvement_audit", []).append({
            "at": isoformat(self.now()), "action": action,
            "request_id": record["request_id"], "kind": record["kind"], "phase": record["phase"],
        })
        self.save_state(state)

    def _load_improvement(self) -> dict[str, Any]:
        record = read_json(self.improvement_path)
        required = {"version", "request_id", "kind", "trigger", "description", "request_digest", "phase", "revisions", "approval", "materialization", "successor"}
        if set(record) != required or record.get("version") != 1 or record.get("kind") not in IMPROVEMENT_KINDS or record.get("phase") not in IMPROVEMENT_PHASES:
            raise SupervisorError("improvement state is malformed or has an unsupported version")
        if not isinstance(record.get("trigger"), str) or not record["trigger"].strip() or not isinstance(record.get("description"), str) or not record["description"].strip():
            raise SupervisorError("improvement request lacks an explicit user trigger or description")
        request_material = {"kind": record["kind"], "trigger": record["trigger"], "description": record["description"]}
        if record.get("request_digest") != content_checksum(request_material):
            raise SupervisorError("improvement request identity was changed")
        revisions = record.get("revisions")
        if not isinstance(revisions, list):
            raise SupervisorError("improvement revision lineage is malformed")
        parent = record["request_digest"]
        for revision in revisions:
            if not isinstance(revision, dict) or set(revision) != {"digest", "parent_digest", "artifact"} or revision.get("parent_digest") != parent:
                raise SupervisorError("improvement architecture correction lineage is broken")
            proposal = read_json(self._improvement_artifact(record["request_id"], revision.get("artifact", "")))
            if content_checksum(proposal) != revision.get("digest"):
                raise SupervisorError("improvement architecture artifact was changed")
            parent = revision["digest"]
        approval = record.get("approval")
        if approval is not None and approval != parent:
            raise SupervisorError("improvement approval must name the exact current architecture revision")
        if record["phase"] in {"BOUNDED_PLAN_READY", "SUCCESSOR_STAGED"} and (approval is None or not isinstance(record.get("materialization"), dict)):
            raise SupervisorError("bounded improvement lacks approval or materialization evidence")
        return record

    def request_improvement(self, kind: str, trigger: str, description: str) -> dict[str, Any]:
        capability = self._improvement_capability(kind)
        self.require_capability(capability)
        if self.improvement_path.exists():
            raise SupervisorError("an improvement review already exists; inspect or finish its recorded workflow")
        if not trigger.strip() or not description.strip():
            raise SupervisorError("improvement requires an explicit nonempty user trigger and description")
        if len(description) > self.policy["improvement"]["max_description_characters"]:
            raise SupervisorError("improvement description exceeds the configured bounded policy")
        material = {"kind": kind, "trigger": trigger.strip(), "description": description.strip()}
        record = {"version": 1, "request_id": uuid.uuid4().hex, **material,
                  "request_digest": content_checksum(material), "phase": "ARCHITECTURE_IMPACT",
                  "revisions": [], "approval": None, "materialization": None, "successor": None}
        atomic_write_json(self.improvement_path, record)
        self._append_improvement_audit("explicit_user_trigger", record)
        return record

    def submit_improvement_architecture(self, proposal_path: Path) -> dict[str, Any]:
        record = self._load_improvement()
        self.require_capability(self._improvement_capability(record["kind"]))
        if record["phase"] not in {"ARCHITECTURE_IMPACT", "APPROVAL_WAIT"}:
            raise SupervisorError("improvement architecture corrections are closed after materialization or escalation")
        proposal = read_json(proposal_path.expanduser().resolve())
        required = {"version", "kind", "request_digest", "parent_revision_digest", "content"}
        if set(proposal) != required or proposal.get("version") != 1 or proposal.get("kind") != "architecture_impact" or proposal.get("request_digest") != record["request_digest"]:
            raise SupervisorError("improvement architecture review requires a matching version 1 impact proposal")
        parent = record["revisions"][-1]["digest"] if record["revisions"] else record["request_digest"]
        if proposal.get("parent_revision_digest") != parent:
            raise SupervisorError("improvement correction must name the immediately preceding lineage revision")
        content = proposal.get("content")
        required_content = {"alternatives", "selected_design", "complexity_rationale", "architecture_delta", "risks"}
        if not isinstance(content, dict) or set(content) != required_content or not all(isinstance(content.get(name), list) and content[name] and all(isinstance(item, str) and item.strip() for item in content[name]) for name in ("alternatives", "architecture_delta", "risks")) or not all(isinstance(content.get(name), str) and content[name].strip() for name in ("selected_design", "complexity_rationale")):
            raise SupervisorError("improvement architecture impact content is malformed")
        digest = content_checksum(proposal)
        artifact = f"architecture/{digest}.json"
        self._write_cold_start_bytes(self._improvement_artifact(record["request_id"], artifact), canonical_json_bytes(proposal))
        record["revisions"].append({"digest": digest, "parent_digest": parent, "artifact": artifact})
        record["approval"] = None
        record["phase"] = "APPROVAL_WAIT"
        atomic_write_json(self.improvement_path, record)
        self._append_improvement_audit("architecture_impact_corrected", record)
        return record

    def approve_improvement_architecture(self, revision_digest: str) -> dict[str, Any]:
        record = self._load_improvement()
        self.require_capability(self._improvement_capability(record["kind"]))
        if record["phase"] != "APPROVAL_WAIT" or not record["revisions"] or record["revisions"][-1]["digest"] != revision_digest:
            raise SupervisorError("improvement approval must name the exact current architecture impact revision")
        record["approval"] = revision_digest
        atomic_write_json(self.improvement_path, record)
        self._append_improvement_audit("architecture_approved", record)
        return record

    def materialize_improvement_plan(self, plan_source: Path, tickets_directory: Path) -> dict[str, Any]:
        record = self._load_improvement()
        self.require_capability(self._improvement_capability(record["kind"]))
        if record["phase"] != "APPROVAL_WAIT" or record.get("approval") is None:
            raise SupervisorError("bounded improvement plan requires exact human architecture approval")
        plan_bytes = plan_source.expanduser().resolve().read_bytes()
        tickets = self._parse_plan_tickets(plan_bytes.decode("utf-8"))
        if len(tickets) > self.policy["improvement"]["max_tickets"]:
            record["phase"] = "ESCALATED_NORMAL_CYCLE"
            atomic_write_json(self.improvement_path, record)
            self._append_improvement_audit("escalated_to_normal_cycle", record)
            return record
        if not tickets_directory.is_dir() or any(len(list(tickets_directory.glob(f"{ticket[1:]}-*.md"))) != 1 for ticket in tickets):
            raise SupervisorError("bounded improvement requires exactly one ticket file for every planned ticket")
        base = f"plans/{hashlib.sha256(plan_bytes).hexdigest()}/"
        self._write_cold_start_bytes(self._improvement_artifact(record["request_id"], base + "implementation-plan.md"), plan_bytes)
        for ticket in tickets:
            source = next(tickets_directory.glob(f"{ticket[1:]}-*.md"))
            self._write_cold_start_bytes(self._improvement_artifact(record["request_id"], base + "tickets/" + source.name), source.read_bytes())
        record["materialization"] = {"plan": base + "implementation-plan.md", "tickets": tickets, "ticket_directory": base + "tickets", "plan_digest": hashlib.sha256(plan_bytes).hexdigest()}
        record["phase"] = "BOUNDED_PLAN_READY"
        atomic_write_json(self.improvement_path, record)
        self._append_improvement_audit("bounded_plan_and_scope_validated", record)
        return record

    def stage_successor(self) -> dict[str, Any]:
        record = self._load_improvement()
        if record["kind"] != "self_development":
            raise SupervisorError("only self_development may stage a successor generation")
        self.require_capability("self_modification")
        if record["phase"] != "BOUNDED_PLAN_READY":
            raise SupervisorError("successor staging requires an approved bounded self-development plan")
        target = self.root / self.policy["improvement"]["successor_directory"] / record["request_id"]
        active = self.assets_dir.resolve()
        if target.exists() or target.resolve() == active:
            raise SupervisorError("successor target is not an isolated new generation")
        shutil.copytree(active, target, ignore=shutil.ignore_patterns(".git", ".dev-supervisor", "__pycache__", "*.pyc"))
        record["successor"] = {"path": str(target.relative_to(self.root)), "base_engine": str(active), "base_digest": self._directory_digest(target), "activation": "forbidden_pending_t10_t11_quiescent_handoff"}
        record["phase"] = "SUCCESSOR_STAGED"
        atomic_write_json(self.improvement_path, record)
        self._append_improvement_audit("successor_staged_in_isolation", record)
        return record

    @staticmethod
    def _directory_digest(path: Path) -> str:
        digest = hashlib.sha256()
        # Git metadata and Python bytecode are host/process by-products, never
        # release material.  Including either would make an otherwise immutable
        # checkout appear to change simply by inspecting or executing it.
        for child in sorted(
            item for item in path.rglob("*") if item.is_file()
            and ".git" not in item.relative_to(path).parts
            and "__pycache__" not in item.relative_to(path).parts
            and item.suffix != ".pyc"
        ):
            digest.update(child.relative_to(path).as_posix().encode() + b"\0")
            digest.update(child.read_bytes())
        return digest.hexdigest()

    def improvement_status(self) -> dict[str, Any]:
        if not self.improvement_path.exists():
            return {"phase": "ABSENT", "required_human_action": "explicitly request an enabled improvement; status is read-only"}
        record = self._load_improvement()
        actions = {
            "ARCHITECTURE_IMPACT": "submit an architecture impact review rooted in the explicit trigger",
            "APPROVAL_WAIT": "approve the exact current architecture impact revision or submit a correction",
            "BOUNDED_PLAN_READY": "stage an isolated successor only for self-development; implementation remains separately controlled",
            "SUCCESSOR_STAGED": "perform no activation here; T10/T11 own the later quiescent handoff",
            "ESCALATED_NORMAL_CYCLE": "start a normal approved development cycle; do not split scope automatically",
        }
        return {**record, "required_human_action": actions[record["phase"]]}

    def initial_state(self) -> dict[str, Any]:
        self.git.require_repository()
        epoch = self._new_plan_epoch()
        return {
            "version": STATE_VERSION,
            "phase": "READY",
            "current_ticket": self.policy["bootstrap_ticket"],
            "completed_tickets": list(self.policy["initial_completed_tickets"]),
            "starting_head": None,
            "active_run": None,
            "blocked_report": None,
            "architecture_resolution": None,
            "message": "Initialized; quota must be set before the first model invocation.",
            "periodic_checkpoint": {
                "baseline_at": isoformat(self.now()),
                "active_runtime_seconds": 0.0,
                "completed_tickets": 0,
                "model_invocations": 0,
            },
            "last_completed_result": None,
            "quota_consumptions": [],
            "diagnostic": None,
            "plan_epochs": [epoch],
            "current_plan_epoch_id": epoch["epoch_id"],
            "history": [],
            "pending_push": None,
            "updated_at": isoformat(self.now()),
        }

    def _plan_digest(self) -> str:
        """Return an immutable identity for the currently approved plan bytes."""
        try:
            contents = (self.root / self.policy["implementation_plan"]).read_bytes()
        except OSError as error:
            raise SupervisorError("cannot read implementation plan for plan epoch") from error
        return hashlib.sha256(contents).hexdigest()

    def _new_plan_epoch(self, *, prior_epoch_id: str | None = None) -> dict[str, Any]:
        tickets = self._plan_tickets()
        return {
            "epoch_id": uuid.uuid4().hex,
            "prior_epoch_id": prior_epoch_id,
            "created_at": isoformat(self.now()),
            "plan_digest": self._plan_digest(),
            "tickets": list(tickets),
            "completion": None,
        }

    def _legacy_state_migration_report(self, state: dict[str, Any]) -> dict[str, Any]:
        """Classify a v4 state before a v5 epoch is ever written.

        A legacy state that already names every plan ticket as complete has no
        durable final-commit evidence.  Guessing whether its final commit was
        reconciled would recreate the 1.x failure, so it is deliberately not
        migrated.
        """
        plan = self._plan_tickets()
        completed = state.get("completed_tickets")
        current = state.get("current_ticket")
        phase = state.get("phase")
        reason: str | None = None
        if not isinstance(completed, list) or any(not isinstance(item, str) for item in completed):
            reason = "completed-ticket history is malformed"
        elif not isinstance(current, str) or current not in plan:
            reason = "current ticket is absent from the authoritative plan"
        elif any(item not in plan for item in completed):
            reason = "completed-ticket history contains tickets absent from the authoritative plan"
        elif set(plan).issubset(completed):
            reason = "legacy state records every plan ticket complete without v5 final-commit evidence"
        elif current == plan[-1] and phase == "COMMITTING":
            reason = "legacy final-ticket commit is pending without v5 epoch-completion evidence"
        elif phase == "PLAN_COMPLETED":
            reason = "PLAN_COMPLETED requires the v5 epoch-completion schema"
        if reason is not None:
            return {
                "status": "unsupported", "from_version": state.get("version", 4),
                "to_version": STATE_VERSION, "reason": reason, "writes_required": False,
            }
        return {
            "status": "supported", "from_version": state.get("version", 4),
            "to_version": STATE_VERSION, "writes_required": True,
        }

    def _migrate_state_v4(self, state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        report = self._legacy_state_migration_report(state)
        if report["status"] != "supported":
            raise SupervisorError("unsupported legacy state migration report: " + report["reason"])
        migrated = deepcopy(state)
        epoch = self._new_plan_epoch()
        migrated.update({
            "version": STATE_VERSION,
            "plan_epochs": [epoch],
            "current_plan_epoch_id": epoch["epoch_id"],
            "state_migration": report,
        })
        return migrated, report

    def _state_predecessor_path(self, checksum: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise SupervisorError("state predecessor checksum is malformed")
        return self.runtime / STATE_PREDECESSORS_DIRECTORY / f"{checksum}.json"

    def _validate_state_v7(self, state: dict[str, Any]) -> str | None:
        cutover = state.get("legacy_cutover")
        if cutover is not None:
            if not isinstance(cutover, dict) or set(cutover) != {"version", "checksum", "archive"}:
                return "legacy cutover predecessor linkage is missing or malformed"
            checksum, archive = cutover.get("checksum"), cutover.get("archive")
            if cutover.get("version") != 1 or not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
                return "legacy cutover predecessor identity is unsupported or malformed"
            if archive != f"{LEGACY_CUTOVER_ARCHIVES_DIRECTORY}/{checksum}.json":
                return "legacy cutover predecessor archive link is malformed"
        predecessor = state.get("state_predecessor")
        if predecessor is None:
            # A freshly initialized v7 runtime has no converted predecessor.
            return None
        required = {"version", "checksum", "archive"}
        if not isinstance(predecessor, dict) or set(predecessor) != required:
            return "versioned state predecessor linkage is missing or malformed"
        version, checksum, archive = predecessor.get("version"), predecessor.get("checksum"), predecessor.get("archive")
        if version != 6 or not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            return "versioned state predecessor identity is unsupported or malformed"
        if archive != f"{STATE_PREDECESSORS_DIRECTORY}/{checksum}.json":
            return "versioned state predecessor archive link is malformed"
        events = state.get("audit_events")
        if events is not None:
            predecessor_checksum: str | None = None
            if not isinstance(events, list):
                return "versioned state audit events are malformed"
            for event in events:
                if not isinstance(event, dict) or set(event) != {"version", "event_id", "predecessor_checksum", "kind", "payload"}:
                    return "versioned state audit event shape is malformed"
                expected = audit_event(event.get("kind"), event.get("payload"), predecessor_checksum)
                if event != expected:
                    return "versioned state audit event checksum or predecessor link is broken"
                predecessor_checksum = event["event_id"]
        return None

    def state_migration_dry_run(self) -> dict[str, Any]:
        """Validate exactly one supported conversion without changing runtime files."""
        if not self.state_path.exists():
            raise SupervisorError("state migration requires an existing state snapshot")
        state = read_json(self.state_path)
        version = state.get("version")
        if version == STATE_VERSION:
            error = self._validate_state_v7(state)
            if error is not None:
                raise SupervisorError(error)
            return {
                "status": "already_applied", "from_version": STATE_VERSION,
                "to_version": STATE_VERSION, "source_checksum": content_checksum(state),
                "target_checksum": content_checksum(state), "writes_required": False,
            }
        if version != 6:
            raise SupervisorError(f"unsupported state migration source version: {version!r}; supported: 6 -> 7")
        error = self._epoch_error(state)
        if error is not None:
            raise SupervisorError("state migration source is malformed: " + error)
        source_checksum = content_checksum(state)
        migrated = deepcopy(state)
        migrated["version"] = STATE_VERSION
        migrated["pending_push"] = None
        migrated["state_predecessor"] = {
            "version": 6,
            "checksum": source_checksum,
            "archive": f"{STATE_PREDECESSORS_DIRECTORY}/{source_checksum}.json",
        }
        migrated["audit_events"] = [audit_event("state_migrated", {
            "from_version": 6, "to_version": STATE_VERSION, "source_checksum": source_checksum,
        })]
        return {
            "status": "supported", "from_version": 6, "to_version": STATE_VERSION,
            "source_checksum": source_checksum, "target_checksum": content_checksum(migrated),
            "archive": migrated["state_predecessor"]["archive"], "writes_required": True,
        }

    def apply_state_migration(self) -> dict[str, Any]:
        """Apply the dry-run transformation after preserving its exact predecessor."""
        report = self.state_migration_dry_run()
        if not report["writes_required"]:
            return report
        source = read_json(self.state_path)
        # Recompute with the same routine so dry-run and apply cannot diverge.
        if content_checksum(source) != report["source_checksum"]:
            raise SupervisorError("state changed after migration validation; refusing to rewrite it")
        archive = self._state_predecessor_path(report["source_checksum"])
        if archive.exists():
            archived = read_json(archive)
            if content_checksum(archived) != report["source_checksum"]:
                raise SupervisorError("existing predecessor archive checksum disagrees with source state")
        else:
            atomic_write_json(archive, source)
        # The archive-first order is recoverable: a retry after an interrupted state
        # write validates and reuses the immutable archive.
        migrated = deepcopy(source)
        migrated["version"] = STATE_VERSION
        migrated["pending_push"] = None
        migrated["state_predecessor"] = {
            "version": 6, "checksum": report["source_checksum"], "archive": report["archive"],
        }
        migrated["audit_events"] = [audit_event("state_migrated", {
            "from_version": 6, "to_version": STATE_VERSION, "source_checksum": report["source_checksum"],
        })]
        if content_checksum(migrated) != report["target_checksum"]:
            raise SupervisorError("state migration transformation was not deterministic")
        atomic_write_json(self.state_path, migrated)
        return report

    def rollback_state_migration(self) -> dict[str, Any]:
        """Restore the checksummed v5 predecessor; no source version is guessed."""
        state = read_json(self.state_path)
        if state.get("version") != STATE_VERSION:
            raise SupervisorError("state rollback only supports version 7")
        error = self._validate_state_v7(state)
        if error is not None:
            raise SupervisorError(error)
        predecessor = state["state_predecessor"]
        archive = self._state_predecessor_path(predecessor["checksum"])
        archived = read_json(archive)
        if archived.get("version") != predecessor["version"] or content_checksum(archived) != predecessor["checksum"]:
            raise SupervisorError("state predecessor archive is missing, malformed, or has a checksum mismatch")
        atomic_write_json(self.state_path, archived)
        return {
            "status": "rolled_back", "from_version": STATE_VERSION,
            "to_version": predecessor["version"], "source_checksum": content_checksum(state),
            "target_checksum": predecessor["checksum"], "writes_required": True,
        }

    def _epoch_error(self, state: dict[str, Any]) -> str | None:
        epochs = state.get("plan_epochs")
        current = state.get("current_plan_epoch_id")
        if not isinstance(epochs, list) or not epochs or not isinstance(current, str):
            return "plan epoch audit is missing"
        required = {"epoch_id", "prior_epoch_id", "created_at", "plan_digest", "tickets", "completion"}
        previous_id: str | None = None
        identifiers: set[str] = set()
        for epoch in epochs:
            if (
                not isinstance(epoch, dict)
                or set(epoch) != required
                or not isinstance(epoch.get("epoch_id"), str)
                or not re.fullmatch(r"[0-9a-f]{32}", epoch["epoch_id"])
                or epoch["epoch_id"] in identifiers
                or epoch.get("prior_epoch_id") != previous_id
                or not isinstance(epoch.get("plan_digest"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", epoch["plan_digest"])
                or not isinstance(epoch.get("tickets"), list)
                or not epoch["tickets"]
                or any(not isinstance(ticket, str) or not ticket for ticket in epoch["tickets"])
            ):
                return "plan epoch history is malformed or its immutable prior link is broken"
            try:
                parse_datetime(epoch["created_at"])
            except SupervisorError:
                return "plan epoch creation timestamp is malformed"
            identifiers.add(epoch["epoch_id"])
            previous_id = epoch["epoch_id"]
        matches = [item for item in epochs if isinstance(item, dict) and item.get("epoch_id") == current]
        if len(matches) != 1:
            return "current plan epoch identity is missing or ambiguous"
        epoch = matches[0]
        if state.get("phase") == "PLAN_COMPLETED" and not isinstance(epoch.get("completion"), dict):
            return "completed plan epoch is missing final-commit evidence"
        return None

    def _current_epoch(self, state: dict[str, Any]) -> dict[str, Any]:
        error = self._epoch_error(state)
        if error is not None:
            raise SupervisorError(error)
        return next(item for item in state["plan_epochs"] if item["epoch_id"] == state["current_plan_epoch_id"])

    def load_state(self, *, read_only: bool = False) -> dict[str, Any]:
        if not self.state_path.exists():
            state = self.initial_state()
            if not read_only:
                self.save_state(state)
            return state
        state = read_json(self.state_path)
        # All legacy snapshots are inspection-only until the operator explicitly
        # invokes migration.  In particular, status and no-model resume cannot
        # mutate the T00 T30 HUMAN_GATE fixture.
        if state.get("version") != STATE_VERSION:
            if state.get("version") == 4 and state.get("phase") != "HUMAN_GATE":
                report = self._legacy_state_migration_report(state)
                if report["status"] != "supported":
                    raise SupervisorError("unsupported legacy state migration report: " + report["reason"])
            return state
        normalized = ["F" + item[2:] if item.startswith("TF") else item for item in state.get("completed_tickets", [])]
        changed = normalized != state.get("completed_tickets")
        if changed:
            state["completed_tickets"] = normalized
        if not isinstance(state.get("periodic_checkpoint"), dict):
            state["periodic_checkpoint"] = {
                "baseline_at": state.get("updated_at", isoformat(self.now())),
                "active_runtime_seconds": 0.0,
                "completed_tickets": 0,
                "model_invocations": 0,
            }
            changed = True
        state.setdefault("last_completed_result", None)
        if state.get("version") != STATE_VERSION:
            raise SupervisorError(f"unsupported supervisor state version: {state.get('version')!r}")
        epoch_error = self._epoch_error(state)
        if epoch_error is not None:
            raise SupervisorError(epoch_error)
        predecessor_error = self._validate_state_v7(state)
        if predecessor_error is not None:
            raise SupervisorError(predecessor_error)
        if changed and not read_only:
            self.save_state(state)
        return state

    def save_state(self, state: dict[str, Any]) -> None:
        if state.get("version") != STATE_VERSION:
            raise SupervisorError("legacy state is inspection-only; run state-migration-dry-run then state-migration-apply")
        # The binding check is immediately before every ordinary state write.
        # Thus a stale synchronized host fails closed before it can advance a
        # state requiring a newer engine, and a v2 controller additionally
        # needs host-local writer ownership (Git synchronization is no lease).
        if self.engine_binding_path.exists():
            binding = self._assert_engine_binding(state)
            self._assert_writer_lease(binding)
        state["updated_at"] = isoformat(self.now())
        atomic_write_json(self.state_path, state)

    def transition(self, state: dict[str, Any], phase: str, message: str, **values: Any) -> None:
        old = state.get("phase")
        state.update(values)
        state["phase"] = phase
        state["message"] = message
        state.setdefault("history", []).append({
            "at": isoformat(self.now()), "from": old, "to": phase, "message": message,
        })
        self.save_state(state)

    def _checkpoint_data(self, state: dict[str, Any]) -> dict[str, Any]:
        value = state.get("periodic_checkpoint")
        if not isinstance(value, dict):
            value = {}
            state["periodic_checkpoint"] = value
        value.setdefault("baseline_at", isoformat(self.now()))
        for key in ("active_runtime_seconds", "completed_tickets", "model_invocations"):
            candidate = value.get(key, 0)
            value[key] = candidate if isinstance(candidate, (int, float)) and candidate >= 0 else 0
        return value

    def _add_active_runtime(self, state: dict[str, Any], seconds: float) -> None:
        checkpoint = self._checkpoint_data(state)
        checkpoint["active_runtime_seconds"] += max(0.0, float(seconds))

    def _checkpoint_reasons(self, state: dict[str, Any]) -> list[str]:
        checkpoint = self._checkpoint_data(state)
        policy = self.policy["periodic_checkpoint"]
        reasons: list[str] = []
        if checkpoint["completed_tickets"] >= policy["max_completed_tickets"]:
            reasons.append(
                f"{checkpoint['completed_tickets']} completed tickets reached the "
                f"limit of {policy['max_completed_tickets']}"
            )
        if checkpoint["active_runtime_seconds"] >= policy["max_active_runtime_seconds"]:
            reasons.append(
                f"{format_duration(checkpoint['active_runtime_seconds'])} active runtime reached the "
                f"limit of {format_duration(policy['max_active_runtime_seconds'])}"
            )
        if checkpoint["model_invocations"] >= policy["max_model_invocations"]:
            reasons.append(
                f"{checkpoint['model_invocations']} model invocations reached the "
                f"limit of {policy['max_model_invocations']}"
            )
        return reasons

    def _maybe_periodic_gate(self, state: dict[str, Any], resume_phase: str) -> bool:
        reasons = self._checkpoint_reasons(state)
        if not reasons:
            return False
        message = "PERIODIC_CHECKPOINT: " + "; ".join(reasons)
        self.transition(
            state, "PERIODIC_CHECKPOINT", message,
            gate={
                "kind": "periodic", "reason": "PERIODIC_CHECKPOINT",
                "triggered_by": reasons, "resume_phase": resume_phase,
                "head": self.git.head(), "ticket": state["current_ticket"],
                "fingerprint": self.git.fingerprint(),
            },
        )
        self._emit(state["current_ticket"], "PERIODIC CHECKPOINT", "STOP · " + "; ".join(reasons))
        return True

    def _timing_history(self) -> tuple[dict[str, Any], str | None]:
        empty = {"version": 1, "model_invocations": [], "verification": [], "architecture_escalations": [], "tickets": []}
        if not self.timing_path.exists():
            return empty, None
        try:
            value = read_json(self.timing_path)
            for key in empty:
                if key == "version":
                    continue
                if not isinstance(value.get(key), list):
                    raise SupervisorError(f"timing history field {key} is not an array")
            return value, None
        except SupervisorError as error:
            return empty, str(error)

    def _record_timing(self, category: str, record: dict[str, Any]) -> None:
        history, error = self._timing_history()
        if error:
            atomic_write_text(self.runtime / "timing-history-error.log", error + "\n")
            history = {"version": 1, "model_invocations": [], "verification": [], "architecture_escalations": [], "tickets": []}
        history[category].append(record)
        atomic_write_json(self.timing_path, history)

    def status(self) -> dict[str, Any]:
        state = self.load_state(read_only=True)
        backlog_cycle = None
        if self.backlog_cycle_path.exists():
            backlog_cycle = self.backlog_cycle_status()
        try:
            quota = self.quota.snapshot()
        except SupervisorError:
            quota = None
        active = state.get("active_run") or {}
        epoch = None
        if state.get("version") == STATE_VERSION:
            epoch = self._current_epoch(state)
        try:
            plan = epoch["tickets"] if epoch is not None and epoch.get("prior_epoch_id") is not None else self._plan_tickets()
        except SupervisorError:
            plan = []
        completed = [ticket for ticket in plan if ticket in state.get("completed_tickets", [])]
        current = state["current_ticket"]
        upcoming: list[str] = []
        if state.get("phase") != "PLAN_COMPLETED" and current in plan:
            upcoming = plan[plan.index(current) + 1:plan.index(current) + 5]
        final_result = epoch.get("completion") if epoch is not None else None
        phase_roles = {
            "ARCHITECTURE_PENDING": "architecture",
            "DIAGNOSTIC_PENDING": "diagnostic",
            "DIAGNOSTIC_REVIEW": "diagnostic",
            "SUPERVISOR_REPAIR_PENDING": "supervisor_repair",
            "SUPERVISOR_REPAIR": "supervisor_repair",
        }
        role = state.get("pending_role") or phase_roles.get(state["phase"]) or active.get("role")
        if not role:
            role = "implementation"
        if role not in self.policy["models"]:
            role = "implementation"
        try:
            quota_status, quota_message = self.quota.evaluate(role, self.policy["quota"])
        except SupervisorError as error:
            quota_status, quota_message = "unknown", str(error)
        checkpoint = self._checkpoint_data(state)
        reasons = self._checkpoint_reasons(state)
        elapsed = self._current_run_elapsed(state, active)
        return {
            "phase": state["phase"],
            "backlog_cycle_phase": backlog_cycle["phase"] if backlog_cycle is not None else None,
            "backlog_cycle": backlog_cycle,
            "current_ticket": current,
            "completed_tickets": completed,
            "upcoming_tickets": upcoming,
            "message": state.get("message"),
            "starting_head": state.get("starting_head"),
            "active_run": active,
            "current_role": role,
            "current_model": self.policy["models"][role],
            "head": self.git.head(),
            "working_tree_clean": self.git.is_clean(),
            "working_tree_files": self.git.changed_files(),
            "quota": quota,
            "quota_status": quota_status,
            "quota_message": quota_message,
            "checkpoint": checkpoint,
            "checkpoint_due": reasons,
            "current_run_elapsed_seconds": elapsed,
            "last_completed_result": state.get("last_completed_result"),
            "plan_epoch": epoch,
            "current_frontier": {
                "current_ticket": current,
                "completed_tickets": completed,
                "remaining_tickets": [] if state.get("phase") == "PLAN_COMPLETED" else [
                    item for item in plan if item not in state.get("completed_tickets", [])
                ],
            },
            "final_result": final_result,
            "audit_evidence": {
                "plan_epochs": state.get("plan_epochs", []),
                "state_migration": state.get("state_migration"),
            },
            "effective_configuration": self.effective_configuration(),
            "next_actions": self._next_actions(state),
            "quiescent": state["phase"] in TERMINAL_STATES,
        }

    def _current_run_elapsed(self, state: dict[str, Any], active: dict[str, Any]) -> float:
        duration = active.get("duration_seconds")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
            return float(duration)
        started_at = active.get("started_at")
        finished_at = active.get("finished_at")
        if started_at and finished_at:
            try:
                return max(0.0, (parse_datetime(finished_at) - parse_datetime(started_at)).total_seconds())
            except SupervisorError:
                return 0.0
        invocation_active = (
            state.get("phase") in {"IMPLEMENTING", "ARCHITECTURE_REVIEW"}
            and active.get("invocation_completed") is not True
        )
        if invocation_active and started_at:
            try:
                return max(0.0, (self.now() - parse_datetime(started_at)).total_seconds())
            except SupervisorError:
                return 0.0
        return 0.0

    def _next_actions(self, state: dict[str, Any]) -> list[str]:
        ticket = state["current_ticket"]
        phase = state["phase"]
        if phase == "PLAN_COMPLETED":
            return ["plan epoch is complete and read-only", "obtain separate approval before creating a new epoch"]
        if phase == "MIGRATION_BLOCKED":
            return ["inspect the migration report; no model or state transition is authorized"]
        if phase in TERMINAL_STATES:
            if (
                phase == "PERIODIC_CHECKPOINT"
                and self._post_implementation_periodic_resume_error(state) is None
            ):
                return [
                    "resume the exact completed implementation checkpoint",
                    "./dev resume",
                    "continue with deterministic verification, scope, and commit",
                ]
            if phase == "HUMAN_GATE" and (state.get("gate") or {}).get("kind") == "evidence":
                actions = []
                if not (state.get("active_run") or {}).get("evidence_checks_passed"):
                    actions.extend([
                        "run deterministic evidence checks",
                        f"./dev evidence check --ticket {ticket}",
                    ])
                actions.extend([
                    "perform and record the owner live PASS/FAIL evidence",
                    './dev gate release --note "..."',
                    "./dev resume",
                ])
                return actions
            if phase in {"HUMAN_GATE", "PERIODIC_CHECKPOINT"}:
                return ["human reviews the gate", './dev gate release --note "..."', "./dev resume"]
            if phase == "INTERRUPTED":
                return ["inspect preserved run artifacts and working tree", "./dev resume"]
            if phase in QUOTA_STATES:
                return ["refresh or wait for trusted quota status", "./dev resume"]
            if phase == "REPORT_INVALID" and self._invalid_report_recovery_error(state) is not None:
                return ["operator must reconcile the invalid report state; automatic resume is unavailable"]
            if phase == "DIAGNOSTIC_FAILED" and self._diagnostic_failed_recovery_error(state) is not None:
                return ["operator must reconcile the failed diagnostic state; automatic resume is unavailable"]
            if phase == "SCOPE_BLOCKED" and self._scope_blocked_recovery_error(state) is not None:
                return ["operator must reconcile the scope checkpoint; automatic resume is unavailable"]
            if phase == "GIT_BLOCKED" and self._protected_snapshot_recovery_error(state) is None:
                return [
                    "inspect the preserved protected-scope review evidence",
                    "./dev recover-protected-snapshot",
                ]
            if phase == "VERIFICATION_FAILED" and self._failed_host_verification(
                state.get("active_run") or {}
            ) is None:
                return [
                    "inspect the preserved deterministic verification failure; automatic retry is unavailable",
                    "./dev recover-generic-verification-failure",
                ]
            return ["inspect the recorded diagnostic and preserved changes", "./dev resume when the documented condition is safe"]
        if phase == "VERIFYING":
            return ["finish deterministic verification", "scope gate", "commit if every gate passes", "quota/checkpoint gate", "advance ticket"]
        if phase == "SCOPE_PENDING":
            return ["scope gate", "commit if scope passes", "quota/checkpoint gate", "advance ticket"]
        if phase == "COMMITTING":
            return ["reconcile or finish the pending commit", "quota/checkpoint gate", "advance ticket"]
        role = {
            "ARCHITECTURE_PENDING": "Sol architecture",
            "DIAGNOSTIC_PENDING": "Sol diagnostic",
            "SUPERVISOR_REPAIR_PENDING": "Sol supervisor repair",
        }.get(phase, "Terra")
        return [
            f"quota/checkpoint gate, then invoke {role} for {ticket}",
            "deterministic verification if the structured report passes",
            "scope gate",
            "commit if every gate passes",
            "quota/checkpoint gate and advance according to the implementation plan",
        ]

    def advertised_resume_command(self, state: dict[str, Any]) -> str | None:
        if state.get("phase") not in TERMINAL_STATES:
            return None
        if (
            state.get("phase") == "PERIODIC_CHECKPOINT"
            and self._post_implementation_periodic_resume_error(state) is not None
        ):
            return None
        if state.get("phase") == "REPORT_INVALID" and self._invalid_report_recovery_error(state) is not None:
            return None
        if state.get("phase") == "DIAGNOSTIC_FAILED" and self._diagnostic_failed_recovery_error(state) is not None:
            return None
        if state.get("phase") == "SCOPE_BLOCKED" and self._scope_blocked_recovery_error(state) is not None:
            return None
        if (
            state.get("phase") == "VERIFICATION_FAILED"
            and self._failed_host_verification(state.get("active_run") or {}) is None
        ):
            return None
        return "./dev resume"

    def dashboard(self) -> str:
        value = self.status()
        active = value["active_run"]
        quota = value["quota"]
        checkpoint = value["checkpoint"]
        policy_checkpoint = self.policy["periodic_checkpoint"]
        model = value["current_model"]
        plan = self._plan_tickets()
        current = value["current_ticket"]
        remaining_to_gate: list[str] = []
        if current in plan:
            start = plan.index(current)
            milestone_indexes = [
                plan.index(item["after_ticket"])
                for item in self.policy["milestones"] if item["after_ticket"] in plan and plan.index(item["after_ticket"]) >= start
            ]
            end = min(milestone_indexes) if milestone_indexes else min(len(plan) - 1, start + 3)
            remaining_to_gate = plan[start:end + 1]
        lines = [
            "PROJECT",
            f"  State: {value['phase']}{' (QUIESCENT · safe to power off)' if value['quiescent'] else ''}",
            f"  Ticket: {current}",
            f"  Role: {value['current_role']} · {model['model']} · reasoning {model['reasoning_effort']}",
            f"  HEAD: {value['head'][:12]}",
            f"  Working tree: {'clean' if value['working_tree_clean'] else 'dirty · ' + ', '.join(value['working_tree_files'])}",
            "",
            "PIPELINE",
            f"  Completed in plan: {', '.join(value['completed_tickets']) or 'none'}",
            f"  Current: {current}",
            f"  Upcoming: {', '.join(value['upcoming_tickets']) or 'none'}",
            f"  Remaining to next configured milestone: {', '.join(remaining_to_gate) or 'none'}",
            "  Gates: " + "; ".join(f"after {item['after_ticket']}: {item['name']}" for item in self.policy["milestones"]),
            "",
            "CURRENT RUN",
            f"  Stage: {value['phase']}",
            f"  Run ID: {active.get('id', 'none')}",
            f"  Start: {active.get('started_at', 'not running')}",
            f"  Elapsed: {format_duration(value['current_run_elapsed_seconds'])}",
            f"  Last completed result: {value['last_completed_result'] or 'none'}",
            "",
            "QUOTA",
            f"  Status: {value['quota_status'].upper()}",
        ]
        if quota:
            weekly = quota.get("weekly_percent_left")
            weekly_text = f"{weekly}%" if weekly is not None else "not supplied"
            lines.extend([
                f"  5-hour: {quota.get('five_hour_percent_left', 'unknown')}%",
                f"  Weekly: {weekly_text}",
            ])
        else:
            lines.extend(["  5-hour: unknown", "  Weekly: unknown"])
        ranges = self.policy["quota"]["roles"][value["current_role"]]
        lines.extend([
            f"  Applicable ranges: 5-hour {ranges['five_hour']} · weekly {ranges['weekly']}",
            f"  Next model permitted now: {'yes' if value['quota_status'] == 'ok' else 'no'}",
            "",
            "PERIODIC CHECKPOINT",
            f"  Active runtime: {format_duration(checkpoint['active_runtime_seconds'])} / {format_duration(policy_checkpoint['max_active_runtime_seconds'])}",
            f"  Completed tickets: {checkpoint['completed_tickets']} / {policy_checkpoint['max_completed_tickets']}",
            f"  Model invocations: {checkpoint['model_invocations']} / {policy_checkpoint['max_model_invocations']}",
            f"  Due: {'yes · ' + '; '.join(value['checkpoint_due']) if value['checkpoint_due'] else 'no'}",
            "",
            "PROGRESS",
            f"  Current ticket: {current}",
            f"  Completed/current stages: {value['last_completed_result'] or 'no completed stage recorded'} / {value['phase']}",
            "",
            "CAPABILITIES",
            "  " + "; ".join(
                f"{name}={'enabled' if details['effective'] else 'disabled'}"
                for name, details in value["effective_configuration"]["capabilities"].items()
            ),
            "",
            "NEXT",
        ])
        lines.extend(f"  {index}. {action}" for index, action in enumerate(value["next_actions"], 1))
        if value["message"]:
            lines.extend(["", "NOTICE", f"  {value['message']}"])
        return "\n".join(lines)

    def _ensure_start_git(self) -> str:
        self.git.require_repository()
        expected = self.policy["expected_branch"]
        actual = self.git.branch()
        if actual != expected:
            raise SupervisorError(f"expected branch {expected!r}, found {actual!r}")
        if not self.git.is_clean():
            names = ", ".join(self.git.changed_files())
            raise SupervisorError(f"working tree has unexpected pre-existing changes: {names}")
        return self.git.head()

    def _checkpoint_head_compatible(self, starting_head: Any) -> bool:
        """Accept the recorded HEAD or descendants containing only supervisor fixes."""
        if not isinstance(starting_head, str) or not starting_head:
            return False
        current_head = self.git.head()
        if current_head == starting_head:
            return True
        if not self.git.is_ancestor(starting_head, current_head):
            return False
        intervening = self.git.changed_files_between(starting_head, current_head)
        return bool(intervening) and all(self._is_supervisor_control_path(path) for path in intervening)

    def _model_checkpoint_matches(self, active: dict[str, Any]) -> bool:
        """Content-verify every tracked and untracked dirty path at a model checkpoint."""
        recorded_files = active.get("changed_files")
        recorded_fingerprint = active.get("post_invocation_fingerprint")
        return (
            self._checkpoint_head_compatible(active.get("starting_head"))
            and isinstance(recorded_files, list)
            and self.git.changed_files() == sorted(recorded_files)
            and isinstance(recorded_fingerprint, str)
            and bool(recorded_fingerprint)
            and self.git.fingerprint() == recorded_fingerprint
        )

    def _human_evidence_gate_policy(self, ticket: str) -> dict[str, Any] | None:
        """Return one explicitly configured owner-evidence gate, failing closed on bad policy."""
        configured = self.policy.get("human_evidence_gates", {}).get(ticket)
        if configured is None:
            return None
        if not isinstance(configured, dict):
            raise SupervisorError(f"human evidence gate policy for {ticket} must be an object")
        if set(configured) != {"message", "record_paths"}:
            raise SupervisorError(
                f"human evidence gate policy for {ticket} must contain only message and record_paths"
            )
        message = configured.get("message")
        paths = configured.get("record_paths")
        if not isinstance(message, str) or not message.strip():
            raise SupervisorError(f"human evidence gate policy for {ticket} requires a message")
        if (
            not isinstance(paths, list)
            or not paths
            or any(not isinstance(path, str) or not path for path in paths)
            or len(paths) != len(set(paths))
            or any(Path(path).is_absolute() or ".." in Path(path).parts for path in paths)
        ):
            raise SupervisorError(f"human evidence gate policy for {ticket} has invalid record_paths")
        return {"message": message, "record_paths": sorted(paths)}

    def _enter_human_evidence_gate(self, state: dict[str, Any], policy: dict[str, Any]) -> None:
        """Preserve a blocked implementation as an explicit owner-operated evidence gate."""
        active = state["active_run"]
        record_paths = policy["record_paths"]
        if any(path not in active.get("changed_files", []) for path in record_paths):
            self.transition(
                state, "REPORT_INVALID",
                "Human evidence gate record paths are absent from the preserved implementation checkpoint.",
            )
            return
        self.transition(
            state, "HUMAN_GATE", policy["message"],
            gate={
                "kind": "evidence",
                "ticket": state["current_ticket"],
                "head": self.git.head(),
                "implementation_run_id": active["id"],
                "implementation_fingerprint": active["post_invocation_fingerprint"],
                "record_paths": record_paths,
                "product_snapshot": self._product_snapshot(),
                "resume_phase": "RECOVER_MODEL",
            },
        )

    def _human_evidence_gate_release_error(self, state: dict[str, Any]) -> str | None:
        """Validate an evidence gate while allowing edits only to its named record files."""
        gate = state.get("gate")
        active = state.get("active_run")
        ticket = state.get("current_ticket")
        if not isinstance(gate, dict) or gate.get("kind") != "evidence":
            return "the current gate is not an evidence gate"
        policy = self._human_evidence_gate_policy(str(ticket))
        report = active.get("report") if isinstance(active, dict) else None
        if (
            policy is None
            or not isinstance(active, dict)
            or gate.get("ticket") != ticket
            or gate.get("implementation_run_id") != active.get("id")
            or gate.get("implementation_fingerprint") != active.get("post_invocation_fingerprint")
            or gate.get("record_paths") != policy["record_paths"]
            or gate.get("resume_phase") != "RECOVER_MODEL"
            or validate_report(report, "implementation", str(ticket))
            or report.get("status") != "blocked"
            or active.get("evidence_checks_passed") is not True
            or not self._checkpoint_head_compatible(active.get("starting_head"))
            or not self._checkpoint_head_compatible(gate.get("head"))
            or self.git.branch() != self.policy["expected_branch"]
            or self.git.changed_files() != active.get("changed_files")
        ):
            return "the preserved implementation, policy, checks, or Git checkpoint is inconsistent"
        before = gate.get("product_snapshot")
        current = self._product_snapshot()
        if not isinstance(before, dict) or not isinstance(before.get("entries"), list):
            return "the evidence gate snapshot is missing or malformed"
        evidence_paths = set(policy["record_paths"])
        before_other = [item for item in before["entries"] if item.get("path") not in evidence_paths]
        current_other = [item for item in current["entries"] if item.get("path") not in evidence_paths]
        if before_other != current_other:
            return "files outside the configured evidence record changed while the gate was closed"
        before_evidence = [item for item in before["entries"] if item.get("path") in evidence_paths]
        current_evidence = [item for item in current["entries"] if item.get("path") in evidence_paths]
        if len(before_evidence) != len(evidence_paths) or len(current_evidence) != len(evidence_paths):
            return "a configured evidence record is missing"
        if before_evidence == current_evidence:
            return "the owner evidence record is unchanged; record the dated PASS or FAIL first"
        return None

    def _post_implementation_periodic_resume_error(self, state: dict[str, Any]) -> str | None:
        """Return why a periodic post-implementation checkpoint cannot resume verification."""
        if state.get("phase") != "PERIODIC_CHECKPOINT":
            return "state is not a periodic checkpoint"
        gate = state.get("gate")
        active = state.get("active_run")
        ticket = state.get("current_ticket")
        if (
            not isinstance(gate, dict)
            or gate.get("kind") != "periodic"
            or gate.get("reason") != "PERIODIC_CHECKPOINT"
            or gate.get("resume_phase") != "VERIFYING"
            or gate.get("ticket") != ticket
            or not isinstance(gate.get("triggered_by"), list)
            or not gate["triggered_by"]
            or any(not isinstance(item, str) or not item for item in gate["triggered_by"])
        ):
            return "periodic gate is not an exact post-implementation verification checkpoint"
        if (
            not isinstance(active, dict)
            or active.get("role") != "implementation"
            or active.get("ticket") != ticket
            or active.get("invocation_completed") is not True
            or active.get("exit_code") != 0
            or active.get("rate_limited") is not False
            or active.get("accounting_recorded") is not True
            or active.get("verification_results") != []
            or state.get("pending_commit") is not None
            or state.get("starting_head") != active.get("starting_head")
            or gate.get("head") != active.get("starting_head")
            or gate.get("fingerprint") != active.get("post_invocation_fingerprint")
        ):
            return "completed implementation checkpoint is missing, malformed, or beyond verification entry"
        report = active.get("report")
        if (
            validate_report(report, "implementation", str(ticket))
            or report.get("status") != "pass"
            or report.get("architecture_deviation") is not False
            or report.get("ambiguity") is not False
            or report.get("product_decision_required") is not False
            or any(
                report.get(field) is not True
                for field in ("acceptance_passed", "tests_passed", "next_ticket_safe")
            )
            or active.get("changed_files") != sorted(report.get("files_changed", []))
        ):
            return "completed implementation report is invalid or does not authorize verification"
        history = state.get("history")
        last = history[-1] if isinstance(history, list) and history else None
        if (
            not isinstance(last, dict)
            or last.get("from") != "VERIFYING"
            or last.get("to") != "PERIODIC_CHECKPOINT"
        ):
            return "periodic checkpoint history does not follow implementation PASS"
        if self.git.branch() != self.policy["expected_branch"] or not self._model_checkpoint_matches(active):
            return "completed implementation working tree is stale or no longer exact"

        authorization = active.get("quota_authorization")
        consumptions = state.get("quota_consumptions")
        if (
            not isinstance(authorization, dict)
            or authorization.get("status") != "consumed"
            or authorization.get("invocation_id") != active.get("id")
            or authorization.get("role") != "implementation"
            or authorization.get("ticket") != ticket
            or authorization.get("recovery") is not active.get("recovery")
            or not isinstance(consumptions, list)
            or sum(item == authorization for item in consumptions) != 1
        ):
            return "implementation quota authorization is missing or contradictory"
        run_id = active.get("id")
        if not isinstance(run_id, str) or not run_id or Path(run_id).name != run_id:
            return "implementation run identity is malformed"
        try:
            invocation = read_json(self.runs_dir / run_id / "invocation.json")
            persisted_report = read_json(self.runs_dir / run_id / "final-report.json")
            persisted_files = json.loads(
                (self.runs_dir / run_id / "changed-files.json").read_text(encoding="utf-8")
            )
        except (SupervisorError, OSError, json.JSONDecodeError):
            return "durable implementation invocation artifacts are missing or malformed"
        if (
            invocation.get("completed") is not True
            or invocation.get("exit_status") != 0
            or invocation.get("rate_limited") is not False
            or persisted_report != report
            or not isinstance(persisted_files, list)
            or persisted_files != active.get("changed_files")
        ):
            return "durable implementation invocation artifacts contradict supervisor state"
        return None

    def _resume_post_implementation_periodic_checkpoint(self, state: dict[str, Any]) -> dict[str, Any]:
        """Release one exact completed implementation checkpoint into deterministic verification."""
        error = self._post_implementation_periodic_resume_error(state)
        if error is not None:
            return state
        gate = state["gate"]
        active = state["active_run"]
        state.setdefault("periodic_resumptions", []).append({
            "at": isoformat(self.now()),
            "ticket": state["current_ticket"],
            "run_id": active["id"],
            "checkpoint_head": gate["head"],
            "fingerprint": gate["fingerprint"],
            "resume_phase": "VERIFYING",
        })
        state["periodic_checkpoint"] = {
            "baseline_at": isoformat(self.now()),
            "active_runtime_seconds": 0.0,
            "completed_tickets": 0,
            "model_invocations": 0,
        }
        self.transition(
            state, "VERIFYING",
            "Validated completed implementation checkpoint; continuing with deterministic verification "
            "without another model invocation.",
            gate=None,
        )
        return state

    def _protected_paths(self, paths: Any) -> list[str]:
        if not isinstance(paths, list):
            return []
        return sorted(
            path for path in paths
            if isinstance(path, str) and any(
                path == prefix or path.startswith(prefix)
                for prefix in self.policy["implementation_forbidden_paths"]
            )
        )

    def _validated_protected_scope_checkpoint(
        self, state: dict[str, Any], active: Any, protected_paths: Any,
    ) -> str | None:
        """Validate a verified implementation checkpoint stopped only at protected scope."""
        ticket = state.get("current_ticket")
        if not isinstance(active, dict) or not isinstance(ticket, str) or not ticket:
            return "the active implementation checkpoint or current ticket is missing"
        report = active.get("report")
        changed_files = active.get("changed_files")
        if (
            active.get("role") != "implementation"
            or active.get("ticket") != ticket
            or active.get("invocation_completed") is not True
            or active.get("exit_code") != 0
            or active.get("rate_limited") is not False
            or not isinstance(changed_files, list)
            or changed_files != sorted(set(changed_files))
            or validate_report(report, "implementation", ticket)
            or report.get("status") != "pass"
            or any(
                report.get(field) is not True
                for field in ("acceptance_passed", "tests_passed", "next_ticket_safe")
            )
            or report.get("architecture_deviation") is not False
            or report.get("ambiguity") is not False
            or report.get("product_decision_required") is not False
            or sorted(report.get("files_changed", [])) != changed_files
            or not self._model_checkpoint_matches(active)
            or self.git.branch() != self.policy["expected_branch"]
        ):
            return "the implementation report or exact post-model tree is stale or contradictory"
        expected_protected = self._protected_paths(changed_files)
        if (
            not expected_protected
            or protected_paths != expected_protected
        ):
            return "the protected-path reason does not exactly match current policy"

        expected_checks = list(self.policy["verification_commands"])
        expected_checks.extend(
            self.policy.get("ticket_verification_commands", {}).get(ticket, [])
        )
        results = active.get("verification_results")
        if (
            not isinstance(results, list)
            or len(results) != len(expected_checks)
            or any(
                not isinstance(result, dict)
                or result.get("name") != check.get("name")
                or result.get("command") != check.get("command")
                or result.get("passed") is not True
                or result.get("exit_status") != 0
                for result, check in zip(results, expected_checks)
            )
        ):
            return "deterministic verification evidence is missing or no longer policy-exact"

        authorization = active.get("quota_authorization")
        consumptions = state.get("quota_consumptions")
        if (
            not isinstance(authorization, dict)
            or authorization.get("status") != "consumed"
            or authorization.get("invocation_id") != active.get("id")
            or authorization.get("role") != "implementation"
            or authorization.get("ticket") != ticket
            or not isinstance(consumptions, list)
            or sum(item == authorization for item in consumptions) != 1
        ):
            return "the implementation quota audit is missing or contradictory"

        run_id = active.get("id")
        if not isinstance(run_id, str) or not run_id or Path(run_id).name != run_id:
            return "the implementation run identity is malformed"
        run_dir = self.runs_dir / run_id
        try:
            invocation = read_json(run_dir / "invocation.json")
            persisted_report = read_json(run_dir / "final-report.json")
            persisted_checks = json.loads((run_dir / "checks.json").read_text(encoding="utf-8"))
            persisted_files = json.loads((run_dir / "changed-files.json").read_text(encoding="utf-8"))
        except (SupervisorError, OSError, json.JSONDecodeError):
            return "the durable invocation, report, verification, or changed-file artifact is unavailable"
        if (
            invocation.get("completed") is not True
            or invocation.get("exit_status") != 0
            or invocation.get("rate_limited") is not False
            or persisted_report != report
            or persisted_checks != results
            or persisted_files != changed_files
            or not (run_dir / "check-git-diff.log").is_file()
        ):
            return "the durable checkpoint artifacts contradict supervisor state"
        return None

    def _scope_blocked_recovery_error(self, state: dict[str, Any]) -> str | None:
        """Return why SCOPE_BLOCKED cannot enter protected-path architecture review."""
        if state.get("scope_recovery_unavailable"):
            return str(state["scope_recovery_unavailable"])
        if state.get("phase") != "SCOPE_BLOCKED":
            return "the supervisor is not at a scope-blocked checkpoint"
        active = state.get("active_run")
        protected = self._protected_paths(
            active.get("changed_files") if isinstance(active, dict) else None
        )
        error = self._validated_protected_scope_checkpoint(state, active, protected)
        if error is not None:
            return error
        history = state.get("history")
        last = history[-1] if isinstance(history, list) and history else None
        expected_message = (
            "Implementation changed protected architecture/OpenAPI/schema/tooling paths: "
            + ", ".join(protected)
        )
        if (
            not isinstance(last, dict)
            or last.get("from") != "SCOPE_PENDING"
            or last.get("to") != "SCOPE_BLOCKED"
            or last.get("message") != expected_message
            or state.get("message") != expected_message
        ):
            return "the protected-path SCOPE_BLOCKED transition is missing or contradictory"
        return None

    def _preserved_architecture_checkpoint(self, state: dict[str, Any]) -> dict[str, Any]:
        """Validate the one dirty checkpoint authorized by an architecture diagnosis."""
        ticket = state.get("current_ticket")
        active = state.get("active_run")
        diagnostic = state.get("diagnostic")
        context = state.get("recovery_context")
        if (
            not isinstance(ticket, str)
            or not ticket
            or not isinstance(active, dict)
            or not isinstance(context, dict)
        ):
            raise SupervisorError("architecture checkpoint authorization is missing or malformed")
        if context.get("kind") == "protected_scope_review":
            source_active = context.get("source_active")
            protected_paths = context.get("protected_paths")
            error = self._validated_protected_scope_checkpoint(
                state, source_active, protected_paths,
            )
            if (
                error is not None
                or active != source_active
                or context.get("role") != "architecture"
                or context.get("ticket") != ticket
                or context.get("prior_run_id") != source_active.get("id")
                or context.get("starting_head") != source_active.get("starting_head")
                or context.get("fingerprint") != source_active.get("post_invocation_fingerprint")
                or context.get("preserved_files") != source_active.get("changed_files")
                or self.git.branch() != self.policy["expected_branch"]
            ):
                raise SupervisorError(
                    "protected-scope architecture checkpoint is stale, malformed, or no longer exact"
                    + (f": {error}" if error else "")
                )
            snapshot = self._product_snapshot()
            return {
                "ticket": ticket,
                "source_run_id": source_active["id"],
                "source_starting_head": source_active["starting_head"],
                "files": list(source_active["changed_files"]),
                "fingerprint": source_active["post_invocation_fingerprint"],
                "product_snapshot": snapshot,
                "recovery_context": dict(context),
                "source_active": deepcopy(source_active),
                "protected_paths": list(protected_paths),
                "scope_review": True,
            }
        if not isinstance(diagnostic, dict):
            raise SupervisorError("architecture checkpoint authorization is missing or malformed")
        supplied = diagnostic.get("evidence_run_ids")
        diagnostic_valid = (
            diagnostic.get("status") == "classified"
            and diagnostic.get("classification") == "ARCHITECTURE_DECISION"
            and diagnostic.get("resulting_transition") == "ARCHITECTURE_PENDING"
            and diagnostic.get("ticket") == ticket
            and isinstance(supplied, list)
            and not validate_diagnostic_report(diagnostic.get("report"), ticket, supplied)
            and isinstance(diagnostic.get("workspace_before"), dict)
            and diagnostic.get("workspace_before") == diagnostic.get("workspace_after")
            and diagnostic.get("origin_recovery_context") == context
        )
        report = active.get("report")
        report_valid = (
            not validate_report(report, "implementation", ticket)
            and report.get("status") == "blocked"
            and report.get("acceptance_passed") is False
            and report.get("next_ticket_safe") is False
            and report.get("architecture_deviation") is False
            and report.get("ambiguity") is False
            and report.get("product_decision_required") is False
        )
        files = active.get("changed_files")
        context_valid = (
            context.get("kind") == "implementation_blocked"
            and context.get("role") == "implementation"
            and context.get("ticket") == ticket
            and context.get("prior_run_id") == active.get("id")
            and context.get("starting_head") == active.get("starting_head")
            and context.get("fingerprint") == active.get("post_invocation_fingerprint")
            and context.get("preserved_files") == files
            and active.get("role") == "implementation"
            and active.get("ticket") == ticket
            and active.get("invocation_completed") is True
            and active.get("exit_code") == 0
            and active.get("rate_limited") is False
            and isinstance(files, list)
            and files == sorted(set(files))
        )
        snapshot = self._product_snapshot()
        snapshot_paths = [item.get("path") for item in snapshot.get("entries", [])]
        snapshot_valid = (
            snapshot_paths == files
            and diagnostic.get("product_fingerprint_after") == snapshot.get("fingerprint")
            and (diagnostic.get("workspace_after") or {}).get("product") == snapshot
        )
        if (
            not diagnostic_valid
            or not report_valid
            or not context_valid
            or not snapshot_valid
            or self.git.branch() != self.policy["expected_branch"]
            or not self._model_checkpoint_matches(active)
        ):
            raise SupervisorError(
                "preserved architecture checkpoint is stale, cross-ticket, contradictory, or no longer exact"
            )
        return {
            "ticket": ticket,
            "source_run_id": active["id"],
            "source_starting_head": active["starting_head"],
            "files": list(files),
            "fingerprint": active["post_invocation_fingerprint"],
            "product_snapshot": snapshot,
            "recovery_context": dict(context),
        }

    def _preserved_paths_match(self, checkpoint: dict[str, Any]) -> bool:
        """Compare only product paths; Git fingerprint still covers control paths."""
        files = checkpoint.get("files")
        snapshot = checkpoint.get("product_snapshot")
        if (
            not isinstance(files, list)
            or files != sorted(set(files))
            or not isinstance(snapshot, dict)
        ):
            return False
        product_files = [path for path in files if not self._is_supervisor_control_path(path)]
        expected = {
            item.get("path"): item
            for item in snapshot.get("entries", [])
            if isinstance(item, dict) and item.get("path") in product_files
        }
        current = {
            item.get("path"): item
            for item in self._product_snapshot().get("entries", [])
            if isinstance(item, dict) and item.get("path") in product_files
        }
        return len(expected) == len(product_files) and current == expected

    def _ensure_recovery_git(self, state: dict[str, Any]) -> str:
        context = state.get("recovery_context") or {}
        starting_head = context.get("starting_head")
        if not self._checkpoint_head_compatible(starting_head):
            raise SupervisorError(
                "recovery HEAD no longer matches its recorded starting HEAD; only committed supervisor fixes may intervene"
            )
        expected = context.get("fingerprint")
        if expected is not None and self.git.fingerprint() != expected:
            raise SupervisorError("interrupted recovery working tree changed after the interruption checkpoint")
        if self.git.branch() != self.policy["expected_branch"]:
            raise SupervisorError("interrupted recovery is on the wrong branch")
        return starting_head

    @staticmethod
    def _snapshot_fingerprint(snapshot: dict[str, Any]) -> str:
        encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode()).hexdigest()

    def _product_snapshot(self) -> dict[str, Any]:
        """Hash every dirty non-supervisor path, including its Git status and kind."""
        entries: list[dict[str, Any]] = []
        for status, relative in self.git.status_entries():
            if self._is_supervisor_control_path(relative):
                continue
            path = self.root / relative
            item: dict[str, Any] = {"path": relative, "status": status}
            try:
                item["mode"] = oct(path.lstat().st_mode & 0o7777)
            except OSError:
                item["mode"] = None
            if path.is_symlink():
                item.update({"kind": "symlink", "sha256": hashlib.sha256(os.readlink(path).encode()).hexdigest()})
            elif path.is_file():
                item.update({"kind": "file", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            elif path.is_dir():
                item["kind"] = "directory"
            else:
                item["kind"] = "missing"
            entries.append(item)
        value = {"entries": entries}
        value["fingerprint"] = self._snapshot_fingerprint(value)
        return value

    def _completed_recovery_run_ids(self, state: dict[str, Any], ticket: str) -> list[str]:
        """Derive completed attempts in the current same-ticket recovery window."""
        result: list[str] = []
        pattern = re.compile(r"^implementation invocation (\S+) started$")
        for item in state.get("history", []):
            if not isinstance(item, dict) or item.get("to") != "IMPLEMENTING":
                continue
            match = pattern.match(str(item.get("message", "")))
            if not match:
                continue
            run_id = match.group(1)
            if not run_id.endswith(f"-implementation-{ticket.lower()}"):
                continue
            if item.get("from") != "RECOVER_MODEL":
                # A normal implementation start opens a new ticket activation. This
                # matters when a deferred ticket returns after its newly inserted
                # prerequisite completed: recoveries from the earlier activation
                # must not immediately escalate the fresh work.
                result.clear()
                continue
            run_dir = self.runs_dir / run_id
            outcome_path = run_dir / "process-outcome.json"
            invocation_path = run_dir / "invocation.json"
            try:
                outcome = read_json(outcome_path if outcome_path.exists() else invocation_path)
            except SupervisorError:
                continue
            if outcome.get("completed") is True and run_id not in result:
                result.append(run_id)
        return result

    def _maybe_trigger_diagnostic(self, state: dict[str, Any]) -> bool:
        context = state.get("recovery_context") or {}
        if context.get("role", "implementation") != "implementation":
            return False
        ticket = state["current_ticket"]
        run_ids = self._completed_recovery_run_ids(state, ticket)
        prior = state.get("diagnostic")
        baseline = 0
        if isinstance(prior, dict) and prior.get("ticket") == ticket:
            candidate = prior.get("authorized_recovery_count", 0)
            if type(candidate) is int and 0 <= candidate <= len(run_ids):
                baseline = candidate
        threshold = int(self.policy["diagnostic"]["completed_same_ticket_recoveries"])
        if threshold < 2:
            raise SupervisorError("diagnostic recovery threshold must be at least 2")
        attempts = len(run_ids) - baseline
        if attempts < threshold:
            return False
        product_snapshot = self._product_snapshot()
        diagnostic = {
            "status": "pending",
            "ticket": ticket,
            "triggered_at": isoformat(self.now()),
            "trigger": "repeated_same_ticket_implementation_recovery",
            "threshold": threshold,
            "completed_recovery_count": len(run_ids),
            "completed_recovery_run_ids": run_ids,
            "recoveries_since_last_diagnostic": attempts,
            "origin_phase": "RECOVER_MODEL",
            "origin_recovery_context": context,
            "product_snapshot_before": product_snapshot,
            "product_fingerprint_before": product_snapshot["fingerprint"],
        }
        self.transition(
            state, "DIAGNOSTIC_PENDING",
            f"Diagnostic escalation triggered after {attempts} completed same-ticket recoveries "
            f"(threshold {threshold}); Sol/High classification is required before another Terra recovery.",
            diagnostic=diagnostic,
        )
        return True

    @staticmethod
    def _bounded_text(path: Path, limit: int) -> tuple[str, dict[str, Any]]:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        truncated = len(data) > limit
        if truncated:
            half = max(1, limit // 2)
            supplied = data[:half] + b"\n... bounded evidence truncated ...\n" + data[-half:]
        else:
            supplied = data
        return supplied.decode("utf-8", errors="replace"), {
            "path": str(path), "bytes": len(data), "sha256": digest, "truncated": truncated,
        }

    def _diagnostic_evidence(self, state: dict[str, Any]) -> dict[str, Any]:
        """Build a deterministic, size-bounded evidence bundle owned by the supervisor."""
        policy = self.policy["diagnostic"]
        ticket = state["current_ticket"]
        max_runs = int(policy["max_recent_runs"])
        artifact_limit = int(policy["max_artifact_bytes"])
        max_logs = int(policy["max_check_logs_per_run"])
        ticket_limit = int(policy["max_ticket_context_bytes"])
        all_candidates = sorted(
            path for path in self.runs_dir.glob(f"*-{ticket.lower()}") if path.is_dir()
        )
        candidates = all_candidates[-max_runs:]
        active_id = (state.get("active_run") or {}).get("id")
        active_path = self.runs_dir / active_id if isinstance(active_id, str) else None
        if active_path in all_candidates and active_path not in candidates:
            recent = candidates[-(max_runs - 1):] if max_runs > 1 else []
            candidates = sorted([active_path, *recent])
        manifest: list[dict[str, Any]] = []
        runs: list[dict[str, Any]] = []
        fixed_names = (
            "final-report.json", "process-outcome.json", "invocation.json",
            "changed-files.json", "diff-summary.txt", "checks.json", "stderr.log", "events.jsonl",
        )
        for run_dir in candidates:
            artifacts: dict[str, str] = {}
            selected = [run_dir / name for name in fixed_names if (run_dir / name).is_file()]
            selected.extend(sorted(run_dir.glob("check-*.log"))[-max_logs:])
            seen: set[str] = set()
            for path in selected:
                if path.name in seen:
                    continue
                seen.add(path.name)
                text_value, record = self._bounded_text(path, artifact_limit)
                relative = str(path.relative_to(self.root))
                record["path"] = relative
                manifest.append(record)
                artifacts[path.name] = text_value
            runs.append({"run_id": run_dir.name, "artifacts": artifacts})

        ticket_path = self._ticket_path(ticket)
        context_documents: list[dict[str, str]] = []
        ticket_text, record = self._bounded_text(ticket_path, ticket_limit)
        record["path"] = str(ticket_path.relative_to(self.root))
        manifest.append(record)
        context_documents.append({"path": record["path"], "content": ticket_text})
        plan_path = self.root / self.policy["implementation_plan"]
        plan_text, record = self._bounded_text(plan_path, ticket_limit)
        record["path"] = str(plan_path.relative_to(self.root))
        manifest.append(record)
        context_documents.append({"path": record["path"], "content": plan_text})

        linked: list[Path] = []
        for target in re.findall(r"\]\(([^)]+\.md)\)", ticket_text):
            candidate = (ticket_path.parent / target).resolve()
            try:
                candidate.relative_to((self.root / "docs" / "architecture").resolve())
            except ValueError:
                continue
            if candidate.is_file() and candidate not in linked:
                linked.append(candidate)
        for path in linked[:int(policy["max_adr_documents"])]:
            content, record = self._bounded_text(path, ticket_limit)
            record["path"] = str(path.relative_to(self.root))
            manifest.append(record)
            context_documents.append({"path": record["path"], "content": content})

        try:
            quota = self.quota.snapshot()
        except SupervisorError as error:
            quota = {"error": str(error)}
        product_snapshot = self._product_snapshot()
        history = state.get("history", [])
        bounded_history = history[-int(policy["max_history_entries"]):] if isinstance(history, list) else []
        return {
            "version": 1,
            "selection_policy": {
                "recent_same_ticket_runs": max_runs,
                "artifact_bytes_each": artifact_limit,
                "check_logs_each_run": max_logs,
                "history_entries": int(policy["max_history_entries"]),
                "ticket_context_bytes_each": ticket_limit,
                "linked_adr_documents": int(policy["max_adr_documents"]),
            },
            "ticket": ticket,
            "phase": state.get("phase"),
            "trigger": state.get("diagnostic"),
            "state": {
                "current_ticket": ticket,
                "completed_tickets": state.get("completed_tickets"),
                "message": state.get("message"),
                "recovery_context": state.get("recovery_context"),
                "architecture_resolution": state.get("architecture_resolution"),
                "periodic_checkpoint": state.get("periodic_checkpoint"),
                "gate": state.get("gate"),
                "history": bounded_history,
            },
            "quota": quota,
            "git": {
                "head": self.git.head(), "branch": self.git.branch(),
                "status": [{"status": status, "path": path} for status, path in self.git.status_entries()],
                "diff_summary": self.git.diff_summary()[:artifact_limit],
                "product_snapshot": product_snapshot,
            },
            "host_verification_handoff_candidate": self._environment_verification_handoff(
                state.get("active_run") or {}
            ),
            "supplied_run_ids": [path.name for path in candidates],
            "runs": runs,
            "context_documents": context_documents,
            "evidence_manifest": manifest,
        }

    def _guard_quota(self, state: dict[str, Any], role: str, resume_phase: str) -> str | None:
        result, message = self.quota.evaluate(role, self.policy["quota"])
        if result == "ok":
            try:
                snapshot = self.quota.snapshot()
            except SupervisorError as error:
                result, message = "unknown", str(error)
            else:
                observation_id = snapshot.get("observation_id") if snapshot else None
                if isinstance(observation_id, str) and observation_id:
                    return observation_id
                result, message = "unknown", "quota observation lacks a durable identity"
        phase = "QUOTA_CHECK_REQUIRED" if result == "unknown" else "QUOTA_LOW"
        self.transition(
            state, phase, message, quota_resume_phase=resume_phase,
            pending_role=role,
        )
        return None

    def _ticket_path(self, ticket: str) -> Path:
        raw = ticket[1:]
        if ticket.startswith("F"):
            pattern = f"{ticket.lower()}-*.md"
        else:
            pattern = f"{int(raw):02d}-*.md"
        materialization = self._current_backlog_materialization()
        directory = (
            self._backlog_cycle_artifact(materialization["tickets"])
            if materialization is not None
            else self.root / "docs" / "architecture" / "tickets"
        )
        matches = sorted(directory.glob(pattern))
        if len(matches) != 1:
            raise SupervisorError(f"could not resolve one ticket document for {ticket}: {pattern}")
        return matches[0]

    def _authoritative_list(self, ticket_path: Path) -> str:
        values = list(self.policy["authoritative_documents"])
        materialization = self._current_backlog_materialization()
        if materialization is not None:
            replacements = {
                self.policy["implementation_plan"]: str(
                    self._backlog_cycle_artifact(materialization["plan"]).relative_to(self.root)
                ),
            }
            values = [replacements.get(value, value) for value in values]
            values = [
                str(self._backlog_cycle_artifact(materialization["index"]).relative_to(self.root))
                if value.endswith("requirements-index.md") else value
                for value in values
            ]
        values.append(str(ticket_path.relative_to(self.root)))
        missing = [value for value in values if not (self.root / value).is_file()]
        if missing:
            raise SupervisorError("missing authoritative documents: " + ", ".join(missing))
        return "\n".join(f"- {value}" for value in values)

    def _prompt(self, role: str, state: dict[str, Any]) -> str:
        ticket = state["current_ticket"]
        ticket_path = self._ticket_path(ticket)
        relative = str(ticket_path.relative_to(self.root))
        recovery_context = state.get("recovery_context") or {}
        if (
            recovery_context.get("kind") == "environment"
            and recovery_context.get("host_verification_required") is True
        ):
            environment_recovery_instruction = (
                "If the recovery context names a sandbox capability limitation, do not treat it as an "
                "architecture decision and do not attempt to prove that lifecycle in the model sandbox; "
                "the configured host verification remains mandatory."
            )
        elif recovery_context.get("kind") == "environment":
            environment_recovery_instruction = (
                "If the recovery context records an environment report without a policy-owned host handoff, "
                "no mandatory host verification is available for that blocker. Do not repeat completed work "
                "or keep reporting the ticket as environment-blocked solely because an unrelated or "
                "unconfigured check cannot run. Evaluate completion from the ticket-owned requirements and "
                "configured checks; return PASS if they are complete, or report concrete remaining "
                "ticket-owned work or a genuine blocker."
            )
        else:
            environment_recovery_instruction = ""
        values = {
            "ticket": ticket,
            "ticket_path": relative,
            "ticket_text": ticket_path.read_text(encoding="utf-8"),
            "authoritative_documents": self._authoritative_list(ticket_path),
            "architecture_resolution": (
                "Previous architecture resolution for this rerun:\n" +
                json.dumps(state["architecture_resolution"], indent=2, ensure_ascii=False)
                if state.get("architecture_resolution") else
                "No prior architecture resolution applies to this run."
            ),
            "blocker_report": json.dumps(state.get("blocked_report"), indent=2, ensure_ascii=False),
            "ticket_verification": (
                "Ticket-specific deterministic verification commands that must pass after a PASS report:\n" +
                json.dumps(self.policy.get("ticket_verification_commands", {}).get(ticket, []), indent=2)
            ),
            "recovery_context": (
                "REPORT RECOVERY RUN: The prior model invocation completed and its exact working-tree delta is "
                "preserved, but its structured report was invalid. Inspect the existing files and return a valid "
                "replacement report only. Do not modify, add, remove, stage, or commit any file. For an architecture "
                "run carrying a preserved implementation checkpoint, files_changed must list only the architecture "
                "delta named in role_changed_files, not the preserved implementation files. Do not reinterpret PASS, "
                "architecture_deviation, ambiguity, or any other field; report them consistently.\n" +
                json.dumps(state.get("recovery_context"), indent=2, ensure_ascii=False)
                if (state.get("recovery_context") or {}).get("kind") == "report_invalid" else
                "PREREQUISITE RUN WITH PRESERVED LATER-TICKET WORK: Architecture inserted this ticket before "
                "the deferred active ticket. The dirty product files are an exact preserved checkpoint from that "
                "later ticket, not prior work for this ticket. Implement only the current prerequisite while "
                "preserving compatible later-ticket work. The prerequisite may modify shared paths that its own "
                "ticket explicitly assigns. Do not discard, reset, or narrow the preserved checkpoint. Because the "
                "prerequisite commit adopts the compatible checkpoint as its baseline, files_changed must list the "
                "complete resulting dirty supervisor-visible product path set.\n" +
                json.dumps(state.get("recovery_context"), indent=2, ensure_ascii=False)
                if (state.get("recovery_context") or {}).get("kind") == "architecture_prerequisite" else
                "PROTECTED-SCOPE ARCHITECTURE REVIEW: A same-ticket implementation returned PASS and passed "
                "deterministic verification, but the scope gate stopped because its exact preserved diff includes "
                "protected paths. This is a read-only review: inspect the ticket, accepted architecture, preserved "
                "working-tree diff, and protected-path reason. Do not modify, add, remove, stage, or commit any file. "
                "If every protected change is necessary and already within the accepted ticket architecture, return "
                "status=pass, all completion booleans true, all decision/deviation booleans false, and files_changed=[]. "
                "If product work must remove or rework a protected change, return status=blocked, "
                "product_decision_required=false, and files_changed=[]. If accepted architecture is insufficient and "
                "a genuine decision is required, return status=blocked, product_decision_required=true, and "
                "files_changed=[]. A PASS authorizes only the exact fingerprint and protected paths below; it is not a "
                "general scope-policy exception.\n" +
                json.dumps(state.get("recovery_context"), indent=2, ensure_ascii=False)
                if (state.get("recovery_context") or {}).get("kind") == "protected_scope_review" else
                "PERIODIC PLAN RECONCILIATION: A human identified a legitimate planning change while the "
                "supervisor was stopped at a durable periodic checkpoint. Resolve only that bounded planning "
                "need under docs/architecture. Do not implement product code or edit supervisor files. Preserve "
                "the completed plan prefix and the order of every existing ticket; insert only the newly required "
                "pending ticket or tickets before the deferred current ticket, add their resolvable ticket "
                "documents and explicit dependencies, and run relevant architecture consistency checks. The "
                "supervisor will validate the resulting plan before commit and execution.\n" +
                json.dumps(state.get("recovery_context"), indent=2, ensure_ascii=False)
                if (state.get("recovery_context") or {}).get("kind") == "periodic_plan_reconciliation" else
                "HUMAN EVIDENCE COMPLETION RUN: The configured owner evidence gate was explicitly released. "
                "Inspect the preserved implementation and the named redacted evidence record. Treat the human "
                "record as evidence, not as permission to invent missing observations. Complete only this ticket, "
                "add the smallest non-sensitive regression required by an observed lesson, and report PASS only "
                "when the ticket's evidence-recording acceptance is complete. A recorded experiment FAIL may still "
                "complete an evidence ticket when the ticket explicitly defines FAIL as a valid terminal outcome.\n" +
                json.dumps(state.get("recovery_context"), indent=2, ensure_ascii=False)
                if (state.get("recovery_context") or {}).get("kind") == "human_evidence" else
                "RECOVERY RUN: A prior invocation of this SAME ticket was interrupted, returned a "
                "blocked or environment-blocked report, or produced a preserved implementation that failed "
                "deterministic verification. "
                "Inspect the existing working-tree changes and run artifacts listed below. "
                "Continue or repair that partial implementation; do not assume a clean start, "
                "do not repeat completed work, do not discard existing work, and do not broaden scope. "
                "If deterministic verification failed, repair the recorded failure before rerunning that host check. "
                "Finish missing ticket-owned implementation and tests. " + environment_recovery_instruction + "\n" +
                json.dumps(state.get("recovery_context"), indent=2, ensure_ascii=False)
                if state.get("recovery_context") else
                "This is not an interrupted-invocation recovery run."
            ),
        }
        template_name = "implement.md" if role == "implementation" else "architecture-blocker.md"
        return (self.assets_dir / "prompts" / template_name).read_text(encoding="utf-8").format(**values)

    def _new_run_id(self, role: str, ticket: str) -> str:
        stamp = self.now().strftime("%Y%m%dT%H%M%S.%fZ")
        base = f"{stamp}-{role}-{ticket.lower()}"
        candidate = base
        suffix = 1
        while (self.runs_dir / candidate).exists():
            suffix += 1
            candidate = f"{base}-{suffix}"
        return candidate

    def _invoke(
        self, state: dict[str, Any], role: str, observation_id: str, *, recovery: bool = False,
    ) -> None:
        preserved_checkpoint = None
        recovery_context = state.get("recovery_context") or {}
        report_recovery = recovery and recovery_context.get("kind") == "report_invalid"
        if report_recovery:
            error = self._invalid_report_recovery_error(state)
            if error is not None:
                raise SupervisorError("report recovery checkpoint is unsafe: " + error)
            start_head = self._ensure_recovery_git(state)
            candidate = recovery_context.get("preserved_implementation_checkpoint")
            if candidate is not None:
                if role != "architecture" or not isinstance(candidate, dict):
                    raise SupervisorError("report recovery preserved checkpoint is malformed")
                preserved_checkpoint = candidate
        elif role == "architecture" and not self.git.is_clean():
            preserved_checkpoint = self._preserved_architecture_checkpoint(state)
            start_head = self.git.head()
        else:
            start_head = self._ensure_recovery_git(state) if recovery else self._ensure_start_git()
        schema_path = self.assets_dir / "schemas" / "agent-report.schema.json"
        require_codex_output_schema(schema_path)
        ticket = state["current_ticket"]
        checkpoint = self._checkpoint_data(state)
        if not isinstance(state.get("ticket_timing"), dict) or state["ticket_timing"].get("ticket") != ticket:
            state["ticket_timing"] = {
                "ticket": ticket,
                "started_at": isoformat(self.now()),
                "active_runtime_start": checkpoint["active_runtime_seconds"],
                "architecture_escalated": False,
            }
        run_id = self._new_run_id(role, ticket)
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        prompt = self._prompt(role, state)
        atomic_write_text(run_dir / "prompt.md", prompt)
        model = self.policy["models"][role]
        active = {
            "id": run_id,
            "role": role,
            "ticket": ticket,
            "starting_head": start_head,
            "model": model["model"],
            "reasoning_effort": model["reasoning_effort"],
            "invocation_completed": False,
            "verification_results": [],
            "started_at": isoformat(self.now()),
            "recovery": recovery,
        }
        if preserved_checkpoint is not None:
            active["preserved_implementation_checkpoint"] = preserved_checkpoint
        if report_recovery:
            active["report_recovery_checkpoint"] = {
                "prior_run_id": recovery_context.get("prior_run_id"),
                "files": list(recovery_context.get("preserved_files", [])),
                "fingerprint": recovery_context.get("fingerprint"),
            }
        try:
            quota_authorization = self.quota.consume(
                observation_id,
                role=role,
                ticket=ticket,
                invocation_id=run_id,
                recovery=recovery,
                policy=self.policy["quota"],
            )
        except SupervisorError as error:
            self.transition(
                state,
                "QUOTA_CHECK_REQUIRED",
                f"Quota observation could not be consumed safely before model start: {error}",
                quota_resume_phase="RECOVER_MODEL" if recovery else (
                    "ARCHITECTURE_PENDING" if role == "architecture" else "READY"
                ),
                pending_role=role,
            )
            return
        active["quota_authorization"] = quota_authorization
        consumptions = state.setdefault("quota_consumptions", [])
        if not isinstance(consumptions, list):
            self.transition(
                state,
                "QUOTA_CHECK_REQUIRED",
                "Supervisor quota-consumption audit state is malformed; the observation was consumed and a fresh observation is required.",
                quota_resume_phase="RECOVER_MODEL" if recovery else (
                    "ARCHITECTURE_PENDING" if role == "architecture" else "READY"
                ),
                pending_role=role,
            )
            return
        consumptions.append(dict(quota_authorization))
        phase = "IMPLEMENTING" if role == "implementation" else "ARCHITECTURE_REVIEW"
        self.transition(
            state, phase, f"{role} invocation {run_id} started",
            starting_head=start_head, active_run=active,
        )
        label = f"{'Terra' if role == 'implementation' else 'Sol'}/{model['reasoning_effort'].title()}"
        self._emit(ticket, label, "RUNNING" + (" · RECOVERY" if recovery else ""))
        try:
            result = self.model_runner.invoke(
                role, ticket, prompt, run_dir, start_head, self.policy,
                schema_path,
            )
        except KeyboardInterrupt:
            result = InvocationResult(
                130, None, {}, error="operator interrupted model invocation",
                interrupted=True, interrupt_reason="keyboard_interrupt",
            )
        active["invocation_completed"] = not result.interrupted
        active["exit_code"] = result.exit_code
        active["usage"] = result.usage
        active["report"] = result.report
        active["rate_limited"] = result.rate_limited
        if result.rate_limited:
            self.quota.invalidate(observation_id, "rate_or_usage_signal")
        active["error"] = result.error
        active["duration_seconds"] = result.duration_seconds
        active["finished_at"] = isoformat(self.now())
        active["warning_emitted"] = result.warning_emitted
        active["changed_files"] = self.git.changed_files()
        active["post_invocation_fingerprint"] = self.git.fingerprint()
        if preserved_checkpoint is not None:
            preserved_files = set(preserved_checkpoint["files"])
            active["role_changed_files"] = [
                path for path in active["changed_files"] if path not in preserved_files
            ]
        state["last_completed_result"] = (
            f"{label} {'interrupted' if result.interrupted else 'completed'} in "
            f"{format_duration(result.duration_seconds)}"
        )
        checkpoint = self._checkpoint_data(state)
        checkpoint["model_invocations"] += 1
        self._add_active_runtime(state, result.duration_seconds)
        active["accounting_recorded"] = True
        self._record_timing("model_invocations", {
            "at": isoformat(self.now()), "role": role, "ticket": ticket,
            "duration_seconds": result.duration_seconds, "interrupted": result.interrupted,
            "architecture_escalation": role == "architecture",
        })
        atomic_write_json(run_dir / "usage.json", result.usage)
        atomic_write_json(run_dir / "invocation.json", {
            "completed": not result.interrupted, "interrupted": result.interrupted,
            "interrupt_reason": result.interrupt_reason,
            "exit_status": result.exit_code, "rate_limited": result.rate_limited,
            "error": result.error, "started_at": active["started_at"],
            "finished_at": active["finished_at"], "duration_seconds": result.duration_seconds,
            "warning_emitted": result.warning_emitted,
        })
        if result.report is not None:
            atomic_write_json(run_dir / "final-report.json", result.report)
        atomic_write_json(run_dir / "changed-files.json", active["changed_files"])
        atomic_write_text(run_dir / "diff-summary.txt", self.git.diff_summary())
        self.save_state(state)
        if report_recovery and (
            active["changed_files"] != recovery_context.get("preserved_files")
            or active["post_invocation_fingerprint"] != recovery_context.get("fingerprint")
        ):
            self.transition(
                state, "GIT_BLOCKED",
                "Report-only recovery changed the preserved working tree; the replacement report was rejected.",
            )
            return
        if preserved_checkpoint is not None and not self._preserved_paths_match(preserved_checkpoint):
            self.transition(
                state, "GIT_BLOCKED",
                "Architecture invocation changed the preserved implementation checkpoint; no verification or commit was attempted.",
            )
            return
        if result.interrupted:
            reason = result.interrupt_reason or "model_interrupted"
            self.transition(
                state, "INTERRUPTED",
                f"Model invocation interrupted ({reason}); partial changes are preserved. Safe to power off. Resume with ./dev resume.",
                recovery_context={
                    "kind": "model", "role": role, "ticket": ticket,
                    "starting_head": start_head, "fingerprint": self.git.fingerprint(),
                    "prior_run_id": run_id, "reason": reason,
                    "partial_files": self.git.changed_files(),
                },
            )
            self._emit(ticket, label, "INTERRUPTED · safe to power off · resume: ./dev resume")
            return
        self._process_invocation(state)
        if state["phase"] == "VERIFYING":
            self._emit(ticket, label, f"PASS ({format_duration(result.duration_seconds)})")
        elif state["phase"] == "ARCHITECTURE_PENDING":
            self._emit(ticket, label, f"BLOCKED ({format_duration(result.duration_seconds)}) · routing to Sol")
        elif state["phase"] in TERMINAL_STATES:
            self._emit(ticket, label, f"STOP · {state['phase']} ({format_duration(result.duration_seconds)})")
        if state["phase"] not in TERMINAL_STATES:
            self._maybe_periodic_gate(state, state["phase"])

    def _record_model_accounting(
        self, state: dict[str, Any], *, role: str, ticket: str,
        duration: float, interrupted: bool,
    ) -> None:
        checkpoint = self._checkpoint_data(state)
        checkpoint["model_invocations"] += 1
        self._add_active_runtime(state, duration)
        self._record_timing("model_invocations", {
            "at": isoformat(self.now()), "role": role, "ticket": ticket,
            "duration_seconds": duration, "interrupted": interrupted,
            "architecture_escalation": role == "architecture",
        })

    def _consume_for_auxiliary_model(
        self, state: dict[str, Any], *, role: str, ticket: str,
        run_id: str, observation_id: str, resume_phase: str,
    ) -> dict[str, Any] | None:
        try:
            authorization = self.quota.consume(
                observation_id, role=role, ticket=ticket, invocation_id=run_id,
                recovery=False, policy=self.policy["quota"],
            )
        except SupervisorError as error:
            self.transition(
                state, "QUOTA_CHECK_REQUIRED",
                f"Quota observation could not be consumed safely before model start: {error}",
                quota_resume_phase=resume_phase, pending_role=role,
            )
            return None
        consumptions = state.setdefault("quota_consumptions", [])
        if not isinstance(consumptions, list):
            self.transition(
                state, "QUOTA_CHECK_REQUIRED",
                "Supervisor quota-consumption audit state is malformed; the observation was consumed "
                "and a fresh observation is required.",
                quota_resume_phase=resume_phase, pending_role=role,
            )
            return None
        consumptions.append(dict(authorization))
        return authorization

    def _invoke_diagnostic(self, state: dict[str, Any], observation_id: str) -> None:
        diagnostic = state.get("diagnostic")
        if not isinstance(diagnostic, dict) or diagnostic.get("status") != "pending":
            self.transition(state, "DIAGNOSTIC_FAILED", "Pending diagnostic state is missing or malformed.")
            return
        ticket = state["current_ticket"]
        start_head = self._ensure_recovery_git(state)
        expected_product = diagnostic.get("product_snapshot_before")
        if expected_product != self._product_snapshot():
            self.transition(
                state, "DIAGNOSTIC_FAILED",
                "Preserved product tree changed before diagnostic start; refusing classification.",
            )
            return
        schema_path = self.assets_dir / "schemas" / "diagnostic-report.schema.json"
        require_codex_output_schema(schema_path)
        run_id = self._new_run_id("diagnostic", ticket)
        run_dir = self.runs_dir / run_id
        evidence = self._diagnostic_evidence(state)
        run_dir.mkdir(parents=True, exist_ok=False)
        evidence_path = run_dir / "diagnostic-evidence.json"
        atomic_write_json(evidence_path, evidence)
        prompt = (self.assets_dir / "prompts" / "diagnose.md").read_text(encoding="utf-8").format(
            ticket=ticket,
            evidence_path=str(evidence_path.relative_to(self.root)),
            evidence_json=json.dumps(evidence, indent=2, ensure_ascii=False),
        )
        atomic_write_text(run_dir / "prompt.md", prompt)
        model = self.policy["models"]["diagnostic"]
        authorization = self._consume_for_auxiliary_model(
            state, role="diagnostic", ticket=ticket, run_id=run_id,
            observation_id=observation_id, resume_phase="DIAGNOSTIC_PENDING",
        )
        if authorization is None:
            return
        workspace_before = {
            "head": self.git.head(), "files": self.git.changed_files(),
            "fingerprint": self.git.fingerprint(), "product": self._product_snapshot(),
        }
        diagnostic.update({
            "status": "running", "run_id": run_id,
            "model": model["model"], "reasoning_effort": model["reasoning_effort"],
            "quota_authorization": authorization,
            "evidence_run_ids": evidence["supplied_run_ids"],
            "evidence_manifest": evidence["evidence_manifest"],
            "evidence_path": str(evidence_path.relative_to(self.root)),
            "workspace_before": workspace_before,
        })
        self.transition(
            state, "DIAGNOSTIC_REVIEW", f"diagnostic invocation {run_id} started",
            diagnostic=diagnostic,
        )
        self._emit(ticket, "Sol/High diagnostic", "RUNNING")
        try:
            result = self.model_runner.invoke(
                "diagnostic", ticket, prompt, run_dir, start_head, self.policy, schema_path,
            )
        except KeyboardInterrupt:
            result = InvocationResult(
                130, None, {}, error="operator interrupted diagnostic invocation",
                interrupted=True, interrupt_reason="keyboard_interrupt",
            )
        diagnostic.update({
            "status": "completed" if not result.interrupted else "interrupted",
            "finished_at": isoformat(self.now()), "exit_code": result.exit_code,
            "report": result.report, "error": result.error,
            "duration_seconds": result.duration_seconds,
            "workspace_after": {
                "head": self.git.head(), "files": self.git.changed_files(),
                "fingerprint": self.git.fingerprint(), "product": self._product_snapshot(),
            },
            "accounting_recorded": True,
        })
        if result.rate_limited:
            self.quota.invalidate(observation_id, "rate_or_usage_signal")
        self._record_model_accounting(
            state, role="diagnostic", ticket=ticket,
            duration=result.duration_seconds, interrupted=result.interrupted,
        )
        atomic_write_json(run_dir / "usage.json", result.usage)
        atomic_write_json(run_dir / "invocation.json", {
            "completed": not result.interrupted, "interrupted": result.interrupted,
            "interrupt_reason": result.interrupt_reason, "exit_status": result.exit_code,
            "rate_limited": result.rate_limited, "error": result.error,
            "duration_seconds": result.duration_seconds,
        })
        if result.report is not None:
            atomic_write_json(run_dir / "final-report.json", result.report)
        atomic_write_json(run_dir / "changed-files.json", self.git.changed_files())
        atomic_write_text(run_dir / "diff-summary.txt", self.git.diff_summary())
        self.save_state(state)
        self._process_diagnostic(state, rate_limited=result.rate_limited, interrupted=result.interrupted)

    def _process_diagnostic(
        self, state: dict[str, Any], *, rate_limited: bool = False, interrupted: bool = False,
    ) -> None:
        diagnostic = state.get("diagnostic") or {}
        ticket = state["current_ticket"]
        if rate_limited:
            diagnostic["status"] = "pending"
            self.transition(
                state, "QUOTA_EXHAUSTED", "Diagnostic Sol reported a rate/usage limit; no retry was attempted.",
                diagnostic=diagnostic,
                quota_resume_phase="DIAGNOSTIC_PENDING", pending_role="diagnostic",
                quota_exhausted_at=isoformat(self.now()),
            )
            return
        if interrupted:
            self.transition(
                state, "DIAGNOSTIC_FAILED",
                "Diagnostic invocation was interrupted after consuming quota; no transition was inferred.",
            )
            return
        before = diagnostic.get("workspace_before")
        after = diagnostic.get("workspace_after")
        if not isinstance(before, dict) or before != after:
            self.transition(
                state, "DIAGNOSTIC_FAILED",
                "Read-only diagnostic changed HEAD or working-tree content; classification was rejected.",
            )
            return
        if diagnostic.get("exit_code") != 0:
            self.transition(
                state, "DIAGNOSTIC_FAILED",
                "Diagnostic Sol process failed; no recovery or verification transition was authorized.",
            )
            return
        supplied = diagnostic.get("evidence_run_ids")
        errors = validate_diagnostic_report(
            diagnostic.get("report"), ticket, supplied if isinstance(supplied, list) else [],
        )
        if errors:
            self.transition(
                state, "DIAGNOSTIC_FAILED",
                "Structured diagnostic failed closed: " + "; ".join(errors),
            )
            return
        report = diagnostic["report"]
        classification = report["classification"]
        diagnostic.update({
            "status": "classified", "classification": classification,
            "rationale_summary": report["rationale_summary"],
            "product_fingerprint_after": self._product_snapshot()["fingerprint"],
        })
        prerequisite = self._pending_plan_prerequisite(state, ticket)
        if (
            diagnostic.get("repair_commit")
            and classification in {"SUPERVISOR_BUG", "PRODUCT_FIX"}
            and prerequisite is not None
        ):
            product_snapshot = self._product_snapshot()
            diagnostic["resulting_transition"] = "QUOTA_CHECK_REQUIRED -> RECOVER_MODEL"
            diagnostic["scheduled_prerequisite"] = prerequisite
            self.transition(
                state, "QUOTA_CHECK_REQUIRED",
                f"Validated supervisor repair restored authoritative plan ordering: {prerequisite} "
                f"must run before deferred {ticket}. A fresh quota observation is required.\n" +
                quota_refresh_instructions(None),
                current_ticket=prerequisite,
                active_run=None,
                starting_head=None,
                blocked_report=None,
                diagnostic=diagnostic,
                recovery_context={
                    "kind": "architecture_prerequisite",
                    "role": "implementation",
                    "ticket": prerequisite,
                    "deferred_ticket": ticket,
                    "starting_head": self.git.head(),
                    "fingerprint": self.git.fingerprint(),
                    "preserved_files": self.git.changed_files(),
                    "preserved_product_snapshot": product_snapshot,
                    "reason": "authoritative_prerequisite_inserted_before_active_ticket",
                    "repair_commit": diagnostic["repair_commit"],
                },
                ticket_timing=None,
                quota_resume_phase="RECOVER_MODEL",
                pending_role="implementation",
            )
            return
        if self._route_post_repair_completion(state, diagnostic):
            return
        if classification == "PRODUCT_FIX":
            diagnostic["authorized_recovery_count"] = len(
                self._completed_recovery_run_ids(state, ticket)
            )
            diagnostic["resulting_transition"] = "QUOTA_CHECK_REQUIRED -> RECOVER_MODEL"
            context = dict(diagnostic.get("origin_recovery_context") or {})
            context["diagnostic"] = {
                "run_id": diagnostic.get("run_id"), "classification": classification,
                "rationale_summary": report["rationale_summary"],
            }
            self.transition(
                state, "QUOTA_CHECK_REQUIRED",
                "Diagnostic classified a concrete product fix. Its quota observation was consumed; "
                "a fresh observation is required before Terra recovery.\n" + quota_refresh_instructions(None),
                diagnostic=diagnostic, recovery_context=context,
                quota_resume_phase="RECOVER_MODEL", pending_role="implementation",
            )
            return
        if classification == "HOST_VERIFICATION_REQUIRED":
            active = state.get("active_run") or {}
            handoff = self._diagnostic_verification_handoff(state)
            if handoff is None:
                diagnostic["resulting_transition"] = "DIAGNOSTIC_FAILED"
                self.transition(
                    state, "DIAGNOSTIC_FAILED",
                    "HOST_VERIFICATION_REQUIRED contradicted deterministic host-handoff policy; "
                    "no verification was started.", diagnostic=diagnostic,
                )
                return
            active["host_verification_handoff"] = handoff
            diagnostic["resulting_transition"] = "VERIFYING"
            self.transition(
                state, "VERIFYING",
                "Diagnostic classified a policy-owned host verification requirement; "
                "deterministic checks will run without another implementation model.",
                diagnostic=diagnostic, verification_role="implementation",
            )
            return
        if classification == "SUPERVISOR_BUG":
            diagnostic["resulting_transition"] = "SUPERVISOR_REPAIR_PENDING"
            self.transition(
                state, "SUPERVISOR_REPAIR_PENDING",
                "Diagnostic classified a supervisor defect; bounded Sol/High supervisor repair is pending.",
                diagnostic=diagnostic,
            )
            return
        if classification == "ARCHITECTURE_DECISION":
            diagnostic["resulting_transition"] = "ARCHITECTURE_PENDING"
            self.transition(
                state, "ARCHITECTURE_PENDING",
                "Diagnostic classified a genuine architecture decision; using the existing architecture path.",
                diagnostic=diagnostic, blocked_report={
                    "source": "diagnostic", "classification": classification,
                    "summary": report["rationale_summary"], "ticket": ticket,
                },
            )
            return
        if classification == "HUMAN_DECISION_REQUIRED":
            diagnostic["resulting_transition"] = "HUMAN_GATE"
            self.transition(
                state, "HUMAN_GATE",
                "Diagnostic requires a genuine human product/scope/permission decision: " +
                report["rationale_summary"],
                diagnostic=diagnostic,
                gate={"kind": "product_decision", "source": "diagnostic", "head": self.git.head(), "ticket": ticket},
            )
            return
        self.transition(state, "DIAGNOSTIC_FAILED", "Unknown diagnostic classification failed closed.")

    def _recover_diagnostic_invocation(self, state: dict[str, Any]) -> bool:
        diagnostic = state.get("diagnostic") or {}
        run_id = diagnostic.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            self.transition(state, "DIAGNOSTIC_FAILED", "Diagnostic review lacks a durable run ID.")
            return False
        run_dir = self.runs_dir / run_id
        invocation_path = run_dir / "invocation.json"
        outcome_path = run_dir / "process-outcome.json"
        if invocation_path.exists():
            invocation = read_json(invocation_path)
        elif outcome_path.exists():
            invocation = read_json(outcome_path)
        else:
            self.transition(
                state, "DIAGNOSTIC_FAILED",
                "Diagnostic completion is absent; quota remains consumed and no transition was inferred.",
            )
            return False
        report_path = run_dir / "final-report.json"
        try:
            report = read_json(report_path) if report_path.exists() else None
        except SupervisorError:
            report = None
        diagnostic.update({
            "status": "completed" if invocation.get("completed") else "interrupted",
            "exit_code": invocation.get("exit_status", 1), "report": report,
            "workspace_after": {
                "head": self.git.head(), "files": self.git.changed_files(),
                "fingerprint": self.git.fingerprint(), "product": self._product_snapshot(),
            },
        })
        if not diagnostic.get("accounting_recorded"):
            duration = float(invocation.get("duration_seconds", 0) or 0)
            self._record_model_accounting(
                state, role="diagnostic", ticket=state["current_ticket"],
                duration=duration, interrupted=not bool(invocation.get("completed")),
            )
            diagnostic["duration_seconds"] = duration
            diagnostic["accounting_recorded"] = True
        self.save_state(state)
        self._process_diagnostic(
            state, rate_limited=bool(invocation.get("rate_limited")),
            interrupted=not bool(invocation.get("completed")),
        )
        return state["phase"] != "DIAGNOSTIC_FAILED"

    def _invoke_supervisor_repair(self, state: dict[str, Any], observation_id: str) -> None:
        diagnostic = state.get("diagnostic") or {}
        if diagnostic.get("classification") != "SUPERVISOR_BUG":
            self.transition(state, "SUPERVISOR_REPAIR_FAILED", "Supervisor repair lacks a validated SUPERVISOR_BUG diagnosis.")
            return
        ticket = state["current_ticket"]
        start_head = self._ensure_recovery_git(state)
        external_repair = self._uses_external_supervisor_repair()
        repair_root = self.assets_dir if external_repair else self.root
        repair_git = GitRepo(repair_root) if external_repair else self.git
        repair_git.require_repository()
        if external_repair and not repair_git.is_clean():
            self.transition(
                state, "SUPERVISOR_REPAIR_FAILED",
                "Supervisor repair repository must be clean before bounded self-repair.",
            )
            return
        repair_start_head = repair_git.head()
        product_before = diagnostic.get("product_snapshot_before")
        if not isinstance(product_before, dict) or product_before != self._product_snapshot():
            self.transition(
                state, "SUPERVISOR_REPAIR_FAILED",
                "Preserved product fingerprint changed before supervisor repair; human review is required.",
            )
            return
        schema_path = self.assets_dir / "schemas" / "supervisor-repair-report.schema.json"
        require_codex_output_schema(schema_path)
        run_id = self._new_run_id("supervisor-repair", ticket)
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        prompt = (self.assets_dir / "prompts" / "supervisor-repair.md").read_text(encoding="utf-8").format(
            ticket=ticket,
            product_snapshot=json.dumps(product_before, indent=2, ensure_ascii=False),
            diagnostic_report=json.dumps(diagnostic.get("report"), indent=2, ensure_ascii=False),
            evidence_path=diagnostic.get("evidence_path", "(missing evidence path)"),
        )
        atomic_write_text(run_dir / "prompt.md", prompt)
        authorization = self._consume_for_auxiliary_model(
            state, role="supervisor_repair", ticket=ticket, run_id=run_id,
            observation_id=observation_id, resume_phase="SUPERVISOR_REPAIR_PENDING",
        )
        if authorization is None:
            return
        repair = {
            "status": "running", "run_id": run_id, "started_at": isoformat(self.now()),
            "starting_head": repair_start_head, "invocation_starting_head": start_head,
            "repair_repository": "external" if external_repair else "embedded",
            "product_snapshot_before": product_before,
            "product_fingerprint_before": product_before["fingerprint"],
            "quota_authorization": authorization,
            "model": self.policy["models"]["supervisor_repair"]["model"],
            "reasoning_effort": self.policy["models"]["supervisor_repair"]["reasoning_effort"],
        }
        diagnostic["repair"] = repair
        self.transition(
            state, "SUPERVISOR_REPAIR", f"supervisor repair invocation {run_id} started",
            diagnostic=diagnostic,
        )
        self._emit(ticket, "Sol/High supervisor repair", "RUNNING")
        try:
            result = self.supervisor_repair_runner.invoke(
                "supervisor_repair", ticket, prompt, run_dir, repair_start_head, self.policy, schema_path,
            )
        except KeyboardInterrupt:
            result = InvocationResult(
                130, None, {}, error="operator interrupted supervisor repair",
                interrupted=True, interrupt_reason="keyboard_interrupt",
            )
        product_after = self._product_snapshot()
        repair.update({
            "status": "completed" if not result.interrupted else "interrupted",
            "finished_at": isoformat(self.now()), "exit_code": result.exit_code,
            "report": result.report, "error": result.error,
            "duration_seconds": result.duration_seconds,
            "product_snapshot_after": product_after,
            "product_fingerprint_after": product_after["fingerprint"],
            "head_after_model": repair_git.head(),
        })
        if result.rate_limited:
            self.quota.invalidate(observation_id, "rate_or_usage_signal")
        self._record_model_accounting(
            state, role="supervisor_repair", ticket=ticket,
            duration=result.duration_seconds, interrupted=result.interrupted,
        )
        atomic_write_json(run_dir / "usage.json", result.usage)
        atomic_write_json(run_dir / "invocation.json", {
            "completed": not result.interrupted, "interrupted": result.interrupted,
            "interrupt_reason": result.interrupt_reason, "exit_status": result.exit_code,
            "rate_limited": result.rate_limited, "error": result.error,
            "duration_seconds": result.duration_seconds,
        })
        if result.report is not None:
            atomic_write_json(run_dir / "final-report.json", result.report)
        atomic_write_json(run_dir / "changed-files.json", repair_git.changed_files())
        atomic_write_text(run_dir / "diff-summary.txt", repair_git.diff_summary())
        self.save_state(state)
        if result.rate_limited:
            self.transition(
                state, "QUOTA_EXHAUSTED", "Supervisor-repair Sol reported a rate/usage limit; no retry was attempted.",
                quota_resume_phase="SUPERVISOR_REPAIR_PENDING", pending_role="supervisor_repair",
                quota_exhausted_at=isoformat(self.now()),
            )
            return
        if result.interrupted or result.exit_code != 0:
            self.transition(
                state, "SUPERVISOR_REPAIR_FAILED",
                "Supervisor repair did not complete successfully; product work remains preserved.",
            )
            return
        if repair_git.head() != repair["starting_head"] or self.git.head() != start_head:
            self.transition(
                state, "SUPERVISOR_REPAIR_FAILED",
                "Supervisor repair moved HEAD; automatic validation requires the supervisor to own the commit.",
            )
            return
        if product_after != product_before:
            self.transition(
                state, "SUPERVISOR_REPAIR_FAILED",
                "Product fingerprint mismatch during supervisor repair; no files were staged or committed.",
            )
            return
        errors = validate_supervisor_repair_report(result.report, ticket)
        if external_repair:
            supervisor_files = sorted(
                path for path in repair_git.changed_files() if self._is_engine_repair_path(path)
            )
            disallowed_repair_files = sorted(
                path for path in repair_git.changed_files() if not self._is_engine_repair_path(path)
            )
            if disallowed_repair_files:
                errors.append("repair changed disallowed engine paths: " + ", ".join(disallowed_repair_files))
        else:
            supervisor_files = sorted(
                path for path in self.git.changed_files() if self._is_supervisor_control_path(path)
            )
        if not errors and result.report["status"] == "blocked":
            errors.append("repair report is blocked")
        if not errors and result.report["files_changed"] != supervisor_files:
            errors.append("reported files do not exactly match dirty supervisor paths")
        if not errors and not supervisor_files:
            errors.append("repair produced no supervisor changes")
        if errors:
            self.transition(
                state, "SUPERVISOR_REPAIR_FAILED",
                "Supervisor repair failed closed: " + "; ".join(errors),
            )
            return

        verification_results: list[dict[str, Any]] = []
        repair_checks = (
            [
                {
                    "name": "full supervisor tests",
                    "command": ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"],
                },
                {
                    "name": "supervisor Python compilation",
                    "command": ["python3", "-m", "py_compile", "supervisor.py"],
                },
            ]
            if external_repair else self.policy.get("supervisor_repair_verification_commands", [])
        )
        for index, check in enumerate(repair_checks, 1):
            output_path = run_dir / f"repair-check-{index:02d}.log"
            outcome = self.command_runner.run(list(check["command"]), repair_root, output_path)
            exit_code = outcome.exit_code if isinstance(outcome, CommandResult) else outcome
            passed = exit_code == 0
            verification_results.append({
                "name": check["name"], "command": check["command"],
                "exit_status": exit_code, "passed": passed, "log": output_path.name,
            })
            if not passed:
                repair["verification_results"] = verification_results
                self.transition(
                    state, "SUPERVISOR_REPAIR_FAILED",
                    f"Supervisor repair verification failed: {check['name']}.",
                )
                return
        diff_ok, diff_output = repair_git.diff_check()
        atomic_write_text(run_dir / "repair-check-git-diff.log", diff_output or "git diff --check passed\n")
        if not diff_ok or self._product_snapshot() != product_before:
            self.transition(
                state, "SUPERVISOR_REPAIR_FAILED",
                "Supervisor repair validation changed product content or failed git diff --check.",
            )
            return
        repair["verification_results"] = verification_results
        repair_git.stage_paths(supervisor_files)
        if repair_git.cached_files() != supervisor_files:
            self.transition(
                state, "SUPERVISOR_REPAIR_FAILED",
                "Staged repair is not supervisor-only; no commit was created.",
            )
            return
        cached_ok, cached_output = repair_git.cached_diff_check()
        atomic_write_text(run_dir / "repair-check-git-diff-cached.log", cached_output or "git diff --cached --check passed\n")
        if not cached_ok or self._product_snapshot() != product_before:
            self.transition(
                state, "SUPERVISOR_REPAIR_FAILED",
                "Staged supervisor repair failed final product fingerprint or diff validation.",
            )
            return
        commit = repair_git.commit_staged(f"Repair dev supervisor for {ticket} diagnosis")
        product_final = self._product_snapshot()
        if product_final != product_before or any(
            not (self._is_engine_repair_path(path) if external_repair else self._is_supervisor_control_path(path))
            for path in repair_git.changed_files_between(repair["starting_head"], commit)
        ):
            self.transition(
                state, "SUPERVISOR_REPAIR_FAILED",
                "Post-commit product fingerprint or supervisor-only commit boundary failed closed.",
            )
            return
        repair.update({
            "status": "committed", "commit": commit,
            "product_snapshot_after": product_final,
            "product_fingerprint_after": product_final["fingerprint"],
        })
        diagnostic["supervisor_repair_commit"] = commit
        diagnostic["repair_commit"] = commit
        diagnostic["repair_repository"] = "external" if external_repair else "embedded"
        diagnostic["product_fingerprint_after_repair"] = product_final["fingerprint"]
        if self._route_post_repair_completion(state, diagnostic):
            state.setdefault("diagnostic_history", []).append(dict(diagnostic))
            self.save_state(state)
            return
        diagnostic["resulting_transition"] = "QUOTA_CHECK_REQUIRED -> DIAGNOSTIC_PENDING"
        state.setdefault("diagnostic_history", []).append(dict(diagnostic))
        next_diagnostic = {
            "status": "pending", "ticket": ticket,
            "triggered_at": isoformat(self.now()),
            "trigger": "validated_supervisor_repair_requires_reclassification",
            "origin_phase": "SUPERVISOR_REPAIR",
            "origin_recovery_context": diagnostic.get("origin_recovery_context"),
            "product_snapshot_before": product_final,
            "product_fingerprint_before": product_final["fingerprint"],
            "repair_commit": commit,
            "repair_repository": "external" if external_repair else "embedded",
        }
        self.transition(
            state, "QUOTA_CHECK_REQUIRED",
            "Supervisor-only repair passed validation and was committed. Its quota observation was consumed; "
            "fresh quota is required for diagnostic reclassification.\n" + quota_refresh_instructions(None),
            diagnostic=next_diagnostic, quota_resume_phase="DIAGNOSTIC_PENDING",
            pending_role="diagnostic",
        )

    def _recover_invocation(self, state: dict[str, Any]) -> bool:
        active = state.get("active_run") or {}
        run_dir = self.runs_dir / str(active.get("id", ""))
        invocation_path = run_dir / "invocation.json"
        if not invocation_path.exists():
            outcome_path = run_dir / "process-outcome.json"
            events_path = run_dir / "events.jsonl"
            report_path = run_dir / "final-report.json"
            if outcome_path.exists():
                invocation = read_json(outcome_path)
            elif report_path.exists() and events_path.exists() and any(
                isinstance(event, dict) and event.get("type") == "turn.completed"
                for event in _jsonl_objects(events_path)
            ):
                invocation = {
                    "completed": True, "exit_status": 0, "rate_limited": False,
                    "error": "reconciled from final report and turn.completed event",
                }
            else:
                if events_path.exists() and events_path.stat().st_size and not active.get("accounting_recorded"):
                    self._checkpoint_data(state)["model_invocations"] += 1
                    active["accounting_recorded"] = True
                self.transition(
                    state, "INTERRUPTED",
                    "Invocation completion is absent; it may never have started or may have failed mid-run. "
                    "Partial changes are preserved. Explicit resume will use a same-ticket recovery prompt.",
                    recovery_context={
                        "kind": "model", "role": active.get("role", "implementation"),
                        "ticket": active.get("ticket", state["current_ticket"]),
                        "starting_head": active.get("starting_head", state.get("starting_head")),
                        "fingerprint": self.git.fingerprint(), "prior_run_id": active.get("id"),
                        "reason": "missing_completion_record", "partial_files": self.git.changed_files(),
                    },
                )
                return False
        else:
            invocation = read_json(invocation_path)
        if not invocation.get("completed"):
            self.transition(
                state, "INTERRUPTED",
                f"Invocation was interrupted ({invocation.get('interrupt_reason', 'unknown')}); explicit same-ticket recovery is required.",
                recovery_context={
                    "kind": "model", "role": active.get("role", "implementation"),
                    "ticket": active.get("ticket", state["current_ticket"]),
                    "starting_head": active.get("starting_head", state.get("starting_head")),
                    "fingerprint": self.git.fingerprint(), "prior_run_id": active.get("id"),
                    "reason": invocation.get("interrupt_reason", "interrupted"),
                    "partial_files": self.git.changed_files(),
                },
            )
            return False
        report = None
        report_path = run_dir / "final-report.json"
        if report_path.exists():
            try:
                report = read_json(report_path)
            except SupervisorError:
                report = None
        usage_path = run_dir / "usage.json"
        if usage_path.exists():
            recovered_usage = read_json(usage_path)
        else:
            events_path = run_dir / "events.jsonl"
            recovered_usage = (
                parse_usage_lines(events_path.read_text(encoding="utf-8", errors="replace").splitlines())
                if events_path.exists() else {}
            )
            atomic_write_json(usage_path, recovered_usage)
        active.update({
            "invocation_completed": True,
            "exit_code": invocation.get("exit_status", 1),
            "rate_limited": invocation.get("rate_limited", False),
            "error": invocation.get("error", ""),
            "report": report,
            "usage": recovered_usage,
            "changed_files": self.git.changed_files(),
            "post_invocation_fingerprint": self.git.fingerprint(),
            "duration_seconds": float(invocation.get("duration_seconds", 0) or 0),
            "finished_at": invocation.get("finished_at"),
            "warning_emitted": bool(invocation.get("warning_emitted", False)),
        })
        if not active.get("accounting_recorded"):
            checkpoint = self._checkpoint_data(state)
            checkpoint["model_invocations"] += 1
            self._add_active_runtime(state, active["duration_seconds"])
            self._record_timing("model_invocations", {
                "at": isoformat(self.now()), "role": active["role"], "ticket": active["ticket"],
                "duration_seconds": active["duration_seconds"], "interrupted": False,
                "architecture_escalation": active["role"] == "architecture",
                "reconciled_after_crash": True,
            })
            active["accounting_recorded"] = True
        self.save_state(state)
        self._process_invocation(state)
        return True

    def _process_invocation(self, state: dict[str, Any]) -> None:
        active = state["active_run"]
        role, ticket = active["role"], active["ticket"]
        if active.get("rate_limited"):
            self.transition(
                state, "QUOTA_EXHAUSTED",
                "Codex reported a rate/usage limit. No retry was attempted. Refresh quota only after trusted status confirms availability.",
                quota_resume_phase="READY" if role == "implementation" else "ARCHITECTURE_PENDING",
                pending_role=role, quota_exhausted_at=isoformat(self.now()),
            )
            return
        if active.get("exit_code") != 0:
            self.transition(state, "INVOCATION_FAILED", f"{role} Codex process failed: {active.get('error') or 'no detail'}")
            return
        errors = validate_report(active.get("report"), role, ticket)
        if errors:
            self.transition(state, "REPORT_INVALID", "Structured report failed closed: " + "; ".join(errors))
            return
        report = active["report"]
        preserved = active.get("preserved_implementation_checkpoint")
        if role == "architecture" and isinstance(preserved, dict) and preserved.get("scope_review") is True:
            self._process_protected_scope_review(state)
            return
        if report["product_decision_required"]:
            self.transition(
                state, "HUMAN_GATE",
                "A genuine product decision is required: " + "; ".join(report["blockers"] or [report["summary"]]),
                gate={"kind": "product_decision", "head": self.git.head(), "ticket": ticket},
            )
            return
        evidence_gate = self._human_evidence_gate_policy(ticket) if role == "implementation" else None
        if (
            role == "implementation"
            and report["status"] == "blocked"
            and evidence_gate is not None
            and report["architecture_deviation"] is False
            and report["ambiguity"] is False
        ):
            self._enter_human_evidence_gate(state, evidence_gate)
            return
        if role == "implementation" and (report["architecture_deviation"] or report["ambiguity"]):
            if self.git.changed_files():
                self.transition(
                    state, "GIT_BLOCKED",
                    "Terra reported an architecture blocker after changing files. Changes were preserved; cleanly separate or commit/revert them manually before architecture review.",
                )
                return
            self.transition(
                state, "ARCHITECTURE_PENDING", "Implementation blocker routed to bounded architecture review.",
                blocked_report=report, active_run=None, starting_head=None,
            )
            return
        if role == "implementation" and report["status"] == "environment_blocked":
            if not self.git.changed_files():
                self.transition(state, "IMPLEMENTATION_FAILED", "Environment-blocked implementation made no recoverable changes.")
                return
            handoff = self._environment_verification_handoff(active)
            if handoff is not None:
                active["host_verification_handoff"] = handoff
                self.transition(
                    state, "VERIFYING",
                    "Environment limitation is owned by mandatory deterministic host verification; "
                    "acceptance remains unresolved until that verification passes.",
                    verification_role=role,
                )
                return
            self.transition(
                state, "RECOVER_MODEL",
                "Implementation is blocked only by a declared environment capability; preserving work for same-ticket recovery.",
                recovery_context={
                    "kind": "environment", "role": role, "ticket": ticket,
                    "starting_head": active["starting_head"], "fingerprint": self.git.fingerprint(),
                    "prior_run_id": active["id"], "reason": "environment_capability",
                    "preserved_files": self.git.changed_files(),
                    "host_verification_required": False,
                    "host_verification_unavailable": (
                        "No configured mandatory ticket host check matched the reported capability."
                    ),
                },
            )
            return
        if report["status"] != "pass":
            phase = "IMPLEMENTATION_FAILED" if role == "implementation" else "ARCHITECTURE_FAILED"
            self.transition(state, phase, f"{role} report status is {report['status']}: {report['summary']}")
            return
        required_true = ["acceptance_passed", "tests_passed", "next_ticket_safe"]
        if role == "implementation" and any(not report[field] for field in required_true):
            self.transition(state, "REPORT_INVALID", "PASS report did not assert all implementation completion gates")
            return
        if report["architecture_deviation"] or report["ambiguity"]:
            self.transition(state, "REPORT_INVALID", "PASS report also asserted architecture deviation or ambiguity")
            return
        self.transition(state, "VERIFYING", f"Running deterministic checks after {role} PASS", verification_role=role)

    def _process_protected_scope_review(self, state: dict[str, Any]) -> None:
        """Route one read-only architecture decision about an exact protected diff."""
        review = state["active_run"]
        report = review["report"]
        preserved = review.get("preserved_implementation_checkpoint") or {}
        source_active = preserved.get("source_active")
        protected_paths = preserved.get("protected_paths")
        role_changed = review.get("role_changed_files")
        checkpoint_error = self._validated_protected_scope_checkpoint(
            state, source_active, protected_paths,
        )
        if (
            checkpoint_error is not None
            or not self._preserved_paths_match(preserved)
            or role_changed != []
            or report.get("files_changed") != []
        ):
            self.transition(
                state, "GIT_BLOCKED",
                "Protected-scope architecture review was not read-only or its preserved implementation "
                "checkpoint is no longer exact"
                + (f": {checkpoint_error}" if checkpoint_error else "."),
            )
            return

        decision_flags_clear = (
            report.get("architecture_deviation") is False
            and report.get("ambiguity") is False
        )
        if report.get("product_decision_required") is True:
            if report.get("status") != "blocked":
                self.transition(
                    state, "REPORT_INVALID",
                    "Protected-scope architecture review requested a human decision without status=blocked.",
                )
                return
            self.transition(
                state, "HUMAN_GATE",
                "Protected-path review found a genuine architecture/product decision is required: "
                + "; ".join(report.get("blockers") or [report["summary"]]),
                gate={
                    "kind": "product_decision", "source": "protected_scope_review",
                    "head": self.git.head(), "ticket": state["current_ticket"],
                    "implementation_fingerprint": preserved.get("fingerprint"),
                    "protected_paths": list(protected_paths),
                },
            )
            return

        if report.get("status") == "pass":
            if (
                not decision_flags_clear
                or any(
                    report.get(field) is not True
                    for field in ("acceptance_passed", "tests_passed", "next_ticket_safe")
                )
            ):
                self.transition(
                    state, "REPORT_INVALID",
                    "Protected-scope architecture approval contradicted its PASS decision fields.",
                )
                return
            quota_authorization = review.get("quota_authorization")
            authorization = {
                "status": "approved",
                "ticket": state["current_ticket"],
                "implementation_run_id": source_active["id"],
                "implementation_starting_head": source_active["starting_head"],
                "implementation_fingerprint": source_active["post_invocation_fingerprint"],
                "protected_paths": list(protected_paths),
                "architecture_run_id": review["id"],
                "architecture_report": deepcopy(report),
                "quota_authorization": deepcopy(quota_authorization),
            }
            restored = deepcopy(source_active)
            restored["protected_scope_authorization"] = authorization
            state.setdefault("protected_scope_reviews", []).append(deepcopy(authorization))
            self.transition(
                state, "SCOPE_PENDING",
                "Architecture review authorized only the exact protected implementation checkpoint; "
                "the deterministic scope gate will re-evaluate it.",
                active_run=restored, starting_head=restored["starting_head"],
                recovery_context=None,
                architecture_resolution={
                    "kind": "protected_scope_approval", "run_id": review["id"],
                    "report": deepcopy(report), "protected_paths": list(protected_paths),
                },
            )
            return

        if report.get("status") == "blocked" and decision_flags_clear:
            restored = deepcopy(source_active)
            context = {
                "kind": "protected_scope_rework", "role": "implementation",
                "ticket": state["current_ticket"],
                "starting_head": restored["starting_head"],
                "fingerprint": restored["post_invocation_fingerprint"],
                "prior_run_id": restored["id"],
                "reason": "architecture_rejected_protected_changes",
                "preserved_files": list(restored["changed_files"]),
                "protected_paths": list(protected_paths),
                "architecture_review": {
                    "run_id": review["id"], "summary": report["summary"],
                    "blockers": list(report["blockers"]),
                },
            }
            self.transition(
                state, "RECOVER_MODEL",
                "Architecture review rejected authorization for the protected changes; bounded same-ticket "
                "product recovery must remove or rework them before verification and scope run again.",
                active_run=restored, starting_head=restored["starting_head"],
                recovery_context=context,
                blocked_report=deepcopy(report),
                architecture_resolution={
                    "kind": "protected_scope_rework", "run_id": review["id"],
                    "report": deepcopy(report),
                },
            )
            return

        self.transition(
            state, "ARCHITECTURE_FAILED",
            "Protected-scope architecture review did not return approval, bounded product rework, or a human gate.",
        )

    @staticmethod
    def _matches_all(patterns: Any, text: str) -> bool:
        if not isinstance(patterns, list) or not patterns:
            return False
        try:
            return all(isinstance(pattern, str) and re.search(pattern, text) for pattern in patterns)
        except re.error:
            return False

    def _environment_verification_handoff(
        self, active: dict[str, Any], *, capability: str | None = None,
    ) -> dict[str, Any] | None:
        """Return a policy-owned host handoff, or fail closed with ``None``."""
        report = active.get("report") or {}
        if (
            active.get("role") != "implementation"
            or report.get("status") != "environment_blocked"
            or report.get("architecture_deviation") is not False
            or report.get("ambiguity") is not False
            or report.get("product_decision_required") is not False
            or report.get("acceptance_passed") is not False
            or report.get("tests_passed") is not False
            or report.get("next_ticket_safe") is not False
        ):
            return None
        actual = self.git.changed_files()
        if (
            not actual
            or actual != sorted(report.get("files_changed", []))
            or actual != sorted(active.get("changed_files", []))
        ):
            return None
        blockers = report.get("blockers")
        checks_run = report.get("checks_run")
        if not isinstance(blockers, list) or not blockers or not isinstance(checks_run, list) or not checks_run:
            return None
        report_evidence = "\n".join([*blockers, str(report.get("summary", "")), *checks_run])

        definitions = self.policy.get("host_verification_capabilities", {})
        ticket_checks = self.policy.get("ticket_verification_commands", {}).get(active.get("ticket"), [])
        candidates: list[dict[str, Any]] = []
        for name, definition in definitions.items():
            if capability is not None and name != capability:
                continue
            owned_checks = [
                check for check in ticket_checks
                if check.get("mandatory") is True
                and name in check.get("host_capabilities", [])
                and (
                    (isinstance(check.get("required_output_patterns"), list) and check["required_output_patterns"])
                    or isinstance(check.get("unittest_evidence"), dict)
                )
            ]
            if not owned_checks:
                continue
            blocker_patterns = definition.get("blocker_patterns")
            if not self._matches_all(blocker_patterns, report_evidence):
                continue
            if not self._matches_all(definition.get("completion_summary_patterns"), str(report.get("summary", ""))):
                continue
            report_checks = "\n".join(checks_run)
            if not self._matches_all(definition.get("required_report_check_patterns"), report_checks):
                continue
            candidates.append({
                "capability": name,
                "required_checks": [check["name"] for check in owned_checks],
                "report_status": "environment_blocked",
                "acceptance_resolved": False,
            })
        return candidates[0] if len(candidates) == 1 else None

    def _post_repair_completion_handoff(
        self, state: dict[str, Any], diagnostic: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Authorize ordinary verification after repairing an unmatched environment route."""
        active = state.get("active_run") or {}
        report = active.get("report") or {}
        context = diagnostic.get("origin_recovery_context") or {}
        repair_commit = diagnostic.get("repair_commit")
        supplied = diagnostic.get("evidence_run_ids")
        current_snapshot = self._product_snapshot()
        run_id = diagnostic.get("run_id")
        artifact = (
            self._diagnostic_artifact(run_id, str(active.get("ticket", "")))
            if isinstance(run_id, str) else None
        )
        checks = list(self.policy.get("verification_commands", []))
        checks.extend(
            self.policy.get("ticket_verification_commands", {}).get(active.get("ticket"), [])
        )
        names = [check.get("name") for check in checks]
        if (
            diagnostic.get("status") != "classified"
            or diagnostic.get("classification") != "SUPERVISOR_BUG"
            or diagnostic.get("trigger") != "validated_supervisor_repair_requires_reclassification"
            or diagnostic.get("origin_phase") != "SUPERVISOR_REPAIR"
            or not isinstance(repair_commit, str)
            or not repair_commit
            or not self._repair_commit_is_current(diagnostic)
            or not self._diagnostic_lineage_contains_run(
                supplied, active.get("id"), str(active.get("ticket", "")), current_snapshot,
            )
            or artifact is None
            or artifact.get("report") != diagnostic.get("report")
            or artifact.get("product_snapshot") != current_snapshot
            or active.get("role") != "implementation"
            or active.get("ticket") != state.get("current_ticket")
            or validate_report(report, "implementation", str(active.get("ticket", "")))
            or report.get("status") != "environment_blocked"
            or not report.get("blockers")
            or not report.get("checks_run")
            or context.get("kind") != "environment"
            or context.get("role") != "implementation"
            or context.get("ticket") != active.get("ticket")
            or context.get("prior_run_id") != active.get("id")
            or context.get("starting_head") != active.get("starting_head")
            or context.get("fingerprint") != active.get("post_invocation_fingerprint")
            or context.get("preserved_files") != active.get("changed_files")
            or diagnostic.get("product_snapshot_before") != current_snapshot
            or diagnostic.get("product_fingerprint_after") != current_snapshot["fingerprint"]
            or state.get("gate") is not None
            or self._environment_verification_handoff(active) is not None
            or not self._model_checkpoint_matches(active)
            or not names
            or any(not isinstance(name, str) or not name for name in names)
            or len(names) != len(set(names))
            or any(check.get("host_capabilities") for check in checks)
        ):
            return None
        return {
            "kind": "post_repair_ticket_completion",
            "diagnostic_run_id": diagnostic.get("run_id"),
            "repair_commit": repair_commit,
            "required_checks": names,
            "acceptance_resolved": False,
        }

    def _diagnostic_lineage_contains_run(
        self, supplied: Any, target_run_id: Any, ticket: str,
        expected_snapshot: dict[str, Any],
    ) -> bool:
        """Validate a direct or one-generation diagnostic reference to an implementation run."""
        if not isinstance(supplied, list) or not all(isinstance(item, str) for item in supplied):
            return False
        if target_run_id in supplied:
            return True
        if not isinstance(target_run_id, str) or not target_run_id:
            return False
        for run_id in supplied:
            artifact = self._diagnostic_artifact(run_id, ticket)
            if (
                artifact is None
                or artifact.get("product_snapshot") != expected_snapshot
                or (artifact.get("report") or {}).get("classification") != "SUPERVISOR_BUG"
            ):
                continue
            prior_supplied = (artifact.get("evidence") or {}).get("supplied_run_ids")
            if isinstance(prior_supplied, list) and target_run_id in prior_supplied:
                return True
        return False

    def _route_post_repair_completion(
        self, state: dict[str, Any], diagnostic: dict[str, Any],
    ) -> bool:
        handoff = self._post_repair_completion_handoff(state, diagnostic)
        if handoff is None:
            return False
        state["active_run"]["diagnostic_completion_handoff"] = handoff
        diagnostic["resulting_transition"] = "VERIFYING"
        self.transition(
            state, "VERIFYING",
            "Validated supervisor repair removed an unmatched environment-only blocker; "
            "configured deterministic checks will resolve ticket acceptance without another product recovery.",
            diagnostic=diagnostic, recovery_context=None, verification_role="implementation",
        )
        return True

    def _diagnostic_artifact(self, run_id: str, ticket: str) -> dict[str, Any] | None:
        """Return one content-validated diagnostic artifact, or fail closed."""
        if Path(run_id).name != run_id or not run_id.endswith(f"-diagnostic-{ticket.lower()}"):
            return None
        run_dir = self.runs_dir / run_id
        try:
            report = read_json(run_dir / "final-report.json")
            evidence = read_json(run_dir / "diagnostic-evidence.json")
        except SupervisorError:
            return None
        supplied = evidence.get("supplied_run_ids")
        if not isinstance(supplied, list) or validate_diagnostic_report(report, ticket, supplied):
            return None
        snapshot = (evidence.get("git") or {}).get("product_snapshot")
        if not isinstance(snapshot, dict) or set(snapshot) != {"entries", "fingerprint"}:
            return None
        entries = snapshot.get("entries")
        if not isinstance(entries, list) or snapshot.get("fingerprint") != self._snapshot_fingerprint({"entries": entries}):
            return None
        return {"report": report, "evidence": evidence, "product_snapshot": snapshot}

    def _failed_host_attempts(self, ticket: str) -> list[dict[str, Any]] | None:
        """Derive prior failed mandatory host checks and their product snapshots."""
        configured = {
            check.get("name"): check
            for check in self.policy.get("ticket_verification_commands", {}).get(ticket, [])
            if check.get("mandatory") is True and check.get("host_capabilities")
        }
        attempts: list[dict[str, Any]] = []
        diagnostic_artifacts: dict[str, dict[str, Any]] = {}
        for path in sorted(self.runs_dir.glob(f"*-diagnostic-{ticket.lower()}")):
            artifact = self._diagnostic_artifact(path.name, ticket)
            if artifact is None:
                try:
                    raw = read_json(path / "final-report.json")
                except SupervisorError:
                    continue
                if raw.get("classification") == "HOST_VERIFICATION_REQUIRED":
                    return None
                continue
            diagnostic_artifacts[path.name] = artifact

        for run_dir in sorted(self.runs_dir.glob(f"*-implementation-{ticket.lower()}")):
            checks_path = run_dir / "checks.json"
            if not checks_path.exists():
                continue
            try:
                checks = json.loads(checks_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            if not isinstance(checks, list):
                return None
            for result in checks:
                if not isinstance(result, dict) or result.get("name") not in configured:
                    continue
                check = configured[result["name"]]
                if result.get("passed") is True:
                    continue
                if (
                    result.get("command") != check.get("command")
                    or result.get("passed") is not False
                    or type(result.get("exit_status")) is not int
                    or result["exit_status"] == 0
                    or sorted(result.get("host_capabilities", []))
                    != sorted(check.get("host_capabilities", []))
                ):
                    return None
                fingerprint = result.get("product_fingerprint")
                host_diagnostics = [
                    (run_id, artifact)
                    for run_id, artifact in diagnostic_artifacts.items()
                    if artifact["report"]["classification"] == "HOST_VERIFICATION_REQUIRED"
                    and run_dir.name in artifact["report"]["evidence_run_ids"]
                    and run_id > run_dir.name
                ]
                if not isinstance(fingerprint, str) or not fingerprint:
                    if len(host_diagnostics) != 1:
                        return None
                    fingerprint = host_diagnostics[0][1]["product_snapshot"]["fingerprint"]
                attempts.append({
                    "run_id": run_dir.name,
                    "diagnostic_run_id": host_diagnostics[0][0] if len(host_diagnostics) == 1 else None,
                    "product_fingerprint": fingerprint,
                })
        return attempts

    def _diagnostic_verification_handoff(
        self, state: dict[str, Any], *, capability: str | None = None,
    ) -> dict[str, Any] | None:
        """Authorize a diagnostic host handoff only for a new or repaired snapshot."""
        active = state.get("active_run") or {}
        diagnostic = state.get("diagnostic") or {}
        handoff = self._environment_verification_handoff(active, capability=capability)
        current_snapshot = self._product_snapshot()
        if (
            handoff is None
            or diagnostic.get("classification") != "HOST_VERIFICATION_REQUIRED"
            or diagnostic.get("ticket") != state.get("current_ticket")
            or diagnostic.get("product_snapshot_before") != current_snapshot
            or diagnostic.get("product_fingerprint_after") != current_snapshot["fingerprint"]
            or not self._model_checkpoint_matches(active)
        ):
            return None

        attempts = self._failed_host_attempts(state["current_ticket"])
        if attempts is None:
            return None
        current_run_id = diagnostic.get("run_id")
        if not isinstance(current_run_id, str) or not current_run_id:
            return None
        prior = [item for item in attempts if item["run_id"] < current_run_id]
        if not prior:
            return handoff
        latest = prior[-1]
        if latest["product_fingerprint"] == current_snapshot["fingerprint"]:
            return None

        supplied = diagnostic.get("evidence_run_ids")
        completed = diagnostic.get("completed_recovery_run_ids")
        if not isinstance(supplied, list) or not isinstance(completed, list):
            return None
        fixes: list[str] = []
        for run_id in supplied:
            artifact = self._diagnostic_artifact(run_id, state["current_ticket"])
            if artifact is None or artifact["report"]["classification"] != "PRODUCT_FIX":
                continue
            referenced = artifact["report"]["evidence_run_ids"]
            if latest["run_id"] in referenced or latest["diagnostic_run_id"] in referenced:
                fixes.append(run_id)
        if len(fixes) != 1:
            return None
        fix_run_id = fixes[0]
        recovery_ids = [
            run_id for run_id in completed
            if isinstance(run_id, str) and fix_run_id < run_id < current_run_id
        ]
        quota = active.get("quota_authorization") or {}
        if (
            active.get("id") not in recovery_ids
            or active.get("id") not in supplied
            or active.get("recovery") is not True
            or quota.get("recovery") is not True
            or quota.get("invocation_id") != active.get("id")
            or quota not in state.get("quota_consumptions", [])
            or not any(
                item.get("from") == "DIAGNOSTIC_REVIEW"
                and item.get("to") == "QUOTA_CHECK_REQUIRED"
                and "concrete product fix" in str(item.get("message", ""))
                for item in state.get("history", []) if isinstance(item, dict)
            )
        ):
            return None
        return handoff

    @staticmethod
    def _unittest_output_errors(evidence: dict[str, Any], output: str) -> list[str]:
        errors: list[str] = []
        required = evidence.get("required_tests")
        expected_count = evidence.get("expected_test_count")
        if (
            not isinstance(required, list)
            or not required
            or any(not isinstance(name, str) or not name for name in required)
            or len(required) != len(set(required))
            or type(expected_count) is not int
            or expected_count < len(required)
        ):
            return ["invalid unittest evidence policy"]

        header_pattern = re.compile(r"(?m)^test[A-Za-z0-9_]+ \(")
        headers = list(header_pattern.finditer(output))
        for name in required:
            matches = [match for match in headers if output.startswith(name + " ", match.start())]
            if len(matches) != 1:
                errors.append(f"required unittest {name!r} appeared {len(matches)} times")
                continue
            start = matches[0].start()
            following = next((match.start() for match in headers if match.start() > start), len(output))
            block = output[start:following]
            outcomes = re.findall(
                r"(?m)^(?:.* \.\.\. )?(ok|FAIL|ERROR|skipped\b[^\n]*)\s*$",
                block,
            )
            if not outcomes:
                errors.append(f"required unittest {name!r} has no terminal outcome")
            elif outcomes[-1] != "ok":
                errors.append(f"required unittest {name!r} ended with {outcomes[-1]!r}, not 'ok'")

        summaries = list(re.finditer(r"(?m)^Ran ([0-9]+) tests? in [0-9.]+s\s*$", output))
        if len(summaries) != 1:
            errors.append(f"unittest completion summary appeared {len(summaries)} times")
            return errors
        observed_count = int(summaries[0].group(1))
        if observed_count != expected_count:
            errors.append(f"unittest ran {observed_count} tests; expected {expected_count}")
        final_statuses = re.findall(
            r"(?m)^(OK(?: \([^\n]*\))?|FAILED(?: \([^\n]*\))?)\s*$",
            output[summaries[0].end():],
        )
        if len(final_statuses) != 1 or not final_statuses[0].startswith("OK"):
            errors.append("unittest suite did not finish with one successful OK status")
        return errors

    @staticmethod
    def _verification_output_errors(check: dict[str, Any], output: str) -> list[str]:
        errors: list[str] = []
        if isinstance(check.get("unittest_evidence"), dict):
            errors.extend(Supervisor._unittest_output_errors(check["unittest_evidence"], output))
        try:
            for pattern in check.get("required_output_patterns", []):
                if re.search(pattern, output) is None:
                    errors.append(f"required output did not match {pattern!r}")
            for pattern in check.get("forbidden_output_patterns", []):
                if re.search(pattern, output) is not None:
                    errors.append(f"forbidden output matched {pattern!r}")
        except re.error as error:
            errors.append(f"invalid verification output policy: {error}")
        return errors

    def _run_verification(self, state: dict[str, Any]) -> bool:
        active = state["active_run"]
        run_dir = self.runs_dir / active["id"]
        results = active.setdefault("verification_results", [])
        passed_names = {item["name"] for item in results if item.get("passed")}
        verification_started = time.monotonic()
        checks = list(self.policy["verification_commands"])
        checks.extend(self.policy.get("ticket_verification_commands", {}).get(active["ticket"], []))
        for check in checks:
            if check["name"] in passed_names:
                continue
            output_path = run_dir / f"check-{len(results) + 1:02d}.log"
            self.save_state(state)
            try:
                command_result = self.command_runner.run(list(check["command"]), self.root, output_path)
            except KeyboardInterrupt:
                command_result = CommandResult(130, interrupted=True, interrupt_reason="keyboard_interrupt")
            if isinstance(command_result, CommandResult):
                return_code = command_result.exit_code
                command_duration = command_result.duration_seconds
                interrupted = command_result.interrupted
                interrupt_reason = command_result.interrupt_reason
            else:
                return_code = command_result
                command_duration = 0.0
                interrupted = False
                interrupt_reason = ""
            if interrupted:
                elapsed = max(command_duration, time.monotonic() - verification_started)
                self._add_active_runtime(state, elapsed)
                self._record_timing("verification", {
                    "at": isoformat(self.now()), "ticket": active["ticket"],
                    "role": active["role"], "duration_seconds": elapsed,
                    "interrupted": True,
                })
                self.transition(
                    state, "INTERRUPTED",
                    f"Verification interrupted ({interrupt_reason}); no commit occurred and changes are preserved. "
                    "Safe to power off. Resume with ./dev resume.",
                    recovery_context={
                        "kind": "verification", "ticket": active["ticket"],
                        "starting_head": active["starting_head"],
                        "fingerprint": self.git.fingerprint(), "reason": interrupt_reason,
                    },
                )
                self._emit(active["ticket"], "verification", "INTERRUPTED · safe to power off · resume: ./dev resume")
                return False
            try:
                output = output_path.read_text(encoding="utf-8", errors="replace")
            except OSError as error:
                output = ""
                evidence_errors = [f"verification output unavailable: {error}"]
            else:
                evidence_errors = self._verification_output_errors(check, output)
            passed = return_code == 0 and not evidence_errors
            result = {
                "name": check["name"], "command": check["command"],
                "exit_status": return_code, "passed": passed,
                "duration_seconds": command_duration, "log": output_path.name,
            }
            if check.get("host_capabilities"):
                result["host_capabilities"] = list(check["host_capabilities"])
                result["product_fingerprint"] = self._product_snapshot()["fingerprint"]
            if evidence_errors:
                result["evidence_errors"] = evidence_errors
            results.append(result)
            atomic_write_json(run_dir / "checks.json", results)
            self.save_state(state)
            if not passed:
                detail = f" Output evidence failed closed: {'; '.join(evidence_errors)}" if evidence_errors else ""
                self.transition(
                    state, "VERIFICATION_FAILED",
                    f"Deterministic verification failed: {check['name']}.{detail} See {output_path.relative_to(self.root)}",
                )
                return False
        diff_ok, diff_output = self.git.diff_check()
        diff_path = run_dir / "check-git-diff.log"
        atomic_write_text(diff_path, diff_output or "git diff --check passed\n")
        if not diff_ok:
            self.transition(state, "VERIFICATION_FAILED", f"git diff --check failed. See {diff_path.relative_to(self.root)}")
            return False
        if active.get("report", {}).get("status") == "environment_blocked":
            handoff = active.get("host_verification_handoff")
            completion = active.get("diagnostic_completion_handoff")
            if isinstance(handoff, dict):
                handoff["acceptance_resolved"] = True
            elif isinstance(completion, dict):
                expected = self._post_repair_completion_handoff(
                    state, state.get("diagnostic") or {},
                )
                if expected is not None:
                    expected["acceptance_resolved"] = completion.get("acceptance_resolved")
                if completion != expected:
                    self.transition(
                        state, "VERIFICATION_FAILED",
                        "Post-repair completion handoff is stale or contradictory.",
                    )
                    return False
                completion["acceptance_resolved"] = True
            else:
                self.transition(
                    state, "VERIFICATION_FAILED",
                    "Environment-blocked verification completed without a valid acceptance handoff.",
                )
                return False
        elapsed = time.monotonic() - verification_started
        active["verification_duration_seconds"] = active.get("verification_duration_seconds", 0.0) + elapsed
        self._add_active_runtime(state, elapsed)
        self._record_timing("verification", {
            "at": isoformat(self.now()), "ticket": active["ticket"],
            "role": active["role"], "duration_seconds": elapsed,
            "interrupted": False,
        })
        self.save_state(state)
        return True

    def run_evidence_checks(self, ticket: str) -> dict[str, Any]:
        """Run configured evidence checks without invoking a model or changing phase."""
        state = self.load_state()
        evidence_policy = self._human_evidence_gate_policy(ticket)
        legacy_failed = state.get("phase") == "IMPLEMENTATION_FAILED"
        evidence_gate = (
            state.get("phase") == "HUMAN_GATE"
            and isinstance(state.get("gate"), dict)
            and state["gate"].get("kind") == "evidence"
        )
        if not legacy_failed and not evidence_gate:
            raise SupervisorError("evidence checks require a preserved blocked run or evidence HUMAN_GATE")
        if state.get("current_ticket") != ticket:
            raise SupervisorError(f"evidence checks target {ticket}, but current ticket is {state.get('current_ticket')}")
        active = state.get("active_run")
        if not isinstance(active, dict) or active.get("ticket") != ticket or active.get("role") != "implementation":
            raise SupervisorError("evidence checks require the preserved implementation run")
        report = active.get("report")
        if not isinstance(report, dict) or report.get("status") != "blocked":
            raise SupervisorError("evidence checks require a blocked implementation report")
        if not self._model_checkpoint_matches(active):
            raise SupervisorError("preserved implementation tree no longer matches the evidence checkpoint")
        checks = self.policy.get("evidence_check_commands", {}).get(ticket)
        if not isinstance(checks, list) or not checks:
            raise SupervisorError(f"no evidence checks are configured for {ticket}")
        run_dir = self.runs_dir / str(active["id"])
        results: list[dict[str, Any]] = []
        for index, check in enumerate(checks, start=1):
            if not isinstance(check, dict) or not isinstance(check.get("name"), str) or not isinstance(check.get("command"), list):
                raise SupervisorError(f"malformed evidence check policy for {ticket}")
            output_path = run_dir / f"evidence-check-{index:02d}.log"
            try:
                command_result = self.command_runner.run(list(check["command"]), self.root, output_path)
            except KeyboardInterrupt:
                raise SupervisorError(f"evidence check interrupted: {check['name']}")
            exit_status = command_result.exit_code if isinstance(command_result, CommandResult) else command_result
            try:
                output = output_path.read_text(encoding="utf-8", errors="replace")
            except OSError as error:
                output = ""
                evidence_errors = [f"evidence output unavailable: {error}"]
            else:
                evidence_errors = self._verification_output_errors(check, output)
            passed = exit_status == 0 and not evidence_errors
            result = {
                "name": check["name"], "command": check["command"],
                "exit_status": exit_status, "passed": passed,
                "log": output_path.name,
            }
            if evidence_errors:
                result["evidence_errors"] = evidence_errors
            results.append(result)
            if not passed:
                active["evidence_checks"] = results
                atomic_write_json(run_dir / "evidence-checks.json", results)
                self.transition(
                    state, "IMPLEMENTATION_FAILED",
                    f"Evidence check failed: {check['name']}. See {output_path.relative_to(self.root)}",
                    gate=None,
                )
                return state
        diff_ok, diff_output = self.git.diff_check()
        diff_path = run_dir / "evidence-check-git-diff.log"
        atomic_write_text(diff_path, diff_output or "git diff --check passed\n")
        if not diff_ok:
            active["evidence_checks"] = results
            atomic_write_json(run_dir / "evidence-checks.json", results)
            self.transition(
                state, "IMPLEMENTATION_FAILED",
                f"git diff --check failed. See {diff_path.relative_to(self.root)}",
                gate=None,
            )
            return state
        active["evidence_checks"] = results
        active["evidence_checks_passed"] = True
        atomic_write_json(run_dir / "evidence-checks.json", results)
        if evidence_policy is not None:
            if legacy_failed:
                self._enter_human_evidence_gate(state, evidence_policy)
            else:
                self.transition(
                    state, "HUMAN_GATE",
                    "Deterministic evidence checks passed; perform and record the owner live PASS/FAIL run. "
                    "No model was invoked and no ticket was completed.",
                )
        else:
            self.transition(
                state, "IMPLEMENTATION_FAILED",
                "Deterministic evidence checks passed; perform the owner live PASS/FAIL run. "
                "No model was invoked and no ticket was completed.",
            )
        return state

    def _scope_gate(self, state: dict[str, Any]) -> bool:
        active = state["active_run"]
        role = active["role"]
        report = active["report"]
        if report.get("status") == "environment_blocked":
            handoff = active.get("host_verification_handoff") or {}
            completion = active.get("diagnostic_completion_handoff") or {}
            acceptance = handoff if handoff else completion
            required = acceptance.get("required_checks")
            passed = {
                item.get("name") for item in active.get("verification_results", [])
                if item.get("passed")
            }
            if handoff:
                passed = {
                    item.get("name") for item in active.get("verification_results", [])
                    if item.get("passed") and item.get("host_capabilities")
                }
            if (
                acceptance.get("acceptance_resolved") is not True
                or not isinstance(required, list)
                or not required
                or any(name not in passed for name in required)
            ):
                self.transition(
                    state, "SCOPE_BLOCKED",
                    "Environment-blocked acceptance lacks every required successful verification result.",
                )
                return False
        all_changed = self.git.changed_files()
        preserved = active.get("preserved_implementation_checkpoint")
        if preserved is not None:
            if role != "architecture" or not self._preserved_paths_match(preserved):
                self.transition(
                    state, "GIT_BLOCKED",
                    "The preserved implementation checkpoint changed during architecture review.",
                )
                return False
            preserved_files = set(preserved["files"])
            actual = [path for path in all_changed if path not in preserved_files]
        else:
            actual = all_changed
        reported = sorted(report["files_changed"])
        if actual != reported:
            self.transition(
                state, "SCOPE_BLOCKED",
                f"Changed files do not exactly match the structured report. actual={actual!r}, reported={reported!r}",
            )
            return False
        if not actual:
            self.transition(state, "SCOPE_BLOCKED", f"{role} PASS produced no committable changes")
            return False
        if role == "implementation":
            forbidden = [
                path for path in actual
                if any(path == prefix or path.startswith(prefix) for prefix in self.policy["implementation_forbidden_paths"])
            ]
            if forbidden:
                authorization = active.get("protected_scope_authorization")
                if authorization is None:
                    self.transition(
                        state, "SCOPE_BLOCKED",
                        "Implementation changed protected architecture/OpenAPI/schema/tooling paths: " + ", ".join(forbidden),
                    )
                    return False
                authorization_error = self._protected_scope_authorization_error(
                    state, active, forbidden,
                )
                if authorization_error is not None:
                    self.transition(
                        state, "SCOPE_BLOCKED",
                        "Protected-path architecture authorization failed closed: " + authorization_error
                        + ". Operator reconciliation is required.",
                        scope_recovery_unavailable=authorization_error,
                    )
                    return False
            later_owned = self._later_ticket_owned_paths(active["ticket"])
            later_hits = [
                (path, owner)
                for path in actual
                for owned_path, owner in later_owned
                if path == owned_path or path.startswith(owned_path.rstrip("/") + "/") or path.startswith(owned_path + ".")
            ]
            if later_hits:
                details = ", ".join(f"{path} ({owner})" for path, owner in later_hits)
                self.transition(
                    state, "SCOPE_BLOCKED",
                    "Changes touch paths explicitly assigned to later tickets: " + details,
                )
                return False
        else:
            allowed = self.policy["architecture_allowed_paths"]
            outside = [path for path in actual if not any(path.startswith(prefix) for prefix in allowed)]
            if outside:
                self.transition(
                    state, "SCOPE_BLOCKED",
                    "Architecture review changed runtime or non-architecture files: " + ", ".join(outside),
                )
                return False
            reconciliation_error = self._periodic_plan_reconciliation_error(state, active, actual)
            if reconciliation_error is not None:
                self.transition(
                    state, "SCOPE_BLOCKED",
                    "Periodic plan reconciliation failed closed: " + reconciliation_error,
                )
                return False
        if self.git.fingerprint() != active["post_invocation_fingerprint"]:
            self.transition(
                state, "GIT_BLOCKED",
                "The working tree changed after the model invocation (possibly during checks); no commit was attempted.",
            )
            return False
        return True

    def _protected_scope_authorization_error(
        self, state: dict[str, Any], active: dict[str, Any], protected_paths: list[str],
    ) -> str | None:
        """Validate that Sol approved only this exact verified implementation checkpoint."""
        authorization = active.get("protected_scope_authorization")
        if not isinstance(authorization, dict):
            return "authorization is missing or malformed"
        report = authorization.get("architecture_report")
        quota = authorization.get("quota_authorization")
        if (
            authorization.get("status") != "approved"
            or authorization.get("ticket") != state.get("current_ticket")
            or authorization.get("implementation_run_id") != active.get("id")
            or authorization.get("implementation_starting_head") != active.get("starting_head")
            or authorization.get("implementation_fingerprint") != active.get("post_invocation_fingerprint")
            or authorization.get("protected_paths") != sorted(protected_paths)
            or self._protected_paths(active.get("changed_files")) != sorted(protected_paths)
            or validate_report(report, "architecture", state.get("current_ticket"))
            or report.get("status") != "pass"
            or report.get("files_changed") != []
            or report.get("product_decision_required") is not False
            or report.get("architecture_deviation") is not False
            or report.get("ambiguity") is not False
            or any(
                report.get(field) is not True
                for field in ("acceptance_passed", "tests_passed", "next_ticket_safe")
            )
        ):
            return "authorization does not match the exact ticket, fingerprint, protected paths, and approval semantics"
        run_id = authorization.get("architecture_run_id")
        if not isinstance(run_id, str) or not run_id or Path(run_id).name != run_id:
            return "architecture review identity is malformed"
        if (
            not isinstance(quota, dict)
            or quota.get("status") != "consumed"
            or quota.get("invocation_id") != run_id
            or quota.get("role") != "architecture"
            or quota.get("ticket") != state.get("current_ticket")
            or quota not in state.get("quota_consumptions", [])
        ):
            return "architecture review quota audit is missing or contradictory"
        try:
            invocation = read_json(self.runs_dir / run_id / "invocation.json")
            persisted_report = read_json(self.runs_dir / run_id / "final-report.json")
        except SupervisorError:
            return "durable architecture review artifacts are missing or malformed"
        if (
            invocation.get("completed") is not True
            or invocation.get("exit_status") != 0
            or invocation.get("rate_limited") is not False
            or persisted_report != report
            or not self._model_checkpoint_matches(active)
        ):
            return "durable architecture approval or implementation checkpoint is stale"
        return None

    def _later_ticket_owned_paths(self, current_ticket: str) -> list[tuple[str, str]]:
        """Extract only explicit repository paths from later ticket ownership lines."""
        ordered = self._plan_tickets()
        try:
            later = ordered[ordered.index(current_ticket) + 1:]
        except ValueError:
            return []
        current_owned = self._ticket_owned_paths(current_ticket)
        result: list[tuple[str, str]] = []
        for ticket in later:
            for path in self._ticket_owned_paths(ticket):
                shared = any(
                    path == owned
                    or path.startswith(owned.rstrip("/") + "/")
                    or owned.startswith(path.rstrip("/") + "/")
                    for owned in current_owned
                )
                if not shared:
                    result.append((path, ticket))
        return result

    def _ticket_owned_paths(self, ticket: str) -> list[str]:
        try:
            text = self._ticket_path(ticket).read_text(encoding="utf-8")
        except SupervisorError:
            return []
        line = next((item for item in text.splitlines() if item.startswith("- Files/modules:")), "")
        result: list[str] = []
        for quoted in re.findall(r"`([^`]+)`", line):
            for candidate in quoted.split(","):
                path = candidate.strip().rstrip(".")
                if path.startswith(("apps/", "adapters/", "docs/", "tests/")) and " " not in path:
                    result.append(path)
        documentation = re.search(
            r"(?ms)^## Documentation impact\s*$\s*(`[^`]+`|[^\n]+)", text,
        )
        if documentation and documentation.group(1).strip().lstrip("`").startswith("Required"):
            # Documentation governance requires behavior-changing tickets to
            # update maintained operator material in the same ticket. Protected
            # docs/architecture paths still pass through the earlier forbidden-
            # path review.
            result.append("docs/")
        return list(dict.fromkeys(result))

    def _commit_message(self, state: dict[str, Any]) -> str:
        active = state["active_run"]
        if active["role"] == "architecture":
            return f"Resolve {active['ticket']} architecture blocker"
        path = self._ticket_path(active["ticket"])
        slug = path.stem.split("-", 1)[1].replace("-", " ")
        return f"Implement {active['ticket']} {slug}"

    def _prepare_commit(self, state: dict[str, Any]) -> None:
        message = self._commit_message(state)
        invocation_head = state["active_run"]["starting_head"]
        commit_base = invocation_head
        current_head = self.git.head()
        if current_head != invocation_head and self.git.is_ancestor(invocation_head, current_head):
            intervening = self.git.changed_files_between(invocation_head, current_head)
            if intervening and all(self._is_supervisor_control_path(path) for path in intervening):
                commit_base = current_head
        self.transition(
            state, "COMMITTING", f"Commit prepared: {message}",
            pending_commit={
                "message": message,
                "starting_head": commit_base,
                "invocation_starting_head": invocation_head,
                "fingerprint": self.git.fingerprint(),
                "role": state["active_run"]["role"],
                "ticket": state["active_run"]["ticket"],
                "final_ticket": (
                    state["active_run"]["role"] == "implementation"
                    and state["active_run"]["ticket"] == self._current_epoch(state)["tickets"][-1]
                ),
            },
        )

    def _complete_plan_epoch(self, state: dict[str, Any], *, committed: str, pending: dict[str, Any]) -> None:
        """Durably reconcile the final verified commit into exactly one epoch completion."""
        epoch = self._current_epoch(state)
        ticket = pending["ticket"]
        if ticket != epoch["tickets"][-1]:
            raise SupervisorError("only the immutable epoch frontier may complete a plan")
        completion = epoch.get("completion")
        evidence = {
            "commit": committed,
            "ticket": ticket,
            "run_id": state["active_run"]["id"],
            "report": state["active_run"]["report"],
            "verification_results": state["active_run"].get("verification_results", []),
            "reason": "all immutable epoch tickets verified and committed",
        }
        if completion is not None and completion != evidence:
            raise SupervisorError("completed epoch evidence contradicts the reconciled final commit")
        epoch["completion"] = evidence
        self.transition(
            state, "PLAN_COMPLETED",
            f"Plan epoch {epoch['epoch_id']} completed at {committed[:12]}; no new ticket will be inferred.",
            current_ticket=ticket,
            active_run=None,
            starting_head=None,
            pending_commit=None,
            architecture_resolution=None,
            blocked_report=None,
            ticket_timing=None,
            completion_reason=evidence["reason"],
            final_result=evidence,
        )

    def _verified_push_target(self) -> dict[str, str]:
        """Return the host target only after all local redirect checks pass."""
        target = self.host_push_target
        if target is None:
            raise SupervisorError("repository push is enabled but the host push target is absent or invalid")
        if self.git.branch() != self.policy["expected_branch"] or target["branch"] != self.policy["expected_branch"]:
            raise SupervisorError("push target branch does not exactly match the checked-out and policy branch")
        fetch_urls, push_urls = self.git.remote_urls(target["remote"])
        if fetch_urls != [target["url"]] or push_urls != [target["url"]]:
            raise SupervisorError("configured Git remote does not exactly match the host push target identity")
        return dict(target)

    def _push_failure_message(self) -> str:
        """Do not persist Git transport output: it can contain credential-bearing URLs."""
        return "Remote push or confirmation failed; verify credentials, network access, branch protection, and fast-forward status. The local commit is preserved."

    def _reconcile_push(self, state: dict[str, Any]) -> bool:
        pending = state.get("pending_push")
        if not isinstance(pending, dict) or set(pending) != {"commit", "target"}:
            self.transition(state, "GIT_BLOCKED", "Push checkpoint is malformed; the local commit is preserved.")
            return False
        try:
            target = self._verified_push_target()
        except SupervisorError as error:
            self.transition(state, "GIT_BLOCKED", str(error) + "; the local commit is preserved.")
            return False
        if pending["target"] != target or pending.get("commit") != self.git.head():
            self.transition(state, "GIT_BLOCKED", "Push checkpoint no longer matches the verified local commit and host target.")
            return False
        # Confirmation always precedes a retry, which makes a successful push followed
        # by interruption idempotent and avoids a second required push.
        remote_commit = self.git.remote_branch_commit(target["remote"], target["branch"])
        if remote_commit != pending["commit"]:
            self._append_audit_event(state, "push_attempted", {"commit": pending["commit"], "target": target})
            self.save_state(state)
            if not self.git.push_exact(target["remote"], pending["commit"], target["branch"]):
                self.transition(state, "GIT_BLOCKED", self._push_failure_message())
                return False
            remote_commit = self.git.remote_branch_commit(target["remote"], target["branch"])
        if remote_commit != pending["commit"]:
            self.transition(state, "GIT_BLOCKED", self._push_failure_message())
            return False
        self._append_audit_event(state, "push_confirmed", {"commit": pending["commit"], "target": target})
        pending_commit = state.get("pending_commit")
        if not isinstance(pending_commit, dict):
            self.transition(state, "GIT_BLOCKED", "Push confirmation lacks its local commit checkpoint.")
            return False
        pending_commit["persistence_reconciled"] = "REMOTELY_PERSISTED"
        self.transition(
            state, "COMMITTING", f"REMOTELY_PERSISTED {pending['commit'][:12]}",
            pending_push=None, pending_commit=pending_commit,
        )
        return True

    def _finish_commit(self, state: dict[str, Any]) -> bool:
        commit_started = time.monotonic()
        pending = state["pending_commit"]
        active = state["active_run"]
        preserved = active.get("preserved_implementation_checkpoint")
        current_head = self.git.head()
        if current_head == pending["starting_head"]:
            if self.git.fingerprint() != pending["fingerprint"]:
                self.transition(state, "GIT_BLOCKED", "Working tree changed after the commit checkpoint; no commit was attempted.")
                return False
            try:
                if preserved is not None:
                    if pending.get("role") != "architecture" or not self._preserved_paths_match(preserved):
                        self.transition(
                            state, "GIT_BLOCKED",
                            "The preserved implementation checkpoint changed before the architecture commit.",
                        )
                        return False
                    commit_paths = sorted(active.get("role_changed_files", []))
                    if not commit_paths or commit_paths != sorted(active["report"]["files_changed"]):
                        self.transition(
                            state, "SCOPE_BLOCKED",
                            "Architecture commit paths no longer match its validated report.",
                        )
                        return False
                    self.git.stage_paths(commit_paths)
                    if self.git.cached_files() != commit_paths:
                        self.transition(
                            state, "GIT_BLOCKED",
                            "Architecture staging included files outside its validated change set.",
                        )
                        return False
                else:
                    self.git.stage_all()
                diff_ok, diff_output = self.git.cached_diff_check()
                run_dir = self.runs_dir / state["active_run"]["id"]
                atomic_write_text(run_dir / "check-git-diff-cached.log", diff_output or "git diff --cached --check passed\n")
                if not diff_ok:
                    self.transition(
                        state, "VERIFICATION_FAILED",
                        f"git diff --cached --check failed. See {(run_dir / 'check-git-diff-cached.log').relative_to(self.root)}",
                    )
                    return False
                committed = self.git.commit_staged(pending["message"])
            except SupervisorError as error:
                self.transition(state, "GIT_BLOCKED", f"Commit failed without recovery action: {error}")
                return False
        else:
            try:
                reconciled = (
                    self.git.parent(current_head) == pending["starting_head"]
                    and self.git.commit_subject(current_head) == pending["message"]
                    and (
                        self.git.is_clean()
                        if preserved is None
                        else (
                            self.git.changed_files() == preserved.get("files")
                            and self.git.fingerprint() == preserved.get("fingerprint")
                            and self._preserved_paths_match(preserved)
                            and self.git.changed_files_between(pending["starting_head"], current_head)
                            == sorted(active.get("role_changed_files", []))
                        )
                    )
                )
            except SupervisorError:
                reconciled = False
            if not reconciled:
                self.transition(
                    state, "GIT_BLOCKED",
                    "HEAD moved during a pending commit and cannot be reconciled safely; no duplicate commit was attempted.",
                )
                return False
            committed = current_head
        role, ticket = pending["role"], pending["ticket"]
        commit_duration = time.monotonic() - commit_started
        self._add_active_runtime(state, commit_duration)
        state["last_commit"] = committed
        if not pending.get("persistence_reconciled"):
            if not self.capability_allowed("repository_push"):
                pending["persistence_reconciled"] = "LOCALLY_COMMITTED"
                self._append_audit_event(state, "locally_committed", {"commit": committed})
                self.transition(
                    state, "COMMITTING", f"LOCALLY_COMMITTED {committed[:12]}", pending_commit=pending,
                )
            else:
                try:
                    target = self._verified_push_target()
                except SupervisorError as error:
                    self.transition(state, "GIT_BLOCKED", str(error) + "; the local commit is preserved.")
                    return False
                self.transition(
                    state, "PUSHING", f"Local commit {committed[:12]} awaits remote persistence.",
                    pending_push={"commit": committed, "target": target}, pending_commit=pending,
                )
                return True
        state["last_completed_result"] = f"{pending['persistence_reconciled']} {committed[:12]}"
        if role == "architecture":
            architecture_duration = (
                state["active_run"].get("duration_seconds", 0.0)
                + state["active_run"].get("verification_duration_seconds", 0.0)
            )
            resolution = {
                "commit": committed,
                "report": state["active_run"]["report"],
                "run_id": state["active_run"]["id"],
            }
            prerequisite = self._pending_plan_prerequisite(state, ticket)
            reconciliation_context = state.get("recovery_context") or {}
            if reconciliation_context.get("kind") == "periodic_plan_reconciliation":
                if prerequisite is None:
                    self.transition(
                        state, "GIT_BLOCKED",
                        "Committed periodic plan reconciliation no longer identifies a pending prerequisite.",
                    )
                    return False
                state.setdefault("plan_reconciliations", []).append({
                    "at": isoformat(self.now()),
                    "note": reconciliation_context["note"],
                    "head": committed,
                    "kind": "periodic",
                    "from_current_ticket": ticket,
                    "to_current_ticket": prerequisite,
                    "checkpoint_head": reconciliation_context["checkpoint_head"],
                })
            if preserved is not None:
                if (
                    self.git.changed_files() != preserved.get("files")
                    or self.git.fingerprint() != preserved.get("fingerprint")
                    or not self._preserved_paths_match(preserved)
                ):
                    self.transition(
                        state, "GIT_BLOCKED",
                        "Architecture commit did not preserve the implementation checkpoint exactly.",
                    )
                    return False
                context = dict(preserved["recovery_context"])
                context.update({
                    "starting_head": committed,
                    "fingerprint": preserved["fingerprint"],
                    "preserved_files": list(preserved["files"]),
                    "reason": "architecture_resolution_with_preserved_implementation",
                    "architecture_resolution_commit": committed,
                })
                diagnostic = state.get("diagnostic")
                if isinstance(diagnostic, dict) and diagnostic.get("ticket") == ticket:
                    diagnostic["authorized_recovery_count"] = len(
                        self._completed_recovery_run_ids(state, ticket)
                    )
                if prerequisite is not None:
                    context = {
                        "kind": "architecture_prerequisite",
                        "role": "implementation",
                        "ticket": prerequisite,
                        "deferred_ticket": ticket,
                        "starting_head": committed,
                        "fingerprint": preserved["fingerprint"],
                        "preserved_files": list(preserved["files"]),
                        "preserved_product_snapshot": preserved["product_snapshot"],
                        "reason": "authoritative_prerequisite_inserted_before_active_ticket",
                        "architecture_resolution_commit": committed,
                    }
                self.transition(
                    state, "RECOVER_MODEL",
                    (
                        f"Architecture amendment committed separately at {committed[:12]}; {prerequisite} "
                        f"must run before deferred {ticket} using its preserved compatible checkpoint."
                        if prerequisite is not None else
                        f"Architecture amendment committed separately at {committed[:12]}; preserved {ticket} "
                        "work is ready for bounded recovery."
                    ),
                    current_ticket=prerequisite or ticket,
                    architecture_resolution=resolution, active_run=None,
                    starting_head=None, pending_commit=None,
                    recovery_context=context, diagnostic=diagnostic,
                    ticket_timing=None if prerequisite is not None else state.get("ticket_timing"),
                )
                timing = state.get("ticket_timing") or {}
                timing["architecture_escalated"] = True
                self._record_timing("architecture_escalations", {
                    "at": isoformat(self.now()), "ticket": ticket,
                    "duration_seconds": architecture_duration,
                })
                if self._maybe_periodic_gate(state, "RECOVER_MODEL"):
                    return False
                return True
            self.transition(
                state, "READY", (
                    f"Architecture amendment committed separately at {committed[:12]}; {prerequisite} "
                    f"must run before deferred {ticket}."
                    if prerequisite is not None else
                    f"Architecture amendment committed separately at {committed[:12]}; rerunning {ticket}."
                ),
                current_ticket=prerequisite or ticket,
                architecture_resolution=resolution, active_run=None, starting_head=None,
                pending_commit=None,
                recovery_context=None,
                ticket_timing=None if prerequisite is not None else state.get("ticket_timing"),
            )
            timing = state.get("ticket_timing") or {}
            timing["architecture_escalated"] = True
            self._record_timing("architecture_escalations", {
                "at": isoformat(self.now()), "ticket": ticket,
                "duration_seconds": architecture_duration,
            })
            if self._maybe_periodic_gate(state, "READY"):
                return False
            return True
        if ticket not in state["completed_tickets"]:
            state["completed_tickets"].append(ticket)
        checkpoint = self._checkpoint_data(state)
        checkpoint["completed_tickets"] += 1
        ticket_timing = state.get("ticket_timing") or {}
        total_active = max(0.0, checkpoint["active_runtime_seconds"] - float(ticket_timing.get("active_runtime_start", 0)))
        try:
            total_elapsed = max(0.0, (self.now() - parse_datetime(ticket_timing["started_at"])).total_seconds())
        except (KeyError, SupervisorError):
            total_elapsed = total_active
        self._record_timing("tickets", {
            "at": isoformat(self.now()), "ticket": ticket,
            "duration_seconds": total_elapsed,
            "active_duration_seconds": total_active,
            "architecture_escalated": bool(ticket_timing.get("architecture_escalated")),
        })
        if pending.get("final_ticket"):
            try:
                self._complete_plan_epoch(state, committed=committed, pending=pending)
            except SupervisorError as error:
                self.transition(state, "GIT_BLOCKED", "Final commit could not be reconciled safely: " + str(error))
                return False
            return False
        next_ticket = self._next_ticket(ticket)
        milestone = next((item for item in self.policy["milestones"] if item["after_ticket"] == ticket), None)
        if milestone:
            self.transition(
                state, "HUMAN_GATE", milestone["message"],
                current_ticket=milestone["before_ticket"], active_run=None,
                starting_head=None, pending_commit=None,
                architecture_resolution=None, blocked_report=None,
                ticket_timing=None,
                gate={"kind": "milestone", "name": milestone["name"], "head": committed, "ticket": next_ticket},
            )
            return False
        self.transition(
            state, "READY", f"{ticket} committed at {committed[:12]}; next ticket is {next_ticket}.",
            current_ticket=next_ticket, active_run=None, starting_head=None,
            pending_commit=None, architecture_resolution=None, blocked_report=None,
            ticket_timing=None,
        )
        if self._maybe_periodic_gate(state, "READY"):
            return False
        return True

    def _plan_tickets(self) -> list[str]:
        materialization = self._current_backlog_materialization()
        if materialization is not None:
            plan_path = self._backlog_cycle_artifact(materialization["plan"])
            plan_bytes = plan_path.read_bytes()
            if hashlib.sha256(plan_bytes).hexdigest() != materialization["plan_digest"]:
                raise SupervisorError("materialized backlog plan changed after epoch creation")
            tickets = self._parse_plan_tickets(plan_bytes.decode("utf-8"))
            state = read_json(self.state_path)
            epoch = next(
                item for item in state["plan_epochs"]
                if item["epoch_id"] == state["current_plan_epoch_id"]
            )
            if tickets != epoch["tickets"]:
                raise SupervisorError("materialized backlog plan contradicts the immutable epoch frontier")
            return tickets
        plan = (self.root / self.policy["implementation_plan"]).read_text(encoding="utf-8")
        return self._parse_plan_tickets(plan)

    def _current_backlog_materialization(self) -> dict[str, Any] | None:
        """Resolve immutable backlog artifacts for the current successor epoch."""
        if not self.state_path.is_file() or not self.backlog_cycle_path.is_file():
            return None
        state = read_json(self.state_path)
        cycle = read_json(self.backlog_cycle_path)
        materialization = cycle.get("materialization") if isinstance(cycle, dict) else None
        if (
            state.get("version") != STATE_VERSION
            or not isinstance(cycle, dict)
            or cycle.get("version") != 1
            or cycle.get("phase") != "READY_EPOCH"
            or not isinstance(materialization, dict)
            or materialization.get("epoch_id") != state.get("current_plan_epoch_id")
        ):
            return None
        required = {
            "epoch_id", "plan", "index", "tickets", "ticket_sources",
            "plan_digest", "index_digest",
        }
        if set(materialization) != required:
            raise SupervisorError("current backlog materialization is malformed")
        if (
            any(not isinstance(materialization.get(key), str) for key in (
                "epoch_id", "plan", "index", "tickets", "plan_digest", "index_digest",
            ))
            or not isinstance(materialization.get("ticket_sources"), dict)
            or any(
                not re.fullmatch(r"[0-9a-f]{64}", materialization[key])
                for key in ("plan_digest", "index_digest")
            )
        ):
            raise SupervisorError("current backlog materialization identity is malformed")
        plan = self._backlog_cycle_artifact(materialization["plan"])
        index = self._backlog_cycle_artifact(materialization["index"])
        tickets = self._backlog_cycle_artifact(materialization["tickets"])
        if (
            not plan.is_file()
            or not index.is_file()
            or not tickets.is_dir()
            or hashlib.sha256(plan.read_bytes()).hexdigest() != materialization["plan_digest"]
            or hashlib.sha256(index.read_bytes()).hexdigest() != materialization["index_digest"]
        ):
            raise SupervisorError("current backlog materialization is missing or changed")
        return materialization

    @staticmethod
    def _parse_plan_tickets(plan: str) -> list[str]:
        table_lines = [line for line in plan.splitlines() if re.match(r"^\|\s*\d+", line)]
        tokens: list[str] = []
        for line in table_lines:
            columns = line.split("|")
            if len(columns) < 4:
                continue
            cell = columns[2]
            for match in re.finditer(r"(F?\d{2})(?:[–-](F?\d{2}))?", cell):
                start, end = match.group(1), match.group(2)
                if end:
                    prefix = "F" if start.startswith("F") else ""
                    first = int(start.removeprefix("F"))
                    last = int(end.removeprefix("F"))
                    tokens.extend(f"{prefix or 'T'}{number:02d}" for number in range(first, last + 1))
                else:
                    tokens.append(start if start.startswith("F") else "T" + start)
        if not tokens:
            raise SupervisorError("no ticket order could be parsed from the implementation plan")
        return list(dict.fromkeys(tokens))

    def _plan_tickets_at(self, revision: str) -> list[str]:
        relative = self.policy["implementation_plan"]
        plan = self.git.run("show", f"{revision}:{relative}").stdout
        return self._parse_plan_tickets(plan)

    def _pending_plan_prerequisite(self, state: dict[str, Any], ticket: str) -> str | None:
        """Find newly authoritative incomplete work that now precedes the active ticket."""
        plan = self._plan_tickets()
        if ticket not in plan:
            raise SupervisorError(f"{ticket} is not present in the authoritative implementation plan")
        completed = state.get("completed_tickets")
        if not isinstance(completed, list) or any(not isinstance(item, str) for item in completed):
            raise SupervisorError("completed-ticket history is malformed")
        unknown = [item for item in completed if item not in plan]
        if unknown:
            raise SupervisorError(
                "completed-ticket history contains tickets absent from the authoritative plan: "
                + ", ".join(unknown)
            )
        if not completed:
            return None
        current_index = plan.index(ticket)
        last_completed_index = max(plan.index(item) for item in completed)
        if last_completed_index >= current_index:
            return None
        return next(
            (item for item in plan[last_completed_index + 1:current_index] if item not in completed),
            None,
        )

    def _periodic_plan_reconciliation_error(
        self, state: dict[str, Any], active: dict[str, Any], actual: list[str],
    ) -> str | None:
        """Validate the insertion-only plan amendment opened by a periodic checkpoint."""
        context = state.get("recovery_context")
        if not isinstance(context, dict) or context.get("kind") != "periodic_plan_reconciliation":
            return None
        original_plan = context.get("original_plan")
        completed = state.get("completed_tickets")
        deferred = context.get("deferred_ticket")
        plan_path = self.policy["implementation_plan"]
        if (
            active.get("role") != "architecture"
            or active.get("ticket") != deferred
            or state.get("current_ticket") != deferred
            or active.get("starting_head") != context.get("reconciliation_head")
            or not isinstance(original_plan, list)
            or not original_plan
            or any(not isinstance(item, str) for item in original_plan)
            or len(original_plan) != len(set(original_plan))
            or not isinstance(completed, list)
            or completed != context.get("completed_tickets")
            or any(not isinstance(item, str) for item in completed)
            or not isinstance(deferred, str)
            or deferred not in original_plan
            or plan_path not in actual
        ):
            return "the architecture run does not match the exact periodic reconciliation checkpoint"
        if not completed or any(item not in original_plan for item in completed):
            return "the completed-ticket frontier is missing or no longer matches the original plan"

        try:
            plan = self._plan_tickets()
        except SupervisorError as error:
            return str(error)
        if len(plan) != len(set(plan)) or deferred not in plan:
            return "the reconciled plan is duplicate, malformed, or omits the deferred ticket"

        original_iterator = iter(plan)
        if any(not any(candidate == item for candidate in original_iterator) for item in original_plan):
            return "existing ticket order was removed or reordered instead of receiving a bounded insertion"

        frontier = max(completed, key=original_plan.index)
        original_prefix = original_plan[:original_plan.index(frontier) + 1]
        reconciled_prefix = plan[:plan.index(frontier) + 1] if frontier in plan else []
        if reconciled_prefix != original_prefix:
            return "the completed plan prefix changed"
        if plan.index(deferred) <= plan.index(frontier):
            return "the deferred ticket moved behind the completed frontier"

        prerequisite = self._pending_plan_prerequisite(state, deferred)
        if prerequisite is None or prerequisite == deferred:
            return "the reconciled plan did not insert pending work before the deferred ticket"
        inserted = [item for item in plan if item not in original_plan]
        if prerequisite not in inserted:
            return "the new next ticket is not a newly inserted plan prerequisite"
        if any(
            plan.index(ticket) <= plan.index(frontier)
            or plan.index(ticket) >= plan.index(deferred)
            for ticket in inserted
        ):
            return "new tickets were inserted outside the bounded completed-to-deferred plan segment"
        for ticket in inserted:
            try:
                self._ticket_path(ticket)
            except SupervisorError as error:
                return str(error)
        return None

    def _validate_architecture_adoption_gate(self, state: dict[str, Any], gate: dict[str, Any]) -> None:
        if gate.get("kind") != "architecture_adoption":
            raise SupervisorError("architecture adoption gate has the wrong kind")
        if not self.git.is_clean():
            raise SupervisorError("architecture adoption requires a clean working tree")
        if self.git.head() != gate.get("head"):
            raise SupervisorError("adopted architecture HEAD changed after the gate")
        if self.git.fingerprint() != gate.get("fingerprint"):
            raise SupervisorError("adopted architecture product fingerprint changed after the gate")
        plan = self._plan_tickets()
        completed = state.get("completed_tickets")
        if not isinstance(completed, list) or any(ticket not in plan for ticket in completed):
            raise SupervisorError("adopted architecture gate has malformed completed-ticket history")
        first = self._next_ticket_after_completed(plan, completed)
        if state.get("current_ticket") != first or gate.get("ticket") != first:
            raise SupervisorError("adopted architecture gate no longer points at the first incomplete ticket")

    def adopt_external_architecture(self, note: str) -> dict[str, Any]:
        """Adopt a reviewed external architecture commit at a periodic checkpoint.

        This is deliberately narrower than ordinary plan reconciliation: the
        external commit must already exist, be a descendant of the checkpoint,
        and touch only the policy's architecture allowlist. The operator still
        releases the resulting human gate before any ticket can run.
        """
        state = self.load_state()
        if state.get("phase") != "PERIODIC_CHECKPOINT":
            raise SupervisorError("external architecture adoption requires a PERIODIC_CHECKPOINT")
        if not note.strip():
            raise SupervisorError("a nonempty adoption note is required")
        gate = state.get("gate")
        if not isinstance(gate, dict) or gate.get("kind") != "periodic":
            raise SupervisorError("external architecture adoption requires a periodic gate")
        if gate.get("reason") != "PERIODIC_CHECKPOINT" or gate.get("resume_phase") != "READY":
            raise SupervisorError("external architecture adoption requires a between-ticket periodic gate")
        if any(state.get(key) is not None for key in ("active_run", "pending_commit", "starting_head")):
            raise SupervisorError("external architecture adoption requires no active or pending run")
        self.git.require_repository()
        if self.git.branch() != self.policy["expected_branch"]:
            raise SupervisorError("external architecture adoption requires the policy branch")
        if not self.git.is_clean():
            raise SupervisorError("external architecture adoption requires a clean working tree")

        checkpoint_head = gate.get("head")
        current_head = self.git.head()
        if not isinstance(checkpoint_head, str) or not checkpoint_head:
            raise SupervisorError("periodic checkpoint has no usable HEAD")
        if checkpoint_head == current_head:
            raise SupervisorError("no external commit is available to adopt")
        if not self.git.is_ancestor(checkpoint_head, current_head):
            raise SupervisorError("external architecture HEAD is not a descendant of the checkpoint")

        changed_paths = self.git.changed_files_between(checkpoint_head, current_head)
        allowed_prefixes = tuple(self.policy.get("architecture_allowed_paths", []))
        if not changed_paths:
            raise SupervisorError("external architecture adoption found no changed paths")
        if not allowed_prefixes or any(
            not (
                any(path.startswith(prefix) for prefix in allowed_prefixes)
                or self._is_supervisor_control_path(path)
            )
            for path in changed_paths
        ):
            raise SupervisorError(
                "external architecture adoption permits only paths under "
                + ", ".join(allowed_prefixes or ("the architecture allowlist",))
                + " (plus supervisor-only maintenance paths)"
            )

        if gate.get("ticket") != state.get("current_ticket"):
            raise SupervisorError("periodic gate does not match its persisted current ticket")
        original_plan = self._plan_tickets_at(checkpoint_head)
        plan = self._plan_tickets()
        completed = state.get("completed_tickets")
        if not isinstance(completed, list) or any(not isinstance(ticket, str) for ticket in completed):
            raise SupervisorError("completed-ticket history is malformed")
        if any(ticket not in original_plan or ticket not in plan for ticket in completed):
            raise SupervisorError("completed-ticket history contains a ticket absent from the adopted plan")
        original_first = self._next_ticket_after_completed(original_plan, completed)
        if original_first != state.get("current_ticket"):
            raise SupervisorError("periodic checkpoint is already stale against its recorded plan")

        # Existing ticket order and the completed prefix are immutable. Only
        # newly inserted tickets may appear before the deferred ticket.
        existing_in_new_order = [ticket for ticket in plan if ticket in original_plan]
        if existing_in_new_order != original_plan:
            raise SupervisorError("external plan change removed or reordered an existing ticket")
        frontier_index = max((original_plan.index(ticket) for ticket in completed), default=-1)
        original_prefix = original_plan[:frontier_index + 1]
        adopted_prefix = plan[:frontier_index + 1]
        if adopted_prefix != original_prefix:
            raise SupervisorError("external plan change modified the completed plan prefix")
        inserted = [ticket for ticket in plan if ticket not in original_plan]
        first_incomplete = self._next_ticket_after_completed(plan, completed)
        if not inserted or first_incomplete == state.get("current_ticket"):
            raise SupervisorError("external architecture commit did not insert pending work")
        deferred_index = plan.index(state["current_ticket"])
        if any(
            plan.index(ticket) <= frontier_index
            or plan.index(ticket) >= deferred_index
            for ticket in inserted
        ):
            raise SupervisorError("external tickets must be inserted between the completed frontier and deferred ticket")
        for ticket in inserted:
            self._ticket_path(ticket)

        fingerprint = self.git.fingerprint()
        adoption = {
            "at": isoformat(self.now()),
            "kind": "external_architecture",
            "note": note.strip(),
            "checkpoint_head": checkpoint_head,
            "adopted_head": current_head,
            "from_current_ticket": state["current_ticket"],
            "to_current_ticket": first_incomplete,
            "changed_paths": changed_paths,
        }
        state.setdefault("external_architecture_adoptions", []).append(dict(adoption))
        state.setdefault("plan_reconciliations", []).append(dict(adoption))
        new_gate = {
            "kind": "architecture_adoption",
            "name": "External architecture plan adoption",
            "head": current_head,
            "fingerprint": fingerprint,
            "ticket": first_incomplete,
            "checkpoint_head": checkpoint_head,
            "deferred_ticket": state["current_ticket"],
            "changed_paths": changed_paths,
            "resume_phase": "READY",
        }
        self.transition(
            state,
            "HUMAN_GATE",
            f"External architecture commit adopted; review before authorizing {first_incomplete}.",
            current_ticket=first_incomplete,
            gate=new_gate,
            active_run=None,
            pending_commit=None,
            starting_head=None,
            architecture_resolution=None,
            blocked_report=None,
            recovery_context=None,
            ticket_timing=None,
        )
        return state

    def _next_ticket(self, ticket: str) -> str:
        tickets = self._plan_tickets()
        try:
            index = tickets.index(ticket)
        except ValueError as error:
            raise SupervisorError(f"{ticket} is not present in the authoritative implementation plan") from error
        if index + 1 >= len(tickets):
            raise SupervisorError(f"{ticket} is the final ticket in the authoritative implementation plan")
        return tickets[index + 1]

    def _interrupt_between_stages(self, state: dict[str, Any], reason: str) -> None:
        phase = state["phase"]
        self.transition(
            state, "INTERRUPTED",
            f"Supervisor interrupted ({reason}) between stages. No new stage was started. "
            "Safe to power off. Resume with ./dev resume.",
            recovery_context={"kind": "stage", "resume_phase": phase, "reason": reason},
        )
        self._emit(state["current_ticket"], phase.lower(), "INTERRUPTED · safe to power off · resume: ./dev resume")

    def _resume_blocked_implementation(self, state: dict[str, Any]) -> dict[str, Any]:
        """Reconcile one valid blocked report to the existing same-ticket recovery path."""
        active = state.get("active_run")
        ticket = state.get("current_ticket")
        if not isinstance(active, dict) or not isinstance(ticket, str) or not ticket:
            self.transition(
                state, "REPORT_INVALID",
                "Blocked implementation recovery state is missing its active run or current ticket.",
            )
            return state
        report = active.get("report")
        errors = validate_report(report, "implementation", ticket)
        contradictory = (
            not errors
            and (
                report.get("status") != "blocked"
                or report.get("acceptance_passed") is not False
                or report.get("next_ticket_safe") is not False
                or report.get("architecture_deviation") is not False
                or report.get("ambiguity") is not False
                or report.get("product_decision_required") is not False
            )
        )
        if errors or contradictory:
            detail = "; ".join(errors) if errors else "report fields contradict bounded blocked recovery"
            self.transition(
                state, "REPORT_INVALID",
                "Blocked implementation recovery report failed closed: " + detail,
            )
            return state

        run_id = active.get("id")
        changed_files = active.get("changed_files")
        authorization = active.get("quota_authorization")
        consumptions = state.get("quota_consumptions")
        expected_authorization_fields = {
            "observation_id", "status", "consumed_at", "invocation_id",
            "role", "ticket", "recovery",
        }
        run_shape_valid = (
            isinstance(run_id, str)
            and bool(run_id)
            and Path(run_id).name == run_id
            and run_id.endswith(f"-implementation-{ticket.lower()}")
            and active.get("role") == "implementation"
            and active.get("ticket") == ticket
            and active.get("invocation_completed") is True
            and active.get("exit_code") == 0
            and active.get("rate_limited") is False
            and type(active.get("recovery")) is bool
            and isinstance(changed_files, list)
            and all(isinstance(path, str) and path for path in changed_files)
            and changed_files == sorted(set(changed_files))
        )
        authorization_valid = (
            isinstance(authorization, dict)
            and set(authorization) == expected_authorization_fields
            and isinstance(authorization.get("observation_id"), str)
            and bool(authorization.get("observation_id"))
            and authorization.get("status") == "consumed"
            and isinstance(authorization.get("consumed_at"), str)
            and bool(authorization.get("consumed_at"))
            and authorization.get("invocation_id") == run_id
            and authorization.get("role") == "implementation"
            and authorization.get("ticket") == ticket
            and authorization.get("recovery") is active.get("recovery")
            and isinstance(consumptions, list)
            and sum(item == authorization for item in consumptions) == 1
        )
        history = state.get("history")
        last_transition = history[-1] if isinstance(history, list) and history else None
        transition_valid = (
            isinstance(last_transition, dict)
            and last_transition.get("from") == "IMPLEMENTING"
            and last_transition.get("to") == "IMPLEMENTATION_FAILED"
        )
        run_dir = self.runs_dir / str(run_id)
        try:
            persisted_invocation = read_json(run_dir / "invocation.json")
            persisted_report = read_json(run_dir / "final-report.json")
        except SupervisorError:
            persisted_invocation = {}
            persisted_report = {}
        artifacts_valid = (
            persisted_invocation.get("completed") is True
            and persisted_invocation.get("exit_status") == 0
            and persisted_invocation.get("rate_limited") is False
            and persisted_report == report
        )
        if not run_shape_valid or not authorization_valid or not transition_valid or not artifacts_valid:
            self.transition(
                state, "REPORT_INVALID",
                "Blocked implementation recovery state is malformed, stale, or unsupported; no recovery was started.",
            )
            return state
        if self.git.branch() != self.policy["expected_branch"] or not self._model_checkpoint_matches(active):
            self.transition(
                state, "GIT_BLOCKED",
                "The blocked implementation's preserved tree no longer exactly matches its model checkpoint.",
            )
            return state

        self.transition(
            state, "RECOVER_MODEL",
            "Blocked implementation report reconciled to bounded same-ticket recovery; verification and scope gates remain pending.",
            blocked_report=report,
            recovery_context={
                "kind": "implementation_blocked", "role": "implementation",
                "ticket": ticket, "starting_head": active["starting_head"],
                "fingerprint": active["post_invocation_fingerprint"],
                "prior_run_id": run_id, "reason": "implementation_report_blocked",
                "preserved_files": list(changed_files),
            },
        )
        return state

    def _resume_scope_blocked(self, state: dict[str, Any]) -> dict[str, Any]:
        """Enter read-only architecture review for one exact protected-path checkpoint."""
        error = self._scope_blocked_recovery_error(state)
        if error is not None:
            # SCOPE_BLOCKED has several unrelated causes. Resume is authorized
            # only for the exact protected-path transition validated above; all
            # other checkpoints remain byte-preserved for operator diagnosis.
            return state
        active = deepcopy(state["active_run"])
        protected_paths = self._protected_paths(active["changed_files"])
        reason = state["message"]
        context = {
            "kind": "protected_scope_review", "role": "architecture",
            "ticket": state["current_ticket"],
            "starting_head": active["starting_head"],
            "fingerprint": active["post_invocation_fingerprint"],
            "prior_run_id": active["id"],
            "reason": "implementation_changed_protected_paths",
            "scope_reason": reason,
            "preserved_files": list(active["changed_files"]),
            "protected_paths": protected_paths,
            "source_active": active,
        }
        self.transition(
            state, "ARCHITECTURE_PENDING",
            "Validated verified protected-path checkpoint; bounded read-only architecture review is pending.",
            recovery_context=context,
            blocked_report={
                "source": "scope_gate", "ticket": state["current_ticket"],
                "summary": reason, "protected_paths": protected_paths,
                "implementation_run_id": active["id"],
                "implementation_fingerprint": active["post_invocation_fingerprint"],
            },
            scope_recovery_unavailable=None,
        )
        return self.run()

    def _resume_failed_invocation(self, state: dict[str, Any]) -> dict[str, Any]:
        """Retry a completed process failure only when it provably changed no workspace state."""
        active = state.get("active_run") or {}
        starting_head = active.get("starting_head", state.get("starting_head"))
        recorded_files = active.get("changed_files")
        recorded_fingerprint = active.get("post_invocation_fingerprint")
        current_head = self.git.head()
        head_compatible = bool(starting_head and current_head == starting_head)
        if starting_head and not head_compatible and self.git.is_ancestor(starting_head, current_head):
            intervening_files = self.git.changed_files_between(starting_head, current_head)
            head_compatible = bool(intervening_files) and all(
                self._is_supervisor_control_path(path) for path in intervening_files
            )
        safe = (
            active.get("invocation_completed") is True
            and active.get("exit_code") != 0
            and recorded_files == []
            and starting_head
            and head_compatible
            and self.git.is_clean()
            and (
                recorded_fingerprint is None
                or self.git.fingerprint() == recorded_fingerprint
            )
        )
        if not safe:
            self.transition(
                state, "GIT_BLOCKED",
                "The failed invocation cannot be proven to have left the workspace unchanged; "
                "only committed supervisor fixes may follow its starting HEAD before retrying.",
            )
            return state
        role = active.get("role")
        if role not in {"implementation", "architecture"}:
            self.transition(state, "GIT_BLOCKED", "The failed invocation has no valid role to retry safely.")
            return state
        retry_phase = "READY" if role == "implementation" else "ARCHITECTURE_PENDING"
        self.transition(
            state, retry_phase,
            "Retrying the unchanged-workspace invocation after an explicit resume; quota will be checked first.",
            active_run=None, starting_head=None, recovery_context=None,
        )
        return self.run()

    def _resume_architecture_entry(self, state: dict[str, Any]) -> dict[str, Any]:
        """Retry only the clean-start rejection of a still-exact architecture checkpoint."""
        history = state.get("history")
        last = history[-1] if isinstance(history, list) and history else None
        if (
            not isinstance(last, dict)
            or last.get("from") != "ARCHITECTURE_PENDING"
            or last.get("to") != "GIT_BLOCKED"
            or not str(last.get("message", "")).startswith("working tree has unexpected pre-existing changes:")
        ):
            return state
        try:
            self._preserved_architecture_checkpoint(state)
        except SupervisorError as error:
            self.transition(state, "GIT_BLOCKED", str(error))
            return state
        self.transition(
            state, "ARCHITECTURE_PENDING",
            "Validated preserved same-ticket implementation checkpoint; retrying the pending architecture role.",
        )
        return self.run()

    def _invalid_report_recovery_error(self, state: dict[str, Any]) -> str | None:
        """Return why the completed model report cannot be retried report-only."""
        active = state.get("active_run")
        ticket = state.get("current_ticket")
        if not isinstance(active, dict) or not isinstance(ticket, str) or not ticket:
            return "the active model run or current ticket is missing"
        role = active.get("role")
        if role not in {"implementation", "architecture"} or active.get("ticket") != ticket:
            return "the active run role or ticket is unsupported"
        report = active.get("report")
        report_errors = validate_report(report, role, ticket)
        if not report_errors and report.get("status") == "pass":
            if role == "implementation" and any(
                report.get(field) is not True
                for field in ("acceptance_passed", "tests_passed", "next_ticket_safe")
            ):
                report_errors.append("PASS report did not assert all implementation completion gates")
            if report.get("architecture_deviation") or report.get("ambiguity"):
                report_errors.append("PASS report also asserted architecture deviation or ambiguity")
        if not report_errors:
            return "the recorded report does not reproduce a supported REPORT_INVALID result"
        changed_files = active.get("changed_files")
        if (
            active.get("invocation_completed") is not True
            or active.get("exit_code") != 0
            or active.get("rate_limited") is not False
            or not isinstance(changed_files, list)
            or changed_files != sorted(set(changed_files))
            or not self._model_checkpoint_matches(active)
            or self.git.branch() != self.policy["expected_branch"]
        ):
            return "the completed invocation checkpoint is stale or malformed"
        authorization = active.get("quota_authorization")
        consumptions = state.get("quota_consumptions")
        if (
            not isinstance(authorization, dict)
            or authorization.get("status") != "consumed"
            or authorization.get("invocation_id") != active.get("id")
            or authorization.get("role") != role
            or authorization.get("ticket") != ticket
            or not isinstance(consumptions, list)
            or sum(item == authorization for item in consumptions) != 1
        ):
            return "the invocation quota audit is missing or contradictory"
        run_id = active.get("id")
        if not isinstance(run_id, str) or not run_id or Path(run_id).name != run_id:
            return "the invocation identity is malformed"
        run_dir = self.runs_dir / run_id
        try:
            invocation = read_json(run_dir / "invocation.json")
        except SupervisorError:
            return "the completed invocation artifact is missing or malformed"
        if (
            invocation.get("completed") is not True
            or invocation.get("exit_status") != 0
            or invocation.get("rate_limited") is not False
        ):
            return "the invocation artifact does not record a successful completed process"
        report_path = run_dir / "final-report.json"
        if isinstance(report, dict):
            try:
                if read_json(report_path) != report:
                    return "the persisted report does not match supervisor state"
            except SupervisorError:
                return "the persisted report is missing or malformed"
        elif report_path.exists():
            return "the persisted report contradicts the missing state report"
        preserved = active.get("preserved_implementation_checkpoint")
        if preserved is not None:
            preserved_files = preserved.get("files") if isinstance(preserved, dict) else None
            role_changed = active.get("role_changed_files")
            if (
                role != "architecture"
                or not isinstance(preserved_files, list)
                or not self._preserved_paths_match(preserved)
                or not isinstance(role_changed, list)
                or role_changed != [path for path in changed_files if path not in set(preserved_files)]
                or any(
                    not any(path.startswith(prefix) for prefix in self.policy["architecture_allowed_paths"])
                    for path in role_changed
                )
            ):
                return "the preserved implementation or architecture delta is inconsistent"
        return None

    def _resume_invalid_report(self, state: dict[str, Any]) -> dict[str, Any]:
        history = state.get("history")
        last = history[-1] if isinstance(history, list) and history else None
        active = state.get("active_run") or {}
        expected_from = "IMPLEMENTING" if active.get("role") == "implementation" else "ARCHITECTURE_REVIEW"
        error = self._invalid_report_recovery_error(state)
        if (
            not isinstance(last, dict)
            or last.get("from") != expected_from
            or last.get("to") != "REPORT_INVALID"
        ):
            error = error or "the REPORT_INVALID transition history is stale or unsupported"
        if error is not None:
            self.transition(
                state, "REPORT_INVALID",
                "Automatic report recovery is unavailable: " + error + ". Operator reconciliation is required.",
            )
            return state
        role = active["role"]
        preserved = active.get("preserved_implementation_checkpoint")
        context = {
            "kind": "report_invalid", "role": role, "ticket": active["ticket"],
            "starting_head": active["starting_head"],
            "fingerprint": active["post_invocation_fingerprint"],
            "prior_run_id": active["id"], "reason": "invalid_structured_report",
            "preserved_files": list(active["changed_files"]),
            "role_changed_files": list(active.get("role_changed_files", active["changed_files"])),
            "report_errors": validate_report(active.get("report"), role, active["ticket"]),
        }
        if not context["report_errors"]:
            context["report_errors"] = [state.get("message", "invalid report semantics")]
        if preserved is not None:
            context["preserved_implementation_checkpoint"] = preserved
        self.transition(
            state, "RECOVER_MODEL",
            "Invalid model report reconciled to bounded report-only recovery; the preserved tree must remain unchanged.",
            recovery_context=context,
        )
        return self.run()

    def _diagnostic_failed_recovery_error(self, state: dict[str, Any]) -> str | None:
        """Return why a failed host diagnosis cannot enter deterministic verification."""
        ticket = state.get("current_ticket")
        diagnostic = state.get("diagnostic")
        active = state.get("active_run")
        if not isinstance(ticket, str) or not isinstance(diagnostic, dict) or not isinstance(active, dict):
            return "the ticket, diagnostic, or active implementation checkpoint is missing"
        supplied = diagnostic.get("evidence_run_ids")
        if (
            diagnostic.get("status") != "classified"
            or diagnostic.get("ticket") != ticket
            or diagnostic.get("classification") != "HOST_VERIFICATION_REQUIRED"
            or diagnostic.get("resulting_transition") != "DIAGNOSTIC_FAILED"
            or not isinstance(supplied, list)
            or validate_diagnostic_report(diagnostic.get("report"), ticket, supplied)
            or active.get("role") != "implementation"
            or active.get("ticket") != ticket
        ):
            return "the failed diagnostic is not a supported host-verification classification"
        before = diagnostic.get("workspace_before")
        after = diagnostic.get("workspace_after")
        if not isinstance(before, dict) or before != after:
            return "the read-only diagnostic workspace checkpoint is stale or contradictory"
        run_id = diagnostic.get("run_id")
        artifact = self._diagnostic_artifact(run_id, ticket) if isinstance(run_id, str) else None
        if (
            artifact is None
            or artifact.get("report") != diagnostic.get("report")
            or artifact.get("product_snapshot") != diagnostic.get("product_snapshot_before")
        ):
            return "the durable diagnostic artifact is missing, stale, or contradictory"
        authorization = diagnostic.get("quota_authorization")
        consumptions = state.get("quota_consumptions")
        if (
            not isinstance(authorization, dict)
            or authorization.get("status") != "consumed"
            or authorization.get("invocation_id") != run_id
            or authorization.get("role") != "diagnostic"
            or authorization.get("ticket") != ticket
            or not isinstance(consumptions, list)
            or sum(item == authorization for item in consumptions) != 1
        ):
            return "the diagnostic quota audit is missing or contradictory"
        history = state.get("history")
        last = history[-1] if isinstance(history, list) and history else None
        if (
            not isinstance(last, dict)
            or last.get("from") != "DIAGNOSTIC_REVIEW"
            or last.get("to") != "DIAGNOSTIC_FAILED"
        ):
            return "the DIAGNOSTIC_FAILED transition history is stale or unsupported"
        if self._diagnostic_verification_handoff(state) is None:
            return "the preserved checkpoint does not satisfy one configured mandatory host-verification handoff"
        return None

    def _resume_failed_diagnostic(self, state: dict[str, Any]) -> dict[str, Any]:
        error = self._diagnostic_failed_recovery_error(state)
        if error is not None:
            self.transition(
                state, "DIAGNOSTIC_FAILED",
                "Automatic diagnostic recovery is unavailable: " + error +
                ". Operator reconciliation is required.",
            )
            return state
        handoff = self._diagnostic_verification_handoff(state)
        if handoff is None:
            raise SupervisorError("validated diagnostic host handoff disappeared before recovery")
        self.recover_environment(handoff["capability"])
        return self.run()

    def _failed_host_verification(self, active: dict[str, Any]) -> dict[str, Any] | None:
        handoff = active.get("host_verification_handoff") or {}
        required = handoff.get("required_checks")
        capability = handoff.get("capability")
        if not isinstance(required, list) or not required or not isinstance(capability, str):
            return None
        failures = [
            item for item in active.get("verification_results", [])
            if item.get("name") in required
            and item.get("passed") is False
            and item.get("exit_status") != 0
            and capability in item.get("host_capabilities", [])
        ]
        if len(failures) != 1:
            return None
        result = failures[0]
        log_name = result.get("log")
        if not isinstance(log_name, str) or Path(log_name).name != log_name:
            return None
        log_path = self.runs_dir / str(active.get("id", "")) / log_name
        try:
            output = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        limit = 32_000
        return {
            "name": result.get("name"),
            "command": result.get("command"),
            "exit_status": result.get("exit_status"),
            "log": str(log_path.relative_to(self.root)),
            "output": output[-limit:],
            "output_truncated": len(output) > limit,
        }

    def _transition_to_verification_failure_recovery(
        self, state: dict[str, Any], failure: dict[str, Any],
    ) -> None:
        active = state["active_run"]
        self.transition(
            state, "RECOVER_MODEL",
            "Deterministic host verification found an implementation failure; preserved work is ready for same-ticket repair.",
            recovery_context={
                "kind": "verification_failure", "role": "implementation",
                "ticket": active["ticket"], "starting_head": active["starting_head"],
                "fingerprint": active["post_invocation_fingerprint"],
                "prior_run_id": active["id"], "reason": "deterministic_verification_failure",
                "preserved_files": list(active["changed_files"]),
                "failed_verification": failure,
            },
        )

    def _protected_snapshot_recovery_error(self, state: dict[str, Any]) -> str | None:
        """Validate the one legacy control-path product-snapshot false block.

        This is intentionally narrower than protected-scope resume.  It accepts
        only a completed read-only architecture PASS which the old product-path
        count comparison rejected because a configured control path is omitted
        from the product snapshot.  The complete Git fingerprint remains the
        authority for those control-path bytes.
        """
        if state.get("phase") != "GIT_BLOCKED":
            return "protected snapshot recovery requires the preserved GIT_BLOCKED checkpoint"
        message = "Protected-scope architecture review was not read-only or its preserved implementation checkpoint is no longer exact."
        history = state.get("history")
        last = history[-1] if isinstance(history, list) and history else None
        if (
            state.get("message") != message
            or not isinstance(last, dict)
            or last.get("from") != "ARCHITECTURE_REVIEW"
            or last.get("to") != "GIT_BLOCKED"
            or last.get("message") != message
        ):
            return "the protected-scope false-block transition is missing or contradictory"

        ticket = state.get("current_ticket")
        review = state.get("active_run")
        context = state.get("recovery_context")
        if not isinstance(ticket, str) or not ticket or not isinstance(review, dict) or not isinstance(context, dict):
            return "the ticket, completed architecture review, or recovery context is missing"
        preserved = review.get("preserved_implementation_checkpoint")
        if not isinstance(preserved, dict) or preserved.get("scope_review") is not True:
            return "the protected implementation checkpoint is missing or not a scope review"
        source = preserved.get("source_active")
        protected_paths = preserved.get("protected_paths")
        checkpoint_error = self._validated_protected_scope_checkpoint(state, source, protected_paths)
        if checkpoint_error is not None:
            return "the preserved implementation checkpoint is stale or contradictory: " + checkpoint_error
        if (
            context != preserved.get("recovery_context")
            or context.get("kind") != "protected_scope_review"
            or context.get("role") != "architecture"
            or context.get("ticket") != ticket
            or context.get("source_active") != source
            or context.get("protected_paths") != protected_paths
            or review.get("role") != "architecture"
            or review.get("ticket") != ticket
            or review.get("recovery") is not True
            or review.get("starting_head") != source.get("starting_head")
            or review.get("changed_files") != source.get("changed_files")
            or review.get("role_changed_files") != []
            or review.get("post_invocation_fingerprint") != source.get("post_invocation_fingerprint")
            or self.git.head() != source.get("starting_head")
            or self.git.branch() != self.policy["expected_branch"]
            or self.git.fingerprint() != source.get("post_invocation_fingerprint")
            or not self._model_checkpoint_matches(review)
        ):
            return "the completed read-only architecture review is stale, cross-ticket, or altered"

        report = review.get("report")
        if (
            validate_report(report, "architecture", ticket)
            or report.get("status") != "pass"
            or any(report.get(field) is not True for field in ("acceptance_passed", "tests_passed", "next_ticket_safe"))
            or any(report.get(field) is not False for field in ("architecture_deviation", "ambiguity", "product_decision_required"))
            or report.get("files_changed") != []
        ):
            return "the completed architecture report is not the exact read-only protected-scope approval"

        source_files = source.get("changed_files")
        if (
            not isinstance(source_files, list)
            or source_files != preserved.get("files")
            or source_files != context.get("preserved_files")
            or not any(self._is_supervisor_control_path(path) for path in source_files)
            or preserved.get("product_snapshot") != self._product_snapshot()
            or not self._preserved_paths_match(preserved)
        ):
            return "the checkpoint is not the configured control-path product-snapshot count mismatch"

        source_run_id = source.get("id")
        if not isinstance(source_run_id, str) or not source_run_id or Path(source_run_id).name != source_run_id:
            return "the preserved implementation run identity is malformed"
        source_dir = self.runs_dir / source_run_id
        source_artifacts = [
            source_dir / "invocation.json", source_dir / "final-report.json",
            source_dir / "checks.json", source_dir / "changed-files.json",
            source_dir / "usage.json", source_dir / "check-git-diff.log",
        ]
        try:
            if any(not stat.S_ISREG(path.lstat().st_mode) for path in source_artifacts):
                return "the preserved implementation artifacts are unsafe"
            source_invocation = read_json(source_dir / "invocation.json")
            source_report = read_json(source_dir / "final-report.json")
            source_checks = json.loads((source_dir / "checks.json").read_text(encoding="utf-8"))
            source_changed = json.loads((source_dir / "changed-files.json").read_text(encoding="utf-8"))
            source_usage = read_json(source_dir / "usage.json")
        except (SupervisorError, OSError, json.JSONDecodeError):
            return "the preserved implementation artifacts are unavailable or malformed"
        if (
            source_invocation.get("completed") is not True
            or source_invocation.get("exit_status") != 0
            or source_invocation.get("rate_limited") is not False
            or source_report != source.get("report")
            or source_checks != source.get("verification_results")
            or source_changed != source_files
            or source_usage != source.get("usage")
        ):
            return "the preserved implementation artifacts contradict the checkpoint"

        run_id = review.get("id")
        authorization = review.get("quota_authorization")
        consumptions = state.get("quota_consumptions")
        if (
            not isinstance(run_id, str)
            or not run_id
            or Path(run_id).name != run_id
            or not isinstance(authorization, dict)
            or authorization.get("status") != "consumed"
            or authorization.get("invocation_id") != run_id
            or authorization.get("role") != "architecture"
            or authorization.get("ticket") != ticket
            or authorization.get("recovery") is not True
            or not isinstance(consumptions, list)
            or sum(item == authorization for item in consumptions) != 1
        ):
            return "the completed architecture review quota audit is missing or contradictory"
        run_dir = self.runs_dir / run_id
        try:
            review_artifacts = [
                run_dir / "invocation.json", run_dir / "final-report.json",
                run_dir / "changed-files.json", run_dir / "usage.json", run_dir / "diff-summary.txt",
            ]
            if any(not stat.S_ISREG(path.lstat().st_mode) for path in review_artifacts):
                return "the completed architecture review artifacts are unsafe"
            invocation = read_json(run_dir / "invocation.json")
            durable_report = read_json(run_dir / "final-report.json")
            durable_files = json.loads((run_dir / "changed-files.json").read_text(encoding="utf-8"))
            durable_usage = read_json(run_dir / "usage.json")
        except (SupervisorError, OSError, json.JSONDecodeError):
            return "the completed architecture review artifacts are unavailable or malformed"
        if (
            invocation.get("completed") is not True
            or invocation.get("exit_status") != 0
            or invocation.get("rate_limited") is not False
            or durable_report != report
            or durable_files != source_files
            or durable_usage != review.get("usage")
        ):
            return "the completed architecture review artifacts contradict the preserved checkpoint"
        return None

    def recover_protected_snapshot(self) -> dict[str, Any]:
        """Reprocess exactly one legacy control-path snapshot false block."""
        state = self.load_state()
        error = self._protected_snapshot_recovery_error(state)
        if error is not None:
            raise SupervisorError("protected snapshot recovery is unavailable: " + error)
        review = state["active_run"]
        preserved = review["preserved_implementation_checkpoint"]
        evidence = {
            "ticket": state["current_ticket"], "review_run_id": review["id"],
            "implementation_run_id": preserved["source_run_id"],
            "head": self.git.head(), "branch": self.git.branch(),
            "files": list(preserved["files"]),
            "product_snapshot": deepcopy(preserved["product_snapshot"]),
            "fingerprint": self.git.fingerprint(),
            "architecture_report": deepcopy(review["report"]),
            "architecture_quota_authorization": deepcopy(review["quota_authorization"]),
        }
        self._append_audit_event(state, "protected_snapshot_recovery", evidence)
        self._process_protected_scope_review(state)
        return state

    def _generic_verification_failure_checkpoint(
        self, state: dict[str, Any], *, require_phase: bool = True,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Validate the immutable evidence needed to open generic repair.

        This deliberately does not reuse the host-verification reconciliation
        predicate.  A mandatory host failure has additional evidence rules and
        must remain on that stricter path.
        """
        if require_phase and state.get("phase") != "VERIFICATION_FAILED":
            return None, "generic verification recovery requires VERIFICATION_FAILED"
        active = state.get("active_run")
        ticket = state.get("current_ticket")
        if not isinstance(active, dict) or not isinstance(ticket, str) or not ticket:
            return None, "current ticket or failed run is missing"
        if self._failed_host_verification(active) is not None:
            return None, "mandatory host-verification failures require their stricter reconciliation path"
        run_id = active.get("id")
        files = active.get("changed_files")
        fingerprint = active.get("post_invocation_fingerprint")
        starting_head = active.get("starting_head")
        if (
            active.get("role") != "implementation"
            or active.get("ticket") != ticket
            or not isinstance(run_id, str)
            or Path(run_id).name != run_id
            or not isinstance(starting_head, str)
            or not starting_head
            or self.git.head() != starting_head
            or self.git.branch() != self.policy["expected_branch"]
            or not isinstance(files, list)
            or files != sorted(set(files))
            or not isinstance(fingerprint, str)
            or not fingerprint
            or not self._model_checkpoint_matches(active)
        ):
            return None, "model checkpoint, starting HEAD, or changed-file identity is stale or malformed"

        snapshot = self._product_snapshot()
        if [item.get("path") for item in snapshot.get("entries", [])] != files:
            return None, "changed-file checkpoint no longer matches the preserved product snapshot"

        results = active.get("verification_results")
        run_dir = self.runs_dir / run_id
        checks_path = run_dir / "checks.json"
        if not isinstance(results, list) or not checks_path.is_file() or checks_path.is_symlink():
            return None, "durable deterministic verification results are unavailable or unsafe"
        try:
            durable_results = json.loads(checks_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, "durable deterministic verification results are malformed"
        if not isinstance(durable_results, list) or durable_results != results:
            return None, "durable deterministic verification results contradict the preserved checkpoint"

        failed = [item for item in results if isinstance(item, dict) and item.get("passed") is False]
        if len(failed) != 1:
            return None, "generic recovery requires exactly one recorded failed deterministic check"
        failure = failed[0]
        configured = [
            check for check in self.policy.get("ticket_verification_commands", {}).get(ticket, [])
            if check.get("name") == failure.get("name") and check.get("command") == failure.get("command")
        ]
        if len(configured) != 1:
            return None, "failed deterministic check is absent from or ambiguous in the current ticket configuration"
        check = configured[0]
        if check.get("mandatory") is True and check.get("host_capabilities"):
            return None, "mandatory host-verification failures require their stricter reconciliation path"
        if (
            type(failure.get("exit_status")) is not int
            or failure["exit_status"] == 0
            or not isinstance(failure.get("log"), str)
            or Path(failure["log"]).name != failure["log"]
        ):
            return None, "failed deterministic check evidence is malformed"
        log_path = run_dir / failure["log"]
        try:
            log_stat = log_path.lstat()
        except OSError:
            return None, "failed deterministic check log is unavailable"
        if not stat.S_ISREG(log_stat.st_mode) or log_stat.st_size <= 0:
            return None, "failed deterministic check log is unsafe or empty"
        try:
            log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None, "failed deterministic check log is unreadable"
        return {
            "ticket": ticket,
            "run_id": run_id,
            "starting_head": starting_head,
            "fingerprint": fingerprint,
            "files": list(files),
            "failed_check": failure["name"],
            "failed_command": list(failure["command"]),
            "failure_log": str(log_path.relative_to(self.root)),
            "failure": deepcopy(failure),
        }, None

    def _append_audit_event(self, state: dict[str, Any], kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        events = state.setdefault("audit_events", [])
        if not isinstance(events, list):
            raise SupervisorError("state audit history is malformed")
        predecessor: str | None = None
        for recorded in events:
            if not isinstance(recorded, dict) or recorded != audit_event(
                recorded.get("kind"), recorded.get("payload"), predecessor,
            ):
                raise SupervisorError("state audit history is malformed")
            predecessor = recorded["event_id"]
        event = audit_event(kind, payload, predecessor)
        if event not in events:
            events.append(event)
        return event

    def recover_generic_verification_failure(self) -> dict[str, Any]:
        """Open one validated generic verification failure for bounded repair only."""
        state = self.load_state()
        context = state.get("recovery_context") or {}
        if state.get("phase") == "RECOVER_MODEL" and context.get("kind") == "generic_verification_failure":
            evidence, error = self._generic_verification_failure_checkpoint(state, require_phase=False)
            if error is not None or evidence is None or context.get("recovery_evidence") != evidence:
                raise SupervisorError("generic verification recovery checkpoint is stale or contradictory")
            matching = [
                event for event in state.get("audit_events", [])
                if isinstance(event, dict)
                and event.get("kind") == "generic_verification_failure_recovery"
                and event.get("payload") == evidence
            ]
            if len(matching) != 1:
                raise SupervisorError("generic verification recovery audit evidence is missing or ambiguous")
            # Reuse the append-only validator without appending: a malformed
            # predecessor chain is not durable recovery evidence.
            events = state.get("audit_events")
            if not isinstance(events, list):
                raise SupervisorError("generic verification recovery audit evidence is malformed")
            predecessor: str | None = None
            for recorded in events:
                if not isinstance(recorded, dict) or recorded != audit_event(
                    recorded.get("kind"), recorded.get("payload"), predecessor,
                ):
                    raise SupervisorError("generic verification recovery audit evidence is malformed")
                predecessor = recorded["event_id"]
            return state
        evidence, error = self._generic_verification_failure_checkpoint(state)
        if error is not None or evidence is None:
            raise SupervisorError("generic verification recovery is unavailable: " + str(error))
        self._append_audit_event(state, "generic_verification_failure_recovery", evidence)
        self.transition(
            state, "RECOVER_MODEL",
            "Validated generic deterministic verification failure is ready for bounded same-ticket repair; "
            "a separately quota-authorized model invocation is required.",
            recovery_context={
                "kind": "generic_verification_failure", "role": "implementation",
                "ticket": evidence["ticket"], "starting_head": evidence["starting_head"],
                "fingerprint": evidence["fingerprint"], "prior_run_id": evidence["run_id"],
                "reason": "generic_deterministic_verification_failure",
                "preserved_files": evidence["files"], "failed_verification": evidence["failure"],
                "recovery_evidence": evidence,
            },
        )
        return state

    def recover_verification_failure(self) -> dict[str, Any]:
        """Reconcile a falsely blocked, content-identical host verification failure."""
        state = self.load_state()
        if state.get("phase") not in {"VERIFICATION_FAILED", "GIT_BLOCKED"}:
            raise SupervisorError(
                "verification-failure reconciliation requires VERIFICATION_FAILED or GIT_BLOCKED"
            )
        active = state.get("active_run") or {}
        if active.get("role") != "implementation" or not self._model_checkpoint_matches(active):
            raise SupervisorError(
                "preserved product content does not exactly match the failed run's model checkpoint"
            )
        failure = self._failed_host_verification(active)
        if failure is None:
            raise SupervisorError("no single recorded mandatory host verification failure is recoverable")
        state.setdefault("verification_failure_reconciliations", []).append({
            "at": isoformat(self.now()), "ticket": active["ticket"], "run_id": active["id"],
            "from_phase": state["phase"], "head": self.git.head(),
            "fingerprint": self.git.fingerprint(), "failed_check": failure["name"],
            "failure_log": failure["log"],
        })
        self._transition_to_verification_failure_recovery(state, failure)
        return state

    def reconcile_verification_evidence(self) -> dict[str, Any]:
        """Re-evaluate one exit-zero failed host check using the current evidence policy."""
        state = self.load_state()
        if state.get("phase") != "VERIFICATION_FAILED":
            raise SupervisorError("verification-evidence reconciliation requires VERIFICATION_FAILED")
        active = state.get("active_run") or {}
        if not self._model_checkpoint_matches(active):
            raise SupervisorError("preserved product content no longer matches its model checkpoint")
        failed = [
            item for item in active.get("verification_results", [])
            if item.get("passed") is False and item.get("exit_status") == 0
        ]
        if len(failed) != 1:
            raise SupervisorError("verification-evidence reconciliation requires one exit-zero failed check")
        result = failed[0]
        configured = [
            check
            for check in self.policy.get("ticket_verification_commands", {}).get(active.get("ticket"), [])
            if check.get("name") == result.get("name")
            and check.get("command") == result.get("command")
            and check.get("mandatory") is True
            and check.get("host_capabilities") == result.get("host_capabilities")
        ]
        if len(configured) != 1:
            raise SupervisorError("failed check does not match one mandatory configured host verification")
        log_name = result.get("log")
        if not isinstance(log_name, str) or Path(log_name).name != log_name:
            raise SupervisorError("failed verification log path is invalid")
        log_path = self.runs_dir / str(active.get("id", "")) / log_name
        try:
            output = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            raise SupervisorError(f"failed verification log is unavailable: {error}") from error
        errors = self._verification_output_errors(configured[0], output)
        if errors:
            raise SupervisorError("recorded verification evidence still fails closed: " + "; ".join(errors))

        previous_errors = result.pop("evidence_errors", [])
        result.update({
            "passed": True,
            "evidence_reconciled_at": isoformat(self.now()),
            "superseded_evidence_errors": previous_errors,
        })
        run_dir = self.runs_dir / active["id"]
        atomic_write_json(run_dir / "checks.json", active["verification_results"])
        state.setdefault("verification_evidence_reconciliations", []).append({
            "at": isoformat(self.now()), "ticket": active["ticket"], "run_id": active["id"],
            "check": result["name"], "log": str(log_path.relative_to(self.root)),
            "exit_status": result["exit_status"], "head": self.git.head(),
            "fingerprint": self.git.fingerprint(), "superseded_errors": previous_errors,
        })
        self.transition(
            state, "VERIFYING",
            "Recorded exit-zero host verification evidence passed the corrected deterministic parser; "
            "normal verification completion and scope validation remain pending.",
        )
        return state

    def recover_environment(self, capability: str) -> dict[str, Any]:
        """Reconcile a preserved environment report with mandatory host verification."""
        state = self.load_state()
        active = state.get("active_run") or {}
        report = active.get("report") or {}
        phase = state.get("phase")
        gate = state.get("gate") or {}
        diagnostic_reconciliation = phase == "DIAGNOSTIC_FAILED"
        eligible = (
            phase in {"RECOVER_MODEL", "GIT_BLOCKED"}
            or diagnostic_reconciliation
            or (
                phase == "PERIODIC_CHECKPOINT"
                and gate.get("kind") == "periodic"
                and gate.get("resume_phase") == "RECOVER_MODEL"
            )
        )
        if not eligible or active.get("role") != "implementation":
            raise SupervisorError(
                "environment reconciliation requires preserved implementation recovery state"
            )
        errors = validate_report(report, "implementation", str(active.get("ticket", "")))
        if errors:
            raise SupervisorError("environment reconciliation report is invalid: " + "; ".join(errors))
        actual = self.git.changed_files()
        if (
            not actual
            or actual != sorted(active.get("changed_files", []))
            or self.git.fingerprint() != active.get("post_invocation_fingerprint")
        ):
            raise SupervisorError("preserved recovery files no longer exactly match the completed invocation record")
        starting_head = active.get("starting_head")
        current_head = self.git.head()
        head_compatible = current_head == starting_head
        if starting_head and not head_compatible and self.git.is_ancestor(starting_head, current_head):
            intervening = self.git.changed_files_between(starting_head, current_head)
            head_compatible = bool(intervening) and all(
                self._is_supervisor_control_path(path) for path in intervening
            )
        if not head_compatible:
            raise SupervisorError(
                "environment reconciliation permits only committed supervisor fixes after the recorded start"
            )
        if diagnostic_reconciliation:
            diagnostic = state.get("diagnostic") or {}
            supplied = diagnostic.get("evidence_run_ids")
            before = diagnostic.get("workspace_before")
            after = diagnostic.get("workspace_after")
            if (
                diagnostic.get("status") != "classified"
                or diagnostic.get("classification") != "HOST_VERIFICATION_REQUIRED"
                or diagnostic.get("resulting_transition") != "DIAGNOSTIC_FAILED"
                or not isinstance(supplied, list)
                or validate_diagnostic_report(diagnostic.get("report"), active.get("ticket"), supplied)
                or not isinstance(before, dict)
                or before != after
            ):
                raise SupervisorError(
                    "diagnostic host-verification reconciliation evidence is stale or malformed"
                )
            handoff = self._diagnostic_verification_handoff(state, capability=capability)
        else:
            handoff = self._environment_verification_handoff(active, capability=capability)
        if handoff is None:
            raise SupervisorError(
                "reported environment blocker does not satisfy the configured mandatory host-verification handoff"
            )
        active["host_verification_handoff"] = handoff
        reconciliation = {
            "at": isoformat(self.now()), "ticket": active["ticket"], "run_id": active["id"],
            "capability": capability, "from_phase": phase, "required_checks": handoff["required_checks"],
            "head": current_head, "fingerprint": self.git.fingerprint(),
        }
        if diagnostic_reconciliation:
            reconciliation["diagnostic_run_id"] = state["diagnostic"]["run_id"]
            state["diagnostic"]["resulting_transition"] = "VERIFYING"
        state.setdefault("environment_reconciliations", []).append(reconciliation)
        if phase == "PERIODIC_CHECKPOINT":
            reconciled_gate = dict(gate)
            reconciled_gate.update({
                "resume_phase": "VERIFYING", "head": current_head,
                "fingerprint": self.git.fingerprint(),
            })
            self.transition(
                state, "PERIODIC_CHECKPOINT",
                "Environment-blocked report reconciled to mandatory host verification; "
                "the periodic checkpoint remains closed until explicit release.",
                gate=reconciled_gate,
            )
        else:
            self.transition(
                state, "VERIFYING",
                "Environment-blocked report reconciled to mandatory host verification; "
                "acceptance remains unresolved until it passes.",
            )
        return state

    def run(self) -> dict[str, Any]:
        try:
            return self._run_loop()
        except KeyboardInterrupt:
            state = self.load_state()
            self._interrupt_between_stages(state, "keyboard_interrupt")
            return state

    def _run_loop(self) -> dict[str, Any]:
        state = self.load_state()
        if state.get("version") != STATE_VERSION:
            raise SupervisorError("legacy state is inspection-only; run state-migration-dry-run then state-migration-apply")
        if state["phase"] in QUOTA_STATES and state.get("quota_resume_phase"):
            if state["phase"] == "QUOTA_EXHAUSTED":
                snapshot = self.quota.snapshot()
                exhausted_at = parse_datetime(state["quota_exhausted_at"])
                if snapshot is None or parse_datetime(str(snapshot.get("observed_at", ""))) <= exhausted_at:
                    return state
            state["phase"] = state.pop("quota_resume_phase")
            state.pop("pending_role", None)
            state.pop("quota_exhausted_at", None)
            self.save_state(state)
        while True:
            phase = state["phase"]
            if self.stop_path.exists() and phase not in TERMINAL_STATES:
                self._interrupt_between_stages(state, "operator_stop")
                break
            if phase == "READY":
                if self._maybe_periodic_gate(state, "READY"):
                    break
                self._emit(state["current_ticket"], "quota check", "RUNNING")
                observation_id = self._guard_quota(state, "implementation", "READY")
                if observation_id is None:
                    self._emit(state["current_ticket"], "quota check", f"STOP · {state['phase']}")
                    break
                self._emit(state["current_ticket"], "quota check", "OK")
                try:
                    self._invoke(state, "implementation", observation_id)
                except SupervisorError as error:
                    self.transition(state, "GIT_BLOCKED", str(error))
                continue
            if phase == "RECOVER_MODEL":
                context = state.get("recovery_context") or {}
                role = context.get("role", "implementation")
                if self._maybe_trigger_diagnostic(state):
                    continue
                if self._maybe_periodic_gate(state, "RECOVER_MODEL"):
                    break
                self._emit(state["current_ticket"], "recovery quota check", "RUNNING")
                observation_id = self._guard_quota(state, role, "RECOVER_MODEL")
                if observation_id is None:
                    self._emit(state["current_ticket"], "recovery quota check", f"STOP · {state['phase']}")
                    break
                self._emit(state["current_ticket"], "recovery quota check", "OK")
                try:
                    self._invoke(state, role, observation_id, recovery=True)
                except SupervisorError as error:
                    self.transition(state, "GIT_BLOCKED", str(error))
                continue
            if phase == "DIAGNOSTIC_PENDING":
                self._emit(state["current_ticket"], "diagnostic quota check", "RUNNING")
                observation_id = self._guard_quota(state, "diagnostic", "DIAGNOSTIC_PENDING")
                if observation_id is None:
                    self._emit(state["current_ticket"], "diagnostic quota check", f"STOP · {state['phase']}")
                    break
                self._emit(state["current_ticket"], "diagnostic quota check", "OK")
                try:
                    self._invoke_diagnostic(state, observation_id)
                except SupervisorError as error:
                    self.transition(state, "DIAGNOSTIC_FAILED", str(error))
                continue
            if phase == "DIAGNOSTIC_REVIEW":
                if not self._recover_diagnostic_invocation(state):
                    break
                continue
            if phase == "SUPERVISOR_REPAIR_PENDING":
                self._emit(state["current_ticket"], "supervisor repair quota check", "RUNNING")
                observation_id = self._guard_quota(
                    state, "supervisor_repair", "SUPERVISOR_REPAIR_PENDING",
                )
                if observation_id is None:
                    self._emit(state["current_ticket"], "supervisor repair quota check", f"STOP · {state['phase']}")
                    break
                self._emit(state["current_ticket"], "supervisor repair quota check", "OK")
                try:
                    self._invoke_supervisor_repair(state, observation_id)
                except SupervisorError as error:
                    self.transition(state, "SUPERVISOR_REPAIR_FAILED", str(error))
                continue
            if phase == "SUPERVISOR_REPAIR":
                self.transition(
                    state, "SUPERVISOR_REPAIR_FAILED",
                    "Supervisor repair was interrupted before durable validation; product work remains preserved.",
                )
                break
            if phase == "ARCHITECTURE_PENDING":
                if self._maybe_periodic_gate(state, "ARCHITECTURE_PENDING"):
                    break
                self._emit(state["current_ticket"], "architecture quota check", "RUNNING")
                observation_id = self._guard_quota(state, "architecture", "ARCHITECTURE_PENDING")
                if observation_id is None:
                    self._emit(state["current_ticket"], "architecture quota check", f"STOP · {state['phase']}")
                    break
                self._emit(state["current_ticket"], "architecture quota check", "OK")
                try:
                    self._invoke(state, "architecture", observation_id)
                except SupervisorError as error:
                    self.transition(state, "GIT_BLOCKED", str(error))
                continue
            if phase in {"IMPLEMENTING", "ARCHITECTURE_REVIEW"}:
                if not self._recover_invocation(state):
                    break
                continue
            if phase == "VERIFYING":
                self._emit(state["current_ticket"], "verification", "RUNNING")
                if not self._run_verification(state):
                    break
                self._emit(state["current_ticket"], "verification", "PASS")
                state["last_completed_result"] = "deterministic verification passed"
                self.transition(state, "SCOPE_PENDING", "Deterministic verification passed; scope gate is next")
                if self._maybe_periodic_gate(state, "SCOPE_PENDING"):
                    break
                continue
            if phase == "SCOPE_PENDING":
                if not self._scope_gate(state):
                    self._emit(state["current_ticket"], "scope gate", f"STOP · {state['phase']}")
                    break
                self._emit(state["current_ticket"], "scope gate", "PASS")
                state["last_completed_result"] = "scope gate passed"
                self._prepare_commit(state)
                continue
            if phase == "COMMITTING":
                committed_ticket = (state.get("active_run") or {}).get("ticket", state["current_ticket"])
                if not self._finish_commit(state):
                    break
                self._emit(committed_ticket, "commit", str(state.get("last_commit", ""))[:12])
                self._emit(state["current_ticket"], "next", state["current_ticket"])
                continue
            if phase == "PUSHING":
                if not self._reconcile_push(state):
                    break
                continue
            break
        return state

    def resume(self) -> dict[str, Any]:
        state = self.load_state()
        if state.get("version") != STATE_VERSION:
            if state.get("phase") == "HUMAN_GATE":
                return state
            raise SupervisorError("legacy state is inspection-only; run state-migration-dry-run then state-migration-apply")
        if state["phase"] == "PLAN_COMPLETED":
            # A completed epoch is intentionally inert.  Even clearing an old
            # stop request would violate the read-only resume guarantee.
            return state
        if state["phase"] == "PUSHING":
            return self.run()
        if state["phase"] == "GIT_BLOCKED" and state.get("pending_push") is not None:
            self.transition(state, "PUSHING", "Retrying remote persistence for the preserved local commit.")
            return self.run()
        if self.stop_path.exists():
            self.stop_path.unlink()
        if state["phase"] == "PERIODIC_CHECKPOINT":
            self._resume_post_implementation_periodic_checkpoint(state)
            return self.run() if state["phase"] == "VERIFYING" else state
        if state["phase"] in {"IMPLEMENTING", "ARCHITECTURE_REVIEW"}:
            recovered = self._recover_invocation(state)
            if not recovered and state["phase"] == "INTERRUPTED":
                return self.resume()
            return self.run()
        if state["phase"] == "DIAGNOSTIC_REVIEW":
            self._recover_diagnostic_invocation(state)
            return self.run() if state["phase"] not in TERMINAL_STATES else state
        if state["phase"] == "SUPERVISOR_REPAIR":
            self.transition(
                state, "SUPERVISOR_REPAIR_FAILED",
                "Supervisor repair was interrupted before durable validation; no automatic commit or retry is safe.",
            )
            return state
        if state["phase"] == "INTERRUPTED":
            context = state.get("recovery_context") or {}
            kind = context.get("kind")
            if kind == "model":
                self.transition(state, "RECOVER_MODEL", "Explicit same-ticket interrupted invocation recovery requested")
                return self.run()
            if kind == "verification":
                active = state.get("active_run") or {}
                if (
                    self.git.head() != context.get("starting_head")
                    or self.git.fingerprint() != context.get("fingerprint")
                ):
                    self.transition(state, "GIT_BLOCKED", "Verification recovery tree no longer matches its interruption checkpoint")
                    return state
                active["verification_results"] = [
                    item for item in active.get("verification_results", []) if item.get("passed")
                ]
                self.transition(state, "VERIFYING", "Resuming interrupted verification without repeating the model invocation")
                return self.run()
            resume_phase = context.get("resume_phase")
            if resume_phase in {
                "READY", "ARCHITECTURE_PENDING", "DIAGNOSTIC_PENDING",
                "SUPERVISOR_REPAIR_PENDING", "VERIFYING", "SCOPE_PENDING", "COMMITTING",
            }:
                self.transition(state, resume_phase, "Resuming from an operator interruption checkpoint")
                return self.run()
            self.transition(state, "GIT_BLOCKED", "Interrupted state lacks a safe recovery phase")
            return state
        if state["phase"] == "VERIFICATION_FAILED":
            active = state.get("active_run") or {}
            # Generic deterministic failures are intentionally inert.  Retrying
            # their failed check would turn an unchanged checkpoint into a loop;
            # only the separately audited operator action may open repair.
            if self._failed_host_verification(active) is None:
                return state
            if not self._model_checkpoint_matches(active):
                self.transition(
                    state, "GIT_BLOCKED",
                    "The failed run's working tree no longer matches its model checkpoint; resume cannot guess how it changed.",
                )
                return state
            failure = self._failed_host_verification(active)
            if failure is not None:
                self._transition_to_verification_failure_recovery(state, failure)
                return self.run()
            active["verification_results"] = [
                item for item in active.get("verification_results", []) if item.get("passed")
            ]
            self.transition(state, "VERIFYING", "Retrying deterministic verification without repeating the model invocation")
            return self.run()
        if state["phase"] == "INVOCATION_FAILED":
            return self._resume_failed_invocation(state)
        if state["phase"] == "IMPLEMENTATION_FAILED":
            self._resume_blocked_implementation(state)
            return self.run() if state["phase"] == "RECOVER_MODEL" else state
        if state["phase"] == "REPORT_INVALID":
            return self._resume_invalid_report(state)
        if state["phase"] == "DIAGNOSTIC_FAILED":
            return self._resume_failed_diagnostic(state)
        if state["phase"] == "SCOPE_BLOCKED":
            return self._resume_scope_blocked(state)
        if state["phase"] == "GIT_BLOCKED":
            return self._resume_architecture_entry(state)
        if state["phase"] in {
            "READY", "RECOVER_MODEL", "ARCHITECTURE_PENDING", "DIAGNOSTIC_PENDING",
            "SUPERVISOR_REPAIR_PENDING", "VERIFYING", "SCOPE_PENDING", "COMMITTING",
        } | QUOTA_STATES:
            return self.run()
        return state

    def release_gate(self, note: str) -> dict[str, Any]:
        state = self.load_state()
        if state["phase"] not in {"HUMAN_GATE", "PERIODIC_CHECKPOINT"}:
            raise SupervisorError(f"cannot release gate from state {state['phase']}")
        if not note.strip():
            raise SupervisorError("a nonempty release note is required")
        self.git.require_repository()
        gate = state.get("gate") or {}
        if gate.get("kind") == "evidence":
            error = self._human_evidence_gate_release_error(state)
            if error is not None:
                raise SupervisorError("cannot release human evidence gate: " + error)
        elif gate.get("kind") == "periodic":
            if (
                not self._checkpoint_head_compatible(gate.get("head"))
                or self.git.fingerprint() != gate.get("fingerprint")
            ):
                raise SupervisorError(
                    "periodic checkpoint tree changed after the gate; only committed supervisor fixes "
                    "with an unchanged product-tree fingerprint are permitted"
                )
        elif not self.git.is_clean():
            raise SupervisorError("working tree must be clean before releasing a human gate")
        if gate.get("kind") == "milestone":
            self._validate_milestone_gate_plan(state, gate)
        if gate.get("kind") == "architecture_adoption":
            self._validate_architecture_adoption_gate(state, gate)
        if gate.get("kind") == "product_decision" and self.git.head() == gate.get("head"):
            raise SupervisorError("product-decision gate requires a human-authored commit before release")
        state.setdefault("gate_releases", []).append({"at": isoformat(self.now()), "note": note, "gate": gate})
        state["periodic_checkpoint"] = {
            "baseline_at": isoformat(self.now()),
            "active_runtime_seconds": 0.0,
            "completed_tickets": 0,
            "model_invocations": 0,
        }
        if gate.get("kind") == "evidence":
            active = state["active_run"]
            recovery_context = {
                "kind": "human_evidence", "role": "implementation",
                "ticket": state["current_ticket"],
                "starting_head": active["starting_head"],
                "fingerprint": self.git.fingerprint(),
                "prior_run_id": active["id"],
                "reason": "owner_evidence_recorded",
                "preserved_files": self.git.changed_files(),
                "record_paths": list(gate["record_paths"]),
                "release_note": note,
            }
            self.transition(
                state, "RECOVER_MODEL",
                f"Human evidence gate released: {note}. Same-ticket completion review is pending.",
                gate=None, blocked_report=active["report"], recovery_context=recovery_context,
            )
        else:
            resume_phase = gate.get("resume_phase", "READY") if gate.get("kind") == "periodic" else "READY"
            self.transition(state, resume_phase, f"Human gate released: {note}", gate=None)
        return state

    def _milestone_for_gate(self, gate: dict[str, Any]) -> dict[str, Any]:
        matches = [item for item in self.policy["milestones"] if item.get("name") == gate.get("name")]
        if len(matches) != 1:
            raise SupervisorError("milestone gate does not match exactly one configured milestone")
        return matches[0]

    @staticmethod
    def _next_ticket_after_completed(plan: list[str], completed: list[str]) -> str:
        """Return the first pending ticket after the furthest recorded completion.

        The supervisor was bootstrapped after feasibility work, so tickets before
        its earliest recorded completion are intentionally not reconstructed as
        missing work.
        """
        if not completed:
            raise SupervisorError("milestone reconciliation requires completed-ticket history")
        last_completed_index = max(plan.index(ticket) for ticket in completed)
        first_incomplete = next(
            (ticket for ticket in plan[last_completed_index + 1:] if ticket not in completed),
            None,
        )
        if first_incomplete is None:
            raise SupervisorError("the authoritative implementation plan has no incomplete ticket after completed work")
        return first_incomplete

    def _validate_milestone_gate_plan(
        self, state: dict[str, Any], gate: dict[str, Any]
    ) -> tuple[list[str], str, dict[str, Any]]:
        plan = self._plan_tickets()
        completed = state.get("completed_tickets")
        if not isinstance(completed, list) or any(not isinstance(ticket, str) for ticket in completed):
            raise SupervisorError("completed-ticket history is malformed")
        unknown = [ticket for ticket in completed if ticket not in plan]
        if unknown:
            raise SupervisorError("completed-ticket history contains tickets absent from the authoritative plan: " + ", ".join(unknown))
        first_incomplete = self._next_ticket_after_completed(plan, completed)
        if state.get("current_ticket") != first_incomplete:
            raise SupervisorError(
                f"milestone gate state is stale: current ticket {state.get('current_ticket')} would skip "
                f"authoritative first incomplete ticket {first_incomplete}; run ./dev gate reconcile-plan"
            )
        milestone = self._milestone_for_gate(gate)
        after, before = milestone.get("after_ticket"), milestone.get("before_ticket")
        if after not in plan or before not in plan or plan.index(before) != plan.index(after) + 1:
            raise SupervisorError("configured milestone boundary is not consecutive in the authoritative plan")
        if plan.index(first_incomplete) > plan.index(before):
            raise SupervisorError("current ticket is beyond the configured milestone boundary")
        return plan, first_incomplete, milestone

    def _periodic_plan_gate_error(self, state: dict[str, Any], gate: Any) -> str | None:
        """Return why a periodic checkpoint cannot safely open plan reconciliation."""
        if not isinstance(gate, dict) or gate.get("kind") != "periodic":
            return "plan reconciliation requires a periodic gate"
        if (
            gate.get("reason") != "PERIODIC_CHECKPOINT"
            or gate.get("resume_phase") != "READY"
            or not isinstance(gate.get("triggered_by"), list)
            or not gate["triggered_by"]
            or any(not isinstance(item, str) or not item for item in gate["triggered_by"])
        ):
            return "periodic plan reconciliation requires a durable READY checkpoint"
        if any(state.get(key) is not None for key in ("active_run", "pending_commit", "starting_head")):
            return "periodic plan reconciliation requires no active or pending run"
        current = state.get("current_ticket")
        if not isinstance(current, str) or not current or gate.get("ticket") != current:
            return "the periodic gate does not match the persisted current ticket"
        history = state.get("history")
        last = history[-1] if isinstance(history, list) and history else None
        if (
            not isinstance(last, dict)
            or last.get("to") != "PERIODIC_CHECKPOINT"
            or last.get("from") != "READY"
        ):
            return "the periodic checkpoint is not a quiescent READY transition"
        checkpoint = state.get("periodic_checkpoint")
        if (
            not isinstance(checkpoint, dict)
            or not isinstance(checkpoint.get("baseline_at"), str)
            or any(
                isinstance(checkpoint.get(key), bool)
                or not isinstance(checkpoint.get(key), (int, float))
                or checkpoint[key] < 0
                for key in ("active_runtime_seconds", "completed_tickets", "model_invocations")
            )
        ):
            return "periodic checkpoint counters are malformed"
        try:
            parse_datetime(checkpoint["baseline_at"])
        except SupervisorError:
            return "periodic checkpoint baseline is malformed"
        if self.git.branch() != self.policy["expected_branch"]:
            return "the repository branch does not match supervisor policy"
        if not self.git.is_clean():
            return "working tree must be clean before periodic plan reconciliation"
        if (
            not self._checkpoint_head_compatible(gate.get("head"))
            or self.git.fingerprint() != gate.get("fingerprint")
        ):
            return "the periodic checkpoint is stale or its product tree changed"
        try:
            plan = self._plan_tickets()
            completed = state.get("completed_tickets")
            if not isinstance(completed, list) or any(not isinstance(item, str) for item in completed):
                return "completed-ticket history is malformed"
            unknown = [item for item in completed if item not in plan]
            if unknown:
                return "completed-ticket history contains tickets absent from the authoritative plan: " + ", ".join(unknown)
            if self._next_ticket_after_completed(plan, completed) != current:
                return "the periodic checkpoint current ticket is already stale against the authoritative plan"
            self._ticket_path(current)
        except SupervisorError as error:
            return str(error)
        return None

    def _begin_periodic_plan_reconciliation(
        self, state: dict[str, Any], gate: dict[str, Any], note: str,
    ) -> dict[str, Any]:
        error = self._periodic_plan_gate_error(state, gate)
        if error is not None:
            raise SupervisorError(error)
        plan = self._plan_tickets()
        current = state["current_ticket"]
        reconciliation_head = self.git.head()
        context = {
            "kind": "periodic_plan_reconciliation",
            "role": "architecture",
            "reason": "legitimate_post_checkpoint_plan_change",
            "note": note.strip(),
            "deferred_ticket": current,
            "checkpoint_head": gate["head"],
            "reconciliation_head": reconciliation_head,
            "checkpoint_fingerprint": gate["fingerprint"],
            "original_plan": list(plan),
            "completed_tickets": list(state["completed_tickets"]),
        }
        state.setdefault("plan_reconciliation_requests", []).append({
            "at": isoformat(self.now()),
            "note": note.strip(),
            "kind": "periodic",
            "checkpoint_head": gate["head"],
            "reconciliation_head": reconciliation_head,
            "current_ticket": current,
        })
        state["periodic_checkpoint"] = {
            "baseline_at": isoformat(self.now()),
            "active_runtime_seconds": 0.0,
            "completed_tickets": 0,
            "model_invocations": 0,
        }
        self.transition(
            state, "ARCHITECTURE_PENDING",
            f"Durable periodic checkpoint released only for bounded plan reconciliation before {current}.",
            gate=None,
            blocked_report={
                "source": "periodic_checkpoint_plan_reconciliation",
                "ticket": current,
                "summary": note.strip(),
                "checkpoint_head": gate["head"],
            },
            recovery_context=context,
            architecture_resolution=None,
            ticket_timing=None,
        )
        return state

    def reconcile_plan_gate(self, note: str) -> dict[str, Any]:
        """Reconcile a durable milestone or periodic checkpoint with authoritative planning."""
        state = self.load_state()
        if not note.strip():
            raise SupervisorError("a nonempty reconciliation note is required")
        if state.get("phase") == "PERIODIC_CHECKPOINT":
            gate = state.get("gate")
            return self._begin_periodic_plan_reconciliation(state, gate, note)
        if state.get("phase") != "HUMAN_GATE":
            raise SupervisorError("plan reconciliation requires a closed HUMAN_GATE or PERIODIC_CHECKPOINT")
        gate = state.get("gate")
        if not isinstance(gate, dict) or gate.get("kind") != "milestone":
            raise SupervisorError("plan reconciliation requires a milestone gate")
        if any(state.get(key) is not None for key in ("active_run", "pending_commit", "starting_head")):
            raise SupervisorError("plan reconciliation requires no active or pending run")
        self.git.require_repository()
        if not self.git.is_clean():
            raise SupervisorError("working tree must be clean before plan reconciliation")

        plan = self._plan_tickets()
        completed = state.get("completed_tickets")
        if not isinstance(completed, list) or any(not isinstance(ticket, str) for ticket in completed):
            raise SupervisorError("completed-ticket history is malformed")
        unknown = [ticket for ticket in completed if ticket not in plan]
        if unknown:
            raise SupervisorError("completed-ticket history contains tickets absent from the authoritative plan: " + ", ".join(unknown))
        first_incomplete = self._next_ticket_after_completed(plan, completed)
        milestone = self._milestone_for_gate(gate)
        after, before = milestone.get("after_ticket"), milestone.get("before_ticket")
        if after not in plan or before not in plan or plan.index(before) != plan.index(after) + 1:
            raise SupervisorError("configured milestone boundary is not consecutive in the authoritative plan")
        if plan.index(first_incomplete) > plan.index(after):
            raise SupervisorError("the first incomplete ticket is already beyond the configured milestone")
        old_current = state.get("current_ticket")
        if old_current not in plan:
            raise SupervisorError("persisted current ticket is absent from the authoritative plan")
        if plan.index(first_incomplete) > plan.index(old_current):
            raise SupervisorError("plan reconciliation cannot advance past the persisted current ticket")

        new_gate = {
            "kind": "milestone",
            "name": milestone["name"],
            "head": self.git.head(),
            "ticket": first_incomplete,
            "after_ticket": after,
            "before_ticket": before,
        }
        if old_current == first_incomplete and all(gate.get(key) == value for key, value in new_gate.items()):
            raise SupervisorError("milestone gate is already reconciled with the authoritative plan")
        state.setdefault("plan_reconciliations", []).append({
            "at": isoformat(self.now()),
            "note": note.strip(),
            "head": self.git.head(),
            "from_current_ticket": old_current,
            "to_current_ticket": first_incomplete,
            "previous_gate": dict(gate),
            "new_gate": dict(new_gate),
        })
        self.transition(
            state,
            "HUMAN_GATE",
            f"Authoritative plan reconciled: {first_incomplete} is next; "
            f"{milestone['name']} remains closed after {after} before {before}.",
            current_ticket=first_incomplete,
            gate=new_gate,
        )
        return state

    def request_stop(self) -> tuple[bool, str]:
        """Request cooperative stop and wait briefly for a quiescent acknowledgement."""
        state = self.load_state(read_only=True)
        if state["phase"] in TERMINAL_STATES:
            return True, f"Already quiescent in {state['phase']}. Safe to power off. Resume: ./dev resume"
        atomic_write_json(self.stop_path, {
            "requested_at": isoformat(self.now()), "requesting_pid": os.getpid(),
        })
        deadline = time.monotonic() + max(15.0, float(self.policy["model_watchdog"]["terminate_grace_seconds"]) + 5)
        while time.monotonic() < deadline:
            time.sleep(0.2)
            try:
                observed = self.load_state(read_only=True)
            except SupervisorError:
                continue
            if observed["phase"] in TERMINAL_STATES:
                return True, (
                    f"Supervisor acknowledged {observed['phase']}; no child remains under normal stop handling. "
                    "Safe to power off. Resume: ./dev resume"
                )
        return False, (
            "Stop request persisted, but no quiescent acknowledgement arrived. Do NOT assume it is safe to power off; "
            "inspect ./dev status and the active process, then use ./dev resume after it stops."
        )


def repository_root() -> Path:
    configured = os.environ.get("DEV_SUPERVISOR_PROJECT_ROOT")
    return Path(configured).expanduser().resolve() if configured else Path.cwd().resolve()


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=Path(sys.argv[0]).name, description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize = subparsers.add_parser("init", help="initialize a Git repository for supervisor control")
    initialize.add_argument("repository", nargs="?", default=".")
    initialize.add_argument("--policy", type=Path)
    initialize.add_argument("--specification", type=Path, help="begin a plan-less cold-start review from this user specification")
    admission = subparsers.add_parser("admission", help="read-only existing-project assessment and exact-approval indexing")
    admission.add_argument("--repository", type=Path, default=Path("."))
    admission_sub = admission.add_subparsers(dest="admission_command", required=True)
    admission_assess = admission_sub.add_parser("assess", help="perform a shallow read-only scenario A or B inventory")
    admission_assess.add_argument("--scenario", choices=("A", "B"), required=True)
    admission_assess.add_argument("--manifest", type=Path)
    admission_begin = admission_sub.add_parser("begin", help="persist a compatible generic mapping for exact approval")
    admission_begin.add_argument("--scenario", choices=("A", "B"), required=True)
    admission_begin.add_argument("--manifest", type=Path, required=True)
    admission_sub.add_parser("status", help="show exact admission inputs and required human action")
    admission_approve = admission_sub.add_parser("approve", help="approve exact revalidated assessment and manifest digests")
    admission_approve.add_argument("--assessment-version", required=True)
    admission_approve.add_argument("--manifest-version", required=True)
    admission_index = admission_sub.add_parser("index", help="materialize one approved Supervisor-compatible provenance index")
    admission_index.add_argument("--destination", required=True)
    migration = subparsers.add_parser(
        "policy-migration-dry-run",
        help="validate a legacy policy and report its in-memory v2 conversion without writing",
    )
    migration.add_argument("--policy", type=Path, default=Path(PROJECT_POLICY_NAME))
    state_migration = subparsers.add_parser(
        "state-migration-dry-run", help="validate the supported state conversion without writing",
    )
    state_migration = subparsers.add_parser(
        "state-migration-apply", help="archive and apply the validated state conversion",
    )
    state_migration = subparsers.add_parser(
        "state-migration-rollback", help="restore the checksummed predecessor state snapshot",
    )
    engine_update = subparsers.add_parser("engine-update", help="qualify and quiescently activate an immutable engine checkout")
    engine_update_sub = engine_update.add_subparsers(dest="engine_update_command", required=True)
    engine_dry_run = engine_update_sub.add_parser("dry-run", help="qualify an isolated candidate without writes")
    engine_dry_run.add_argument("--candidate", type=Path, required=True)
    engine_activate = engine_update_sub.add_parser("activate", help="archive then atomically bind a qualified candidate")
    engine_activate.add_argument("--candidate", type=Path, required=True)
    engine_activate.add_argument("--go", action="store_true", help="record the explicit human go decision")
    engine_update_sub.add_parser("rollback", help="restore the archived binding after stopping the new generation")
    legacy_cutover = subparsers.add_parser("legacy-cutover", help="opt-in qualified 1.x to 2.0 conversion and binding handoff")
    legacy_cutover_sub = legacy_cutover.add_subparsers(dest="legacy_cutover_command", required=True)
    legacy_dry_run = legacy_cutover_sub.add_parser("dry-run", help="inspect the supported 1.x HUMAN_GATE without writing")
    legacy_dry_run.add_argument("--candidate", type=Path, required=True)
    legacy_apply = legacy_cutover_sub.add_parser("apply", help="archive, convert, and atomically switch a reviewed legacy source")
    legacy_apply.add_argument("--candidate", type=Path, required=True)
    legacy_apply.add_argument("--source-checksum", required=True, help="exact source_checksum from legacy-cutover dry-run")
    legacy_apply.add_argument("--go", action="store_true", help="record the explicit human go decision")
    legacy_cutover_sub.add_parser("rollback", help="restore the checksummed 1.x predecessor after stopping the new controller")
    subparsers.add_parser("status", help="show supervisor state and the current quota snapshot")
    subparsers.add_parser("run", help="run safe ticket progression until an explicit stop state")
    subparsers.add_parser("resume", help="resume only from a safely checkpointed state")
    environment = subparsers.add_parser(
        "recover-environment", help="reconcile a recognized preserved environment block to mandatory host verification"
    )
    environment.add_argument("--capability", required=True)
    subparsers.add_parser(
        "recover-verification-failure",
        help="reconcile a content-identical preserved host verification failure to implementation recovery",
    )
    subparsers.add_parser(
        "recover-generic-verification-failure",
        help="validate and explicitly open one preserved generic verification failure for bounded repair",
    )
    subparsers.add_parser(
        "recover-protected-snapshot",
        help="reprocess one exact legacy protected-scope control-path snapshot false block without a model call",
    )
    subparsers.add_parser(
        "reconcile-verification-evidence",
        help="re-evaluate one recorded exit-zero host check with the current deterministic evidence policy",
    )
    subparsers.add_parser("stop", help="request a cooperative stop and wait for quiescent acknowledgement")
    evidence = subparsers.add_parser("evidence", help="run deterministic checks for an evidence ticket without invoking a model")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    evidence_check = evidence_sub.add_parser("check", help="run configured evidence checks for a preserved blocked run")
    evidence_check.add_argument("--ticket", required=True)
    quota = subparsers.add_parser("quota", help="manage the quota provider")
    quota_sub = quota.add_subparsers(dest="quota_command", required=True)
    quota_sub.add_parser("show", help="show the manual quota snapshot")
    quota_sub.add_parser("migration-dry-run", help="validate a legacy quota-ledger conversion without writing")
    quota_sub.add_parser("migration-apply", help="archive and convert a legacy quota ledger")
    quota_sub.add_parser("migration-rollback", help="restore the archived legacy quota ledger")
    quota_set = quota_sub.add_parser("set", help="record a trusted manual quota observation")
    quota_set.add_argument("--five-hour", type=float, required=True)
    quota_set.add_argument("--weekly", type=float, required=True)
    gate = subparsers.add_parser("gate", help="manage explicit human gates")
    gate_sub = gate.add_subparsers(dest="gate_command", required=True)
    release = gate_sub.add_parser("release", help="release the current gate after human review")
    release.add_argument("--note", required=True)
    accept_cutover = gate_sub.add_parser(
        "accept-cutover",
        help="accept an exact qualified legacy cutover and close its non-executable final sentinel",
    )
    accept_cutover.add_argument("--note", required=True)
    reconcile = gate_sub.add_parser(
        "reconcile-plan",
        help="reconcile a closed milestone or durable periodic gate with authoritative planning",
    )
    reconcile.add_argument("--note", required=True)
    adopt = gate_sub.add_parser(
        "adopt-architecture",
        help="adopt a reviewed external architecture-plan commit at a periodic checkpoint",
    )
    adopt.add_argument("--note", required=True)
    cold_start = subparsers.add_parser("cold-start", help="manage a plan-less requirements and architecture review")
    cold_start_sub = cold_start.add_subparsers(dest="cold_start_command", required=True)
    cold_start_begin = cold_start_sub.add_parser("begin", help="capture a source specification before planning")
    cold_start_begin.add_argument("--specification", type=Path, required=True)
    cold_start_sub.add_parser("status", help="show exact review versions and the required human action")
    cold_start_submit = cold_start_sub.add_parser("submit", help="archive a requirements or architecture proposal")
    cold_start_submit.add_argument("--proposal", type=Path, required=True)
    cold_start_correct = cold_start_sub.add_parser("correct", help="invalidate approval and return to a review stage")
    cold_start_correct.add_argument("--stage", choices=("requirements", "architecture"), required=True)
    cold_start_approve_requirements = cold_start_sub.add_parser("approve-requirements", help="approve one exact requirements revision")
    cold_start_approve_requirements.add_argument("--requirements-version", required=True)
    cold_start_approve_architecture = cold_start_sub.add_parser("approve-architecture", help="approve exact requirements and architecture revisions")
    cold_start_approve_architecture.add_argument("--requirements-version", required=True)
    cold_start_approve_architecture.add_argument("--architecture-version", required=True)
    cold_start_plan = cold_start_sub.add_parser("plan", help="materialize a plan only after exact two-version approval")
    cold_start_plan.add_argument("--source", type=Path, required=True)
    cold_start_plan.add_argument("--requirements-version", required=True)
    cold_start_plan.add_argument("--architecture-version", required=True)
    backlog = subparsers.add_parser("backlog", help="review bounded backlog work into a separately approved next epoch")
    backlog_sub = backlog.add_subparsers(dest="backlog_command", required=True)
    backlog_begin = backlog_sub.add_parser("begin", help="select bounded non-executable backlog items after plan completion")
    backlog_begin.add_argument("--selection", type=Path, required=True)
    backlog_sub.add_parser("status", help="show backlog review state and required human action")
    backlog_submit = backlog_sub.add_parser("submit", help="archive a requirements or architecture-delta revision")
    backlog_submit.add_argument("--proposal", type=Path, required=True)
    backlog_requirements = backlog_sub.add_parser("approve-requirements", help="approve the exact backlog requirements revision")
    backlog_requirements.add_argument("--requirements-version", required=True)
    backlog_architecture = backlog_sub.add_parser("approve-architecture", help="approve exact backlog requirements and architecture revisions")
    backlog_architecture.add_argument("--requirements-version", required=True)
    backlog_architecture.add_argument("--architecture-version", required=True)
    backlog_materialize = backlog_sub.add_parser("materialize", help="create the immutable next epoch from exact approvals")
    backlog_materialize.add_argument("--plan-source", type=Path, required=True)
    backlog_materialize.add_argument("--index-source", type=Path, required=True)
    backlog_materialize.add_argument("--tickets-directory", type=Path, required=True)
    backlog_materialize.add_argument("--ticket-lineage", type=Path, required=True)
    improvement = subparsers.add_parser("improvement", help="review an explicitly triggered, capability-gated out-of-plan improvement")
    improvement_sub = improvement.add_subparsers(dest="improvement_command", required=True)
    improvement_request = improvement_sub.add_parser("request", help="record an explicit user trigger; disabled capability writes nothing")
    improvement_request.add_argument("--kind", choices=("user_improvement", "self_development"), required=True)
    improvement_request.add_argument("--trigger", required=True)
    improvement_request.add_argument("--description", required=True)
    improvement_sub.add_parser("status", help="read the improvement workflow without mutation")
    improvement_submit = improvement_sub.add_parser("submit-architecture", help="archive an architecture-impact revision")
    improvement_submit.add_argument("--proposal", type=Path, required=True)
    improvement_approve = improvement_sub.add_parser("approve-architecture", help="approve one exact architecture-impact revision")
    improvement_approve.add_argument("--revision", required=True)
    improvement_plan = improvement_sub.add_parser("materialize-plan", help="validate and archive a bounded plan and its ticket files")
    improvement_plan.add_argument("--plan-source", type=Path, required=True)
    improvement_plan.add_argument("--tickets-directory", type=Path, required=True)
    improvement_sub.add_parser("stage-successor", help="copy a self-development successor into isolation; never activate it")
    return parser


def main(arguments: list[str] | None = None) -> int:
    args = build_parser().parse_args(arguments)
    if args.command == "init":
        try:
            print_json(initialize_repository(Path(args.repository), args.policy, args.specification))
            return 0
        except SupervisorError as error:
            print(f"dev supervisor: {error}", file=sys.stderr)
            return 2
    if args.command == "policy-migration-dry-run":
        try:
            policy = read_json(args.policy.expanduser().resolve())
            converted, migration_report = validate_project_policy(policy)
            print_json({
                "migration": migration_report or {
                    "from_version": POLICY_VERSION,
                    "to_version": POLICY_VERSION,
                    "removed_fields": [],
                    "writes_required": False,
                },
                "effective_capabilities": converted["capabilities"],
            })
            return 0
        except SupervisorError as error:
            print(f"dev supervisor: {error}", file=sys.stderr)
            return 2
    if args.command == "admission":
        try:
            root = args.repository.expanduser().resolve()
            if args.admission_command == "assess":
                result = assess_existing_project(root, args.scenario, args.manifest)
            else:
                review = AdmissionReview(root)
                if args.admission_command == "begin":
                    result = review.begin(args.scenario, args.manifest)
                elif args.admission_command == "status":
                    result = review.status()
                elif args.admission_command == "approve":
                    result = review.approve(args.assessment_version, args.manifest_version)
                else:
                    result = review.materialize_index(args.destination)
            print_json(result)
            return 0
        except SupervisorError as error:
            print(f"dev supervisor: {error}", file=sys.stderr)
            return 2
    try:
        supervisor = Supervisor(repository_root(), progress=print)
        if args.command == "cold-start":
            with supervisor.operation_lock():
                if args.cold_start_command == "begin":
                    state = supervisor.begin_cold_start(args.specification)
                elif args.cold_start_command == "status":
                    print_json(supervisor.cold_start_status())
                    return 0
                elif args.cold_start_command == "submit":
                    state = supervisor.submit_cold_start_revision(args.proposal)
                elif args.cold_start_command == "correct":
                    state = supervisor.correct_cold_start(args.stage)
                elif args.cold_start_command == "approve-requirements":
                    state = supervisor.approve_cold_start_requirements(args.requirements_version)
                elif args.cold_start_command == "approve-architecture":
                    state = supervisor.approve_cold_start_architecture(
                        args.requirements_version, args.architecture_version,
                    )
                else:
                    state = supervisor.materialize_cold_start_plan(
                        args.source, args.requirements_version, args.architecture_version,
                    )
            print_json({**state, "required_human_action": supervisor.cold_start_status()["required_human_action"]})
            return 0
        if args.command == "backlog":
            with supervisor.operation_lock():
                if args.backlog_command == "begin":
                    result = supervisor.begin_backlog_cycle(args.selection)
                elif args.backlog_command == "status":
                    print_json(supervisor.backlog_cycle_status())
                    return 0
                elif args.backlog_command == "submit":
                    result = supervisor.submit_backlog_revision(args.proposal)
                elif args.backlog_command == "approve-requirements":
                    result = supervisor.approve_backlog_requirements(args.requirements_version)
                elif args.backlog_command == "approve-architecture":
                    result = supervisor.approve_backlog_architecture(args.requirements_version, args.architecture_version)
                else:
                    result = supervisor.materialize_backlog_epoch(args.plan_source, args.index_source, args.tickets_directory, args.ticket_lineage)
            print_json({**result, "required_human_action": supervisor.backlog_cycle_status()["required_human_action"]})
            return 0
        if args.command == "improvement":
            if args.improvement_command == "status":
                print_json(supervisor.improvement_status())
                return 0
            with supervisor.operation_lock():
                if args.improvement_command == "request":
                    result = supervisor.request_improvement(args.kind, args.trigger, args.description)
                elif args.improvement_command == "submit-architecture":
                    result = supervisor.submit_improvement_architecture(args.proposal)
                elif args.improvement_command == "approve-architecture":
                    result = supervisor.approve_improvement_architecture(args.revision)
                elif args.improvement_command == "materialize-plan":
                    result = supervisor.materialize_improvement_plan(args.plan_source, args.tickets_directory)
                else:
                    result = supervisor.stage_successor()
            print_json({**result, "required_human_action": supervisor.improvement_status()["required_human_action"]})
            return 0
        if args.command in {"state-migration-dry-run", "state-migration-apply", "state-migration-rollback"}:
            with supervisor.operation_lock():
                if args.command == "state-migration-dry-run":
                    result = supervisor.state_migration_dry_run()
                elif args.command == "state-migration-apply":
                    result = supervisor.apply_state_migration()
                else:
                    result = supervisor.rollback_state_migration()
            print_json(result)
            return 0
        if args.command == "engine-update":
            if args.engine_update_command == "dry-run":
                print_json(supervisor.engine_update_dry_run(args.candidate))
                return 0
            with supervisor.operation_lock():
                if args.engine_update_command == "activate":
                    result = supervisor.activate_engine_update(args.candidate, go=args.go)
                else:
                    result = supervisor.rollback_engine_update()
            print_json(result)
            return 0
        if args.command == "legacy-cutover":
            if args.legacy_cutover_command == "dry-run":
                print_json(supervisor.legacy_cutover_dry_run(args.candidate))
                return 0
            with supervisor.operation_lock():
                if args.legacy_cutover_command == "apply":
                    result = supervisor.apply_legacy_cutover(
                        args.candidate, source_checksum=args.source_checksum, go=args.go,
                    )
                else:
                    result = supervisor.rollback_legacy_cutover()
            print_json(result)
            return 0
        if args.command == "status":
            print(supervisor.dashboard())
            return 0
        if args.command == "stop":
            safe, message = supervisor.request_stop()
            print(message)
            return 0 if safe else 2
        if args.command == "evidence":
            if args.evidence_command != "check":
                raise SupervisorError("unknown evidence command")
            with supervisor.operation_lock():
                state = supervisor.run_evidence_checks(args.ticket)
            print_json({
                "phase": state["phase"], "current_ticket": state["current_ticket"],
                "message": state.get("message"), "last_commit": state.get("last_commit"),
                "safe_to_power_off": state["phase"] in TERMINAL_STATES,
                "resume_command": supervisor.advertised_resume_command(state),
            })
            return 0
        if args.command == "quota":
            if args.quota_command == "show":
                value = supervisor.quota.snapshot()
                if value is None:
                    print(quota_refresh_instructions(None))
                    return 2
                print_json(value)
                return 0
            with supervisor.operation_lock():
                if not isinstance(supervisor.quota, ManualQuotaProvider):
                    raise SupervisorError("quota set is only available for ManualQuotaProvider")
                if args.quota_command == "set":
                    value = supervisor.quota.set(args.five_hour, args.weekly)
                elif args.quota_command == "migration-dry-run":
                    value = supervisor.quota.migration_dry_run()
                elif args.quota_command == "migration-apply":
                    value = supervisor.quota.apply_migration()
                else:
                    value = supervisor.quota.rollback_migration()
            print_json(value)
            return 0
        with supervisor.operation_lock():
            if args.command == "gate":
                if args.gate_command == "accept-cutover":
                    state = supervisor.accept_legacy_cutover(args.note)
                elif args.gate_command == "reconcile-plan":
                    state = supervisor.reconcile_plan_gate(args.note)
                elif args.gate_command == "adopt-architecture":
                    state = supervisor.adopt_external_architecture(args.note)
                else:
                    state = supervisor.release_gate(args.note)
            elif args.command == "run":
                state = supervisor.run()
            elif args.command == "recover-environment":
                state = supervisor.recover_environment(args.capability)
            elif args.command == "recover-verification-failure":
                state = supervisor.recover_verification_failure()
            elif args.command == "recover-generic-verification-failure":
                state = supervisor.recover_generic_verification_failure()
            elif args.command == "recover-protected-snapshot":
                state = supervisor.recover_protected_snapshot()
            elif args.command == "reconcile-verification-evidence":
                state = supervisor.reconcile_verification_evidence()
            else:
                state = supervisor.resume()
        print_json({
            "phase": state["phase"], "current_ticket": state["current_ticket"],
            "message": state.get("message"), "last_commit": state.get("last_commit"),
            "safe_to_power_off": state["phase"] in TERMINAL_STATES,
            "resume_command": supervisor.advertised_resume_command(state),
        })
        return 0 if state["phase"] in {"READY", "RECOVER_MODEL", "HUMAN_GATE", "PERIODIC_CHECKPOINT", "INTERRUPTED"} else 2
    except SupervisorError as error:
        print(f"dev supervisor: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
