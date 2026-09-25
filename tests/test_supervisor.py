from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "supervisor.py"
SPEC = importlib.util.spec_from_file_location("dev_supervisor", MODULE_PATH)
supervisor_module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = supervisor_module
SPEC.loader.exec_module(supervisor_module)

InvocationResult = supervisor_module.InvocationResult
CommandResult = supervisor_module.CommandResult
Supervisor = supervisor_module.Supervisor
SupervisorError = supervisor_module.SupervisorError
parse_usage_lines = supervisor_module.parse_usage_lines
run_process_with_watchdog = supervisor_module.run_process_with_watchdog
validate_codex_output_schema = supervisor_module.validate_codex_output_schema
validate_diagnostic_report = supervisor_module.validate_diagnostic_report
validate_report = supervisor_module.validate_report
initialize_repository = supervisor_module.initialize_repository

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def report(role: str, ticket: str, *, status: str = "pass", files: list[str] | None = None,
           ambiguity: bool = False, product: bool = False) -> dict:
    passed = status == "pass"
    return {
        "role": role,
        "ticket": ticket,
        "status": status,
        "acceptance_passed": passed,
        "tests_passed": passed,
        "architecture_deviation": ambiguity,
        "ambiguity": ambiguity,
        "product_decision_required": product,
        "next_ticket_safe": passed,
        "files_changed": files or [],
        "summary": f"{role} {status}",
        "blockers": ["bounded blocker"] if status == "blocked" else [],
        "checks_run": ["focused fake check"] if passed else [],
    }


class FakeModelRunner:
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls: list[tuple[str, str]] = []
        self.prompts: list[str] = []

    def invoke(self, role, ticket, prompt, run_dir, start_head, policy, schema_path):
        self.calls.append((role, ticket))
        self.prompts.append(prompt)
        if not self.actions:
            raise AssertionError("unexpected model invocation")
        action = self.actions.pop(0)
        return action(role, ticket, run_dir)


class FakeCommandRunner:
    def __init__(self, statuses=None, outputs=None):
        self.statuses = list(statuses or [])
        self.outputs = list(outputs or [])
        self.calls = 0

    def run(self, command, cwd, output_path):
        self.calls += 1
        status = self.statuses.pop(0) if self.statuses else 0
        output = self.outputs.pop(0) if self.outputs else f"fake status {status}\n"
        output_path.write_text(output, encoding="utf-8")
        return status


class InterruptingCommandRunner:
    def __init__(self):
        self.calls = 0

    def run(self, command, cwd, output_path):
        self.calls += 1
        output_path.write_text("partial verification output\n", encoding="utf-8")
        if self.calls == 1:
            raise KeyboardInterrupt
        return 0


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        git(self.root, "init", "-b", "master")
        git(self.root, "config", "user.name", "Supervisor Test")
        git(self.root, "config", "user.email", "supervisor@example.invalid")
        (self.root / "docs/architecture/tickets").mkdir(parents=True)
        (self.root / "docs/architecture/implementation-plan.md").write_text(
            "| Milestone | Tickets | Gate |\n"
            "|---|---|---|\n"
            "| 2 useful memory | 10 → 12 → 11 | pilot |\n"
            "| 3 MVP UI | 13, 15–17 | ui |\n",
            encoding="utf-8",
        )
        for number, slug in ((10, "search"), (11, "briefings"), (12, "commitments"), (13, "person-ui")):
            (self.root / f"docs/architecture/tickets/{number:02d}-{slug}.md").write_text(
                f"# T{number:02d}: {slug}\n", encoding="utf-8",
            )
        (self.root / ".gitignore").write_text(".dev-supervisor/\n", encoding="utf-8")
        (self.root / "seed.txt").write_text("seed\n", encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "Seed")
        self.policy = json.loads(
            (MODULE_PATH.parent / "tests/fixtures/reference-policy.json").read_text(encoding="utf-8")
        )
        # Ordinary lifecycle tests exercise the current observed-quota policy.
        # The fixture remains a v1 compatibility input for explicit migration tests.
        self.policy, _ = supervisor_module.migrate_legacy_policy(self.policy)
        self.policy.update({
            "implementation_plan": "docs/architecture/implementation-plan.md",
            "authoritative_documents": ["docs/architecture/implementation-plan.md"],
            "bootstrap_ticket": "T10",
            "initial_completed_tickets": [],
            "verification_commands": [{"name": "fake verification", "command": ["fake-check"]}],
        })

    def tearDown(self):
        self.temporary.cleanup()

    def make_supervisor(self, runner=None, commands=None, policy=None):
        value = Supervisor(
            self.root,
            policy=deepcopy(policy or self.policy),
            assets_dir=MODULE_PATH.parent,
            model_runner=runner or FakeModelRunner([]),
            command_runner=commands or FakeCommandRunner(),
            now=lambda: NOW,
        )
        return value

    def test_init_creates_lightweight_controlled_repository_scaffold(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            git(root, "init", "-b", "main")
            git(root, "config", "user.name", "Supervisor Test")
            git(root, "config", "user.email", "supervisor@example.invalid")
            (root / "README.md").write_text("# New project\n", encoding="utf-8")
            git(root, "add", ".")
            git(root, "commit", "-m", "Seed")

            result = initialize_repository(root)

            self.assertEqual(result["repository"], str(root))
            self.assertEqual((root / "dev").stat().st_mode & 0o111, 0o111)
            policy = json.loads((root / "dev-supervisor.json").read_text(encoding="utf-8"))
            self.assertEqual(policy["expected_branch"], "main")
            self.assertEqual(policy["bootstrap_ticket"], "T01")
            self.assertEqual(policy["supervisor_repair_repository"], "external")
            self.assertIn(".dev-supervisor/", (root / ".gitignore").read_text(encoding="utf-8"))
            binding = json.loads((root / ".dev-supervisor/engine.json").read_text(encoding="utf-8"))
            self.assertEqual(binding["engine_root"], str(MODULE_PATH.parent))
            state = json.loads((root / ".dev-supervisor/state.json").read_text(encoding="utf-8"))
            self.assertEqual((state["phase"], state["current_ticket"]), ("READY", "T01"))

            status = subprocess.run(
                [str(root / "dev"), "status"], cwd=root, text=True,
                capture_output=True, check=True,
            )
            self.assertIn("State: READY", status.stdout)
            self.assertIn("Ticket: T01", status.stdout)

            with self.assertRaisesRegex(SupervisorError, "refusing to overwrite"):
                initialize_repository(root)

    def set_quota(self, supervisor, five=90, weekly=90):
        supervisor.quota.set(five, weekly)

    @staticmethod
    def quota_authorization(observation):
        entries = observation["authorizations"]
        return entries[-1] if entries else {"status": "available"}

    def write_action(self, relative, result_report):
        def action(role, ticket, run_dir):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{role} {ticket}\n", encoding="utf-8")
            return InvocationResult(0, result_report, {
                "input_tokens": 1, "cached_input_tokens": 0,
                "output_tokens": 1, "reasoning_output_tokens": 0,
                "turn_completed_events": [],
            })
        return action

    def amend_plan_for_pilot_runtime(self):
        (self.root / "docs/architecture/implementation-plan.md").write_text(
            "| Milestone | Tickets | Gate |\n"
            "|---|---|---|\n"
            "| 0 feasibility | 00–02 | feasibility |\n"
            "| 2 useful memory | 10 → 12 → 11 | memory |\n"
            "| 2.5 Pilot-A enablement | 28 → 29 | pilot |\n"
            "| 3 MVP UI | 13, 15–17 | ui |\n",
            encoding="utf-8",
        )
        for number, slug in ((28, "local-runtime"), (29, "pilot-a-runner")):
            (self.root / f"docs/architecture/tickets/{number:02d}-{slug}.md").write_text(
                f"# T{number:02d}: {slug}\n", encoding="utf-8",
            )
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "Amend implementation plan")

    def periodic_ready_checkpoint(self, supervisor, *, current="T12", completed=None):
        state = supervisor.load_state()
        checkpoint = {
            "baseline_at": (NOW - timedelta(minutes=5)).isoformat(),
            "active_runtime_seconds": 12.5,
            "completed_tickets": 1,
            "model_invocations": 1,
        }
        gate = {
            "kind": "periodic",
            "reason": "PERIODIC_CHECKPOINT",
            "triggered_by": ["1 completed ticket reached the checkpoint"],
            "resume_phase": "READY",
            "head": git(self.root, "rev-parse", "HEAD"),
            "ticket": current,
            "fingerprint": supervisor.git.fingerprint(),
        }
        state.update({
            "phase": "PERIODIC_CHECKPOINT",
            "current_ticket": current,
            "completed_tickets": list(completed or ["T10"]),
            "active_run": None,
            "pending_commit": None,
            "starting_head": None,
            "periodic_checkpoint": checkpoint,
            "gate": gate,
            "history": [{
                "at": NOW.isoformat(), "from": "READY", "to": "PERIODIC_CHECKPOINT",
                "message": "PERIODIC_CHECKPOINT: focused fixture",
            }],
        })
        supervisor.save_state(state)
        return state

    def post_implementation_periodic_checkpoint(self, *, commands=None):
        policy = deepcopy(self.policy)
        policy["milestones"] = []
        policy["periodic_checkpoint"]["max_model_invocations"] = 1
        runner = FakeModelRunner([
            self.write_action(
                "apps/search.py",
                report("implementation", "T10", files=["apps/search.py"]),
            ),
        ])
        supervisor = self.make_supervisor(runner, commands or FakeCommandRunner(), policy)
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(state["phase"], "PERIODIC_CHECKPOINT")
        self.assertEqual(state["gate"]["resume_phase"], "VERIFYING")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        return supervisor, runner, state

    @staticmethod
    def host_handoff_policy(policy, ticket="T10"):
        policy["host_verification_capabilities"] = {
            "loopback-bind-eperm": {
                "blocker_patterns": [r"(?is)(?=.*AF_INET)(?=.*EPERM)(?=.*real-process)"],
                "completion_summary_patterns": [r"(?is)(?=.*implementation complete)(?=.*host verification)"],
                "required_report_check_patterns": [r"(?is)focused tests passed"],
            },
        }
        policy["ticket_verification_commands"] = {
            ticket: [{
                "name": "required host lifecycle check", "command": ["host-check"],
                "mandatory": True, "host_capabilities": ["loopback-bind-eperm"],
                "required_output_patterns": [r"(?m)^real process lifecycle: ok$"],
                "forbidden_output_patterns": [r"(?i)skipped"],
            }],
        }
        return policy

    @staticmethod
    def environment_report(ticket="T10", files=None):
        value = report("implementation", ticket, status="environment_blocked", files=files or ["apps/search.py"])
        value.update({
            "summary": "Implementation complete; only mandatory host verification remains.",
            "blockers": ["AF_INET real-process lifecycle unavailable with EPERM"],
            "checks_run": ["focused tests passed"],
        })
        return value

    def failed_host_checkpoint(self):
        policy = self.host_handoff_policy(deepcopy(self.policy))
        failed = self.environment_report(files=["apps/search.py", "seed.txt"])

        def action(role, ticket, run_dir):
            (self.root / "seed.txt").write_text("tracked model content\n", encoding="utf-8")
            (self.root / "apps").mkdir(exist_ok=True)
            (self.root / "apps/search.py").write_text("untracked model content\n", encoding="utf-8")
            return InvocationResult(0, failed, {})

        failure_output = (
            "test_public_flow_uses_one_runtime_dispatcher ... ERROR\n"
            "Traceback (most recent call last):\n"
            "  reminders[\"data\"][0]\n"
            "KeyError: 0\n"
        )
        runner = FakeModelRunner([action])
        commands = FakeCommandRunner(
            statuses=[0, 1], outputs=["generic: ok\n", failure_output],
        )
        supervisor = self.make_supervisor(runner, commands, policy)
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(state["phase"], "VERIFICATION_FAILED")
        return supervisor, runner, commands, state

    def failed_generic_checkpoint(self):
        policy = deepcopy(self.policy)
        policy["ticket_verification_commands"] = {
            "T10": [{"name": "ticket generic check", "command": ["ticket-check"]}],
        }

        def action(role, ticket, run_dir):
            (self.root / "apps").mkdir(exist_ok=True)
            (self.root / "apps/search.py").write_text("model content\n", encoding="utf-8")
            return InvocationResult(0, report(role, ticket, files=["apps/search.py"]), {})

        runner = FakeModelRunner([action])
        commands = FakeCommandRunner(statuses=[0, 1], outputs=["generic: ok\n", "ticket check failed\n"])
        supervisor = self.make_supervisor(runner, commands, policy)
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(state["phase"], "VERIFICATION_FAILED")
        return supervisor, runner, commands, state

    def test_generic_verification_failure_resume_is_inert_until_explicit_recovery(self):
        supervisor, runner, commands, failed = self.failed_generic_checkpoint()
        state_bytes = supervisor.state_path.read_bytes()

        resumed = supervisor.resume()

        self.assertEqual(resumed["phase"], "VERIFICATION_FAILED")
        self.assertEqual(supervisor.state_path.read_bytes(), state_bytes)
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertEqual(commands.calls, 2)
        self.assertIn(
            "./dev recover-generic-verification-failure", supervisor._next_actions(resumed),
        )
        self.assertIsNone(supervisor.advertised_resume_command(resumed))

    def test_generic_verification_recovery_audits_once_without_quota_model_or_check(self):
        supervisor, runner, commands, failed = self.failed_generic_checkpoint()
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()

        recovered = supervisor.recover_generic_verification_failure()
        repeated = supervisor.recover_generic_verification_failure()

        self.assertEqual((recovered["phase"], repeated["phase"]), ("RECOVER_MODEL", "RECOVER_MODEL"))
        events = [item for item in repeated["audit_events"] if item["kind"] == "generic_verification_failure_recovery"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["run_id"], failed["active_run"]["id"])
        self.assertEqual(events[0]["payload"]["failed_check"], "ticket generic check")
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertEqual(commands.calls, 2)

    def test_generic_verification_recovery_rejects_configuration_drift_without_mutation(self):
        supervisor, _, _, failed = self.failed_generic_checkpoint()
        state_bytes = supervisor.state_path.read_bytes()
        supervisor.policy["ticket_verification_commands"]["T10"][0]["command"] = ["changed-check"]

        with self.assertRaisesRegex(SupervisorError, "current ticket configuration"):
            supervisor.recover_generic_verification_failure()

        self.assertEqual(supervisor.state_path.read_bytes(), state_bytes)
        self.assertEqual(supervisor.load_state(read_only=True)["phase"], "VERIFICATION_FAILED")

    def test_generic_verification_recovery_cannot_reconcile_mandatory_host_failure(self):
        supervisor, _, _, _ = self.failed_host_checkpoint()
        state_bytes = supervisor.state_path.read_bytes()

        with self.assertRaisesRegex(SupervisorError, "mandatory host-verification"):
            supervisor.recover_generic_verification_failure()

        self.assertEqual(supervisor.state_path.read_bytes(), state_bytes)

    @staticmethod
    def diagnostic_report(ticket, classification, run_ids):
        return {
            "role": "diagnostic", "ticket": ticket,
            "classification": classification,
            "rationale_summary": f"bounded {classification.lower()} diagnosis",
            "evidence_run_ids": list(run_ids),
        }

    def repeated_recovery_checkpoint(self, supervisor, *, count=2, ticket="T10", environment=None):
        product = self.root / "apps/search.py"
        product.parent.mkdir(parents=True, exist_ok=True)
        product.write_text("preserved product work\n", encoding="utf-8")
        state = supervisor.load_state()
        state["current_ticket"] = ticket
        starting_head = git(self.root, "rev-parse", "HEAD")
        run_ids = []
        active_report = environment or report(
            "implementation", ticket, status="environment_blocked", files=["apps/search.py"],
        )
        for index in range(count):
            run_id = f"20260922T12000{index}.000000Z-implementation-{ticket.lower()}"
            run_ids.append(run_id)
            run_dir = self.root / ".dev-supervisor/runs" / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "invocation.json").write_text(
                json.dumps({"completed": True, "exit_status": 0}), encoding="utf-8",
            )
            (run_dir / "process-outcome.json").write_text(
                json.dumps({"completed": True, "exit_status": 0}), encoding="utf-8",
            )
            (run_dir / "final-report.json").write_text(json.dumps(active_report), encoding="utf-8")
            (run_dir / "changed-files.json").write_text(json.dumps(["apps/search.py"]), encoding="utf-8")
            (run_dir / "diff-summary.txt").write_text("apps/search.py | 1 +\n", encoding="utf-8")
            state.setdefault("history", []).extend([
                {
                    "at": NOW.isoformat(), "from": "RECOVER_MODEL", "to": "IMPLEMENTING",
                    "message": f"implementation invocation {run_id} started",
                },
                {
                    "at": NOW.isoformat(), "from": "IMPLEMENTING", "to": "RECOVER_MODEL",
                    "message": "preserved same-ticket recovery",
                },
            ])
        fingerprint = supervisor.git.fingerprint()
        state.update({
            "phase": "RECOVER_MODEL",
            "active_run": {
                "id": run_ids[-1], "role": "implementation", "ticket": ticket,
                "starting_head": starting_head, "changed_files": ["apps/search.py"],
                "post_invocation_fingerprint": fingerprint, "report": active_report,
                "verification_results": [], "recovery": True,
            },
            "recovery_context": {
                "kind": "environment", "role": "implementation", "ticket": ticket,
                "starting_head": starting_head, "fingerprint": fingerprint,
                "prior_run_id": run_ids[-1], "reason": "environment_capability",
                "preserved_files": ["apps/search.py"],
            },
        })
        supervisor.save_state(state)
        return state, run_ids

    def architecture_diagnostic_checkpoint(self, architecture_action):
        run_ids = []

        def diagnose(role, ticket, run_dir):
            return InvocationResult(
                0, self.diagnostic_report(ticket, "ARCHITECTURE_DECISION", run_ids), {},
            )

        runner = FakeModelRunner([diagnose, architecture_action])
        supervisor = self.make_supervisor(runner)
        blocked = report(
            "implementation", "T10", status="blocked", files=["apps/search.py"],
        )
        state, run_ids = self.repeated_recovery_checkpoint(
            supervisor, count=2, environment=blocked,
        )
        active = state["active_run"]
        active.update({
            "invocation_completed": True, "exit_code": 0, "rate_limited": False,
        })
        state["recovery_context"] = {
            "kind": "implementation_blocked", "role": "implementation",
            "ticket": "T10", "starting_head": active["starting_head"],
            "fingerprint": active["post_invocation_fingerprint"],
            "prior_run_id": active["id"], "reason": "implementation_report_blocked",
            "preserved_files": list(active["changed_files"]),
        }
        supervisor.save_state(state)
        self.set_quota(supervisor)
        waiting = supervisor.run()
        self.assertEqual(waiting["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(waiting["quota_resume_phase"], "ARCHITECTURE_PENDING")
        self.assertEqual(runner.calls, [("diagnostic", "T10")])
        return supervisor, runner, waiting

    def protected_scope_checkpoint(self, architecture_action=None):
        protected = "docs/architecture/ticket-contract.md"
        implementation = self.write_action(
            protected,
            report("implementation", "T10", files=[protected]),
        )
        actions = [implementation]
        if architecture_action is not None:
            actions.append(architecture_action)
        runner = FakeModelRunner(actions)
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(state["phase"], "SCOPE_BLOCKED")
        self.assertIn(protected, state["message"])
        return supervisor, runner, state, protected

    def invalid_architecture_report_checkpoint(self):
        def contradictory_architecture(role, ticket, run_dir):
            path = self.root / "docs/architecture/contracts.md"
            path.write_text("# Preserved architecture delta\n", encoding="utf-8")
            return InvocationResult(
                0,
                report(
                    role, ticket, files=["docs/architecture/contracts.md"], ambiguity=True,
                ),
                {},
            )

        supervisor, runner, _ = self.architecture_diagnostic_checkpoint(
            contradictory_architecture,
        )
        self.set_quota(supervisor)
        invalid = supervisor.resume()
        self.assertEqual(invalid["phase"], "REPORT_INVALID")
        self.assertEqual(runner.calls, [("diagnostic", "T10"), ("architecture", "T10")])
        return supervisor, runner, invalid

    def repaired_host_reverification_checkpoint(
        self, supervisor, *, product_changed=True, malformed_fix=False, contradictory=False,
    ):
        product = self.root / "apps/search.py"
        product.parent.mkdir(parents=True, exist_ok=True)
        product.write_text("host-exposed defect\n", encoding="utf-8")
        failed_snapshot = supervisor._product_snapshot()
        check = supervisor.policy["ticket_verification_commands"]["T10"][0]
        failed_run = "20260922T120000.000000Z-implementation-t10"
        failed_dir = supervisor.runs_dir / failed_run
        failed_dir.mkdir(parents=True)
        (failed_dir / "checks.json").write_text(json.dumps([{
            "name": check["name"], "command": check["command"],
            "exit_status": 1, "passed": False,
            "host_capabilities": check["host_capabilities"], "log": "check-02.log",
        }]), encoding="utf-8")

        host_diagnostic = "20260922T121000.000000Z-diagnostic-t10"
        host_dir = supervisor.runs_dir / host_diagnostic
        host_dir.mkdir()
        host_supplied = [failed_run]
        (host_dir / "final-report.json").write_text(json.dumps(
            self.diagnostic_report("T10", "HOST_VERIFICATION_REQUIRED", host_supplied)
        ), encoding="utf-8")
        (host_dir / "diagnostic-evidence.json").write_text(json.dumps({
            "supplied_run_ids": host_supplied,
            "git": {"product_snapshot": failed_snapshot},
        }), encoding="utf-8")

        fix_diagnostic = "20260922T122000.000000Z-diagnostic-t10"
        fix_dir = supervisor.runs_dir / fix_diagnostic
        fix_dir.mkdir()
        fix_supplied = [failed_run, host_diagnostic]
        fix_report = self.diagnostic_report("T10", "PRODUCT_FIX", fix_supplied)
        if malformed_fix:
            fix_report.pop("rationale_summary")
        (fix_dir / "final-report.json").write_text(json.dumps(fix_report), encoding="utf-8")
        (fix_dir / "diagnostic-evidence.json").write_text(json.dumps({
            "supplied_run_ids": fix_supplied,
            "git": {"product_snapshot": failed_snapshot},
        }), encoding="utf-8")

        if product_changed:
            product.write_text("repaired product work\n", encoding="utf-8")
        current_snapshot = supervisor._product_snapshot()
        environment = self.environment_report(files=["apps/search.py"])
        if contradictory:
            environment["blockers"] = ["GPU unavailable"]
        recovery_ids = [
            "20260922T123000.000000Z-implementation-t10",
            "20260922T124000.000000Z-implementation-t10",
        ]
        for run_id in recovery_ids:
            run_dir = supervisor.runs_dir / run_id
            run_dir.mkdir()
            (run_dir / "process-outcome.json").write_text(
                json.dumps({"completed": True, "exit_status": 0}), encoding="utf-8",
            )
            (run_dir / "final-report.json").write_text(json.dumps(environment), encoding="utf-8")

        current_diagnostic = "20260922T125000.000000Z-diagnostic-t10"
        supplied = [host_diagnostic, fix_diagnostic, *recovery_ids]
        workspace = {
            "head": supervisor.git.head(), "files": supervisor.git.changed_files(),
            "fingerprint": supervisor.git.fingerprint(), "product": current_snapshot,
        }
        starting_head = supervisor.git.head()
        authorization = {
            "status": "consumed", "consumed_at": NOW.isoformat(),
            "invocation_id": recovery_ids[-1], "role": "implementation",
            "ticket": "T10", "recovery": True,
        }
        state = supervisor.load_state()
        state.update({
            "phase": "DIAGNOSTIC_FAILED", "current_ticket": "T10",
            "active_run": {
                "id": recovery_ids[-1], "role": "implementation", "ticket": "T10",
                "starting_head": starting_head, "changed_files": ["apps/search.py"],
                "post_invocation_fingerprint": supervisor.git.fingerprint(),
                "report": environment, "verification_results": [], "recovery": True,
                "quota_authorization": authorization,
            },
            "diagnostic": {
                "status": "classified", "classification": "HOST_VERIFICATION_REQUIRED",
                "ticket": "T10", "run_id": current_diagnostic,
                "report": self.diagnostic_report("T10", "HOST_VERIFICATION_REQUIRED", supplied),
                "evidence_run_ids": supplied, "completed_recovery_run_ids": recovery_ids,
                "product_snapshot_before": current_snapshot,
                "product_fingerprint_after": current_snapshot["fingerprint"],
                "workspace_before": workspace, "workspace_after": workspace,
                "resulting_transition": "DIAGNOSTIC_FAILED",
            },
            "quota_consumptions": [authorization],
        })
        state.setdefault("history", []).append({
            "at": NOW.isoformat(), "from": "DIAGNOSTIC_REVIEW", "to": "QUOTA_CHECK_REQUIRED",
            "message": "Diagnostic classified a concrete product fix.",
        })
        for run_id in recovery_ids:
            state["history"].append({
                "at": NOW.isoformat(), "from": "RECOVER_MODEL", "to": "IMPLEMENTING",
                "message": f"implementation invocation {run_id} started",
            })
        supervisor.save_state(state)
        return state, failed_snapshot

    def t28_unittest_check(self):
        return deepcopy(self.policy["ticket_verification_commands"]["T28"][0])

    @staticmethod
    def successful_unittest_output(*, multiline=False):
        if multiline:
            tests = (
                "test_public_flow_uses_one_runtime_dispatcher (test_runtime.RuntimeProcessTests.test_public_flow_uses_one_runtime_dispatcher)\n"
                "Exercise the implemented public routes through the supported process. ... "
                "/usr/lib/python3.12/unittest/case.py:589: ResourceWarning: unclosed file\n"
                "  if method() is not None:\n"
                "ResourceWarning: Enable tracemalloc to get the object allocation traceback\n"
                "ok\n"
                "test_sigint_restart_reuses_port_data_and_resets_csrf "
                "(test_runtime.RuntimeProcessTests.test_sigint_restart_reuses_port_data_and_resets_csrf) ... "
                "/usr/lib/python3.12/unittest/case.py:589: ResourceWarning: unclosed file\n"
                "  if method() is not None:\n"
                "ResourceWarning: Enable tracemalloc to get the object allocation traceback\n"
                "ok\n"
            )
        else:
            tests = (
                "test_public_flow_uses_one_runtime_dispatcher (test_runtime.RuntimeProcessTests.test_public_flow_uses_one_runtime_dispatcher) ... ok\n"
                "test_sigint_restart_reuses_port_data_and_resets_csrf (test_runtime.RuntimeProcessTests.test_sigint_restart_reuses_port_data_and_resets_csrf) ... ok\n"
            )
        return tests + "\n----------------------------------------------------------------------\nRan 9 tests in 0.885s\n\nOK\n"

    def test_terra_pass_verifies_and_commits(self):
        policy = deepcopy(self.policy)
        policy["milestones"] = [{
            "name": "test gate", "after_ticket": "T10", "before_ticket": "T12", "message": "stop",
        }]
        runner = FakeModelRunner([
            self.write_action("apps/search.py", report("implementation", "T10", files=["apps/search.py"])),
        ])
        commands = FakeCommandRunner()
        supervisor = self.make_supervisor(runner, commands, policy)
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "HUMAN_GATE")
        self.assertEqual(commands.calls, 1)
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "Implement T10 search")
        self.assertEqual(runner.calls, [("implementation", "T10")])

    def test_architecture_ambiguity_routes_to_sol_then_reruns_terra(self):
        policy = deepcopy(self.policy)
        policy["milestones"] = [{
            "name": "test gate", "after_ticket": "T10", "before_ticket": "T12", "message": "stop",
        }]

        def blocked(role, ticket, run_dir):
            return InvocationResult(0, report(role, ticket, status="blocked", ambiguity=True), {})

        runner = FakeModelRunner([
            blocked,
            self.write_action(
                "docs/architecture/contracts.md",
                report("architecture", "T10", files=["docs/architecture/contracts.md"]),
            ),
            self.write_action("apps/search.py", report("implementation", "T10", files=["apps/search.py"])),
        ])
        supervisor = self.make_supervisor(runner, FakeCommandRunner(), policy)
        self.set_quota(supervisor)

        state = supervisor.run()
        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.set_quota(supervisor)
        state = supervisor.resume()
        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(runner.calls, [
            ("implementation", "T10"), ("architecture", "T10"),
        ])
        self.set_quota(supervisor)
        state = supervisor.resume()

        self.assertEqual(state["phase"], "HUMAN_GATE")
        self.assertEqual(runner.calls, [
            ("implementation", "T10"), ("architecture", "T10"), ("implementation", "T10"),
        ])
        subjects = git(self.root, "log", "-2", "--format=%s").splitlines()
        self.assertEqual(subjects, ["Implement T10 search", "Resolve T10 architecture blocker"])

    def test_sol_product_decision_required_enters_human_gate(self):
        def blocked(role, ticket, run_dir):
            return InvocationResult(0, report(role, ticket, status="blocked", ambiguity=True), {})

        def product(role, ticket, run_dir):
            return InvocationResult(0, report(role, ticket, status="blocked", product=True), {})

        runner = FakeModelRunner([blocked, product])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)

        state = supervisor.run()
        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.set_quota(supervisor)
        state = supervisor.resume()

        self.assertEqual(state["phase"], "HUMAN_GATE")
        self.assertEqual(state["gate"]["kind"], "product_decision")
        self.assertEqual(len(runner.calls), 2)

    def test_recoverable_protected_scope_resume_progresses_to_architecture_quota_boundary(self):
        supervisor, runner, blocked, protected = self.protected_scope_checkpoint()
        product_before = (self.root / protected).read_bytes()
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()

        self.assertEqual(supervisor.advertised_resume_command(blocked), "./dev resume")
        waiting = supervisor.resume()

        self.assertEqual(waiting["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(waiting["quota_resume_phase"], "ARCHITECTURE_PENDING")
        self.assertEqual(waiting["pending_role"], "architecture")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)
        self.assertEqual((self.root / protected).read_bytes(), product_before)

    def test_protected_scope_architecture_invocation_consumes_only_fresh_quota_at_model_start(self):
        observed = []
        supervisor = None

        def approve(role, ticket, run_dir):
            observed.append(self.quota_authorization(supervisor.quota.snapshot())["status"])
            return InvocationResult(0, report(role, ticket), {})

        supervisor, runner, _, protected = self.protected_scope_checkpoint(approve)
        product_before = (self.root / protected).read_bytes()
        waiting = supervisor.resume()
        self.assertEqual(waiting["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(observed, [])

        self.set_quota(supervisor)
        state = supervisor.resume()

        self.assertEqual(observed, ["consumed"])
        self.assertEqual(runner.calls, [("implementation", "T10"), ("architecture", "T10")])
        self.assertEqual((self.root / protected).read_bytes(), product_before)
        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")

    def test_protected_paths_stay_blocked_without_exact_architecture_authorization(self):
        supervisor, _, state, _ = self.protected_scope_checkpoint()
        state["active_run"]["protected_scope_authorization"] = {
            "status": "approved", "protected_paths": ["docs/architecture/other.md"],
        }
        state["phase"] = "SCOPE_PENDING"

        passed = supervisor._scope_gate(state)

        self.assertFalse(passed)
        self.assertEqual(state["phase"], "SCOPE_BLOCKED")
        self.assertIn("authorization failed closed", state["message"])
        self.assertIsNone(supervisor.advertised_resume_command(state))

    def test_architecture_approval_returns_through_scope_and_commit_lifecycle(self):
        def approve(role, ticket, run_dir):
            return InvocationResult(0, report(role, ticket), {})

        supervisor, runner, _, protected = self.protected_scope_checkpoint(approve)
        product_before = (self.root / protected).read_bytes()
        supervisor.resume()
        self.set_quota(supervisor)

        state = supervisor.resume()

        transitions = [(item["from"], item["to"]) for item in state["history"]]
        self.assertIn(("ARCHITECTURE_REVIEW", "SCOPE_PENDING"), transitions)
        self.assertIn(("SCOPE_PENDING", "COMMITTING"), transitions)
        self.assertEqual(git(self.root, "show", "--pretty=format:", "--name-only", "HEAD"), protected)
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "Implement T10 search")
        self.assertEqual((self.root / protected).read_bytes(), product_before)
        self.assertEqual(runner.calls, [("implementation", "T10"), ("architecture", "T10")])

    def test_architecture_rejection_routes_to_bounded_product_recovery(self):
        def reject(role, ticket, run_dir):
            value = report(role, ticket, status="blocked")
            value["summary"] = "Protected contract change is not required by accepted architecture"
            value["blockers"] = ["Remove the protected contract change"]
            return InvocationResult(0, value, {})

        supervisor, runner, _, protected = self.protected_scope_checkpoint(reject)
        product_before = (self.root / protected).read_bytes()
        supervisor.resume()
        self.set_quota(supervisor)

        state = supervisor.resume()

        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(state["quota_resume_phase"], "RECOVER_MODEL")
        self.assertEqual(state["recovery_context"]["kind"], "protected_scope_rework")
        self.assertEqual(state["recovery_context"]["protected_paths"], [protected])
        self.assertEqual(runner.calls, [("implementation", "T10"), ("architecture", "T10")])
        self.assertEqual((self.root / protected).read_bytes(), product_before)
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "Seed")

    def test_protected_scope_genuine_architecture_decision_enters_human_gate(self):
        def needs_human(role, ticket, run_dir):
            value = report(role, ticket, status="blocked", product=True)
            value["summary"] = "Accepted architecture does not decide this protected contract"
            return InvocationResult(0, value, {})

        supervisor, runner, _, protected = self.protected_scope_checkpoint(needs_human)
        product_before = (self.root / protected).read_bytes()
        supervisor.resume()
        self.set_quota(supervisor)

        state = supervisor.resume()

        self.assertEqual(state["phase"], "HUMAN_GATE")
        self.assertEqual(state["gate"]["kind"], "product_decision")
        self.assertEqual(state["gate"]["source"], "protected_scope_review")
        self.assertEqual(state["gate"]["protected_paths"], [protected])
        self.assertEqual((self.root / protected).read_bytes(), product_before)
        self.assertEqual(runner.calls, [("implementation", "T10"), ("architecture", "T10")])

    def test_stale_protected_scope_checkpoint_fails_closed_without_quota_or_model(self):
        supervisor, runner, state, protected = self.protected_scope_checkpoint()
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()
        (self.root / protected).write_text("operator mutation\n", encoding="utf-8")
        state_before = (self.root / ".dev-supervisor/state.json").read_bytes()

        self.assertIsNone(supervisor.advertised_resume_command(state))
        refused = supervisor.resume()

        self.assertEqual(refused["phase"], "SCOPE_BLOCKED")
        self.assertEqual((self.root / ".dev-supervisor/state.json").read_bytes(), state_before)
        self.assertIsNone(supervisor.advertised_resume_command(refused))
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)

    def test_malformed_protected_scope_checkpoint_fails_closed(self):
        supervisor, runner, state, _ = self.protected_scope_checkpoint()
        state["active_run"].pop("verification_results")
        supervisor.save_state(state)
        state_before = (self.root / ".dev-supervisor/state.json").read_bytes()

        self.assertIsNone(supervisor.advertised_resume_command(state))
        refused = supervisor.resume()

        self.assertEqual(refused["phase"], "SCOPE_BLOCKED")
        self.assertEqual((self.root / ".dev-supervisor/state.json").read_bytes(), state_before)
        self.assertIsNone(supervisor.advertised_resume_command(refused))
        self.assertEqual(runner.calls, [("implementation", "T10")])

    def test_non_protected_scope_block_exposes_no_fake_resume(self):
        def mismatched(role, ticket, run_dir):
            path = self.root / "apps/search.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("search\n", encoding="utf-8")
            return InvocationResult(
                0, report(role, ticket, files=["apps/not-search.py"]), {},
            )

        supervisor = self.make_supervisor(FakeModelRunner([mismatched]))
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "SCOPE_BLOCKED")
        self.assertIn("do not exactly match", state["message"])
        self.assertIsNone(supervisor.advertised_resume_command(state))
        self.assertIn("operator must reconcile", supervisor._next_actions(state)[0])

        state_before = (self.root / ".dev-supervisor/state.json").read_bytes()
        refused = supervisor.resume()

        self.assertEqual((refused["phase"], refused["message"]), (state["phase"], state["message"]))
        self.assertEqual((self.root / ".dev-supervisor/state.json").read_bytes(), state_before)

    def test_required_documentation_impact_is_current_ticket_scope(self):
        (self.root / "docs/architecture/implementation-plan.md").write_text(
            "| Milestone | Tickets | Gate |\n"
            "|---|---|---|\n"
            "| 4 upgrades | F11 → 12 | cutover |\n",
            encoding="utf-8",
        )
        (self.root / "docs/architecture/tickets/f11-recovery.md").write_text(
            "# F11\n\n- Files/modules: `supervisor.py`, `tests/`.\n\n"
            "## Documentation impact\n\n"
            "`Required — recovery workflow.` Update maintained operator documentation.\n",
            encoding="utf-8",
        )
        (self.root / "docs/architecture/tickets/12-qualification.md").write_text(
            "# T12\n\n- Files/modules: `tests/`, `docs/`.\n\n"
            "## Documentation impact\n\n`Required — runbook.`\n",
            encoding="utf-8",
        )
        supervisor = self.make_supervisor()

        self.assertIn("docs/", supervisor._ticket_owned_paths("F11"))
        self.assertNotIn(("docs/", "T12"), supervisor._later_ticket_owned_paths("F11"))

    def protected_snapshot_false_block_checkpoint(self):
        """Build the exact persisted state produced by the pre-F11 count defect."""
        policy = deepcopy(self.policy)
        control = "control/review-marker.txt"
        policy["supervisor_control_paths"].append("control/")
        policy["implementation_forbidden_paths"].append("control/")

        def implementation(role, ticket, run_dir):
            architecture = self.root / "docs/architecture/ticket-contract.md"
            architecture.write_text("protected architecture delta\n", encoding="utf-8")
            marker = self.root / control
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("controller evidence\n", encoding="utf-8")
            return InvocationResult(0, report("implementation", ticket, files=[control, str(architecture.relative_to(self.root))]), {})

        runner = FakeModelRunner([implementation, lambda role, ticket, run_dir: InvocationResult(0, report(role, ticket), {})])
        supervisor = self.make_supervisor(runner, policy=policy)
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(state["phase"], "SCOPE_BLOCKED")
        supervisor.resume()
        self.set_quota(supervisor)
        state = supervisor.load_state()
        # Preserve the completed review immediately before its historical
        # count-based rejection; normal F11 behavior would now reprocess it.
        with patch.object(supervisor, "_process_protected_scope_review"):
            supervisor._invoke(state, "architecture", supervisor.quota.snapshot()["observation_id"], recovery=True)
        self.assertEqual(state["phase"], "ARCHITECTURE_REVIEW")

        # F11 fixes the comparison.  Preserve the exact terminal state that the
        # prior count-based implementation had already written before this fix.
        message = "Protected-scope architecture review was not read-only or its preserved implementation checkpoint is no longer exact."
        state["phase"] = "GIT_BLOCKED"
        state["message"] = message
        state["history"].append({"at": NOW.isoformat(), "from": "ARCHITECTURE_REVIEW", "to": "GIT_BLOCKED", "message": message})
        supervisor.save_state(state)
        return supervisor, runner, state, control

    def test_protected_snapshot_recovery_reprocesses_exact_legacy_false_block_without_model_or_quota(self):
        supervisor, runner, state, control = self.protected_snapshot_false_block_checkpoint()
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()
        report_before = deepcopy(state["active_run"]["report"])
        source = state["active_run"]["preserved_implementation_checkpoint"]["source_active"]

        recovered = supervisor.recover_protected_snapshot()

        self.assertEqual(recovered["phase"], "SCOPE_PENDING")
        self.assertEqual(runner.calls, [("implementation", "T10"), ("architecture", "T10")])
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)
        self.assertEqual(recovered["active_run"]["report"], source["report"])
        self.assertEqual(recovered["active_run"]["protected_scope_authorization"]["architecture_report"], report_before)
        self.assertIn(control, recovered["active_run"]["changed_files"])
        events = [event for event in recovered["audit_events"] if event["kind"] == "protected_snapshot_recovery"]
        self.assertEqual(len(events), 1)

    def test_protected_snapshot_recovery_rejects_changed_or_ambiguous_evidence_without_mutation(self):
        def change_ticket(supervisor, state, control):
            state["current_ticket"] = "T11"

        def change_run(supervisor, state, control):
            state["active_run"]["id"] = "other-run"

        def change_branch(supervisor, state, control):
            git(self.root, "checkout", "-b", "stale-protected-snapshot")

        def change_dirty_paths(supervisor, state, control):
            (self.root / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")

        def change_dirty_bytes(supervisor, state, control):
            (self.root / "docs/architecture/ticket-contract.md").write_text("altered\n", encoding="utf-8")

        def change_report(supervisor, state, control):
            state["active_run"]["report"]["summary"] = "altered"

        def change_artifact(supervisor, state, control):
            run_id = state["active_run"]["id"]
            (supervisor.runs_dir / run_id / "final-report.json").write_text("{}", encoding="utf-8")

        def change_quota_audit(supervisor, state, control):
            state["quota_consumptions"].pop()

        def change_fingerprint(supervisor, state, control):
            state["active_run"]["preserved_implementation_checkpoint"]["source_active"]["post_invocation_fingerprint"] = "0" * 64

        cases = {
            "ticket": change_ticket, "run": change_run, "branch": change_branch,
            "dirty paths": change_dirty_paths, "dirty bytes": change_dirty_bytes,
            "report": change_report, "artifact": change_artifact,
            "quota audit": change_quota_audit, "fingerprint": change_fingerprint,
        }
        for index, (name, mutate) in enumerate(cases.items()):
            with self.subTest(name=name):
                if index:
                    self.tearDown()
                    self.setUp()
                supervisor, runner, state, control = self.protected_snapshot_false_block_checkpoint()
                mutate(supervisor, state, control)
                supervisor.save_state(state)
                before = (self.root / ".dev-supervisor/state.json").read_bytes()
                with self.assertRaisesRegex(SupervisorError, "protected snapshot recovery is unavailable"):
                    supervisor.recover_protected_snapshot()
                self.assertEqual((self.root / ".dev-supervisor/state.json").read_bytes(), before)
                self.assertEqual(runner.calls, [("implementation", "T10"), ("architecture", "T10")])

    def test_unknown_quota_blocks_invocation(self):
        runner = FakeModelRunner([])
        state = self.make_supervisor(runner).run()
        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertIn("./dev quota set", state["message"])
        self.assertEqual(runner.calls, [])

    def test_low_five_hour_quota_blocks_invocation(self):
        runner = FakeModelRunner([])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor, five=19)
        state = supervisor.run()
        self.assertEqual(state["phase"], "QUOTA_LOW")
        self.assertIn("configured low range", state["message"])
        self.assertEqual(runner.calls, [])

    def test_low_weekly_quota_blocks_invocation(self):
        runner = FakeModelRunner([])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor, weekly=14)
        state = supervisor.run()
        self.assertEqual(state["phase"], "QUOTA_LOW")
        self.assertIn("configured low range", state["message"])
        self.assertEqual(runner.calls, [])

    def test_cli_requires_both_observed_windows_and_records_no_reset_time(self):
        (self.root / "dev-supervisor.json").write_text(json.dumps(self.policy), encoding="utf-8")
        output = StringIO()
        with patch.object(supervisor_module, "repository_root", return_value=self.root):
            with redirect_stdout(output):
                exit_code = supervisor_module.main([
                    "quota", "set", "--five-hour", "50", "--weekly", "44",
                ])

        self.assertEqual(exit_code, 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value["five_hour_percent_left"], 50.0)
        self.assertEqual(value["weekly_percent_left"], 44.0)
        self.assertNotIn("five_hour_reset_at", value)
        self.assertNotIn("weekly_reset_at", value)
        supervisor = self.make_supervisor()
        self.assertEqual(supervisor.quota.evaluate("implementation", self.policy["quota"])[0], "ok")
        dashboard = supervisor.dashboard()
        self.assertIn("Weekly: 44.0%", dashboard)

    def test_cli_rejects_removed_reset_time_inputs(self):
        (self.root / "dev-supervisor.json").write_text(json.dumps(self.policy), encoding="utf-8")
        output = StringIO()
        with patch.object(supervisor_module, "repository_root", return_value=self.root):
            with self.assertRaises(SystemExit) as error:
                supervisor_module.main([
                    "quota", "set", "--five-hour", "50", "--weekly", "44",
                    "--five-hour-reset", "2026-09-22T12:34:00+08:00",
                    "--weekly-reset", "2026-09-28T12:34:00+08:00",
                ])

        self.assertEqual(error.exception.code, 2)

    def test_omitted_quota_fields_are_null_not_copied_from_prior_observation(self):
        supervisor = self.make_supervisor()
        prior = supervisor.quota.set(90, 80)

        current = supervisor.quota.set(50, 50)

        self.assertEqual(current["weekly_percent_left"], 50)
        self.assertNotIn("five_hour_reset_at", current)
        self.assertNotIn("weekly_reset_at", current)
        ledger = json.loads((self.root / ".dev-supervisor/quota.json").read_text(encoding="utf-8"))
        self.assertEqual(ledger["observations"][-2], prior)
        self.assertEqual(ledger["observations"][-1], current)

    def test_supplied_optional_weekly_quota_still_uses_policy_reserve(self):
        supervisor = self.make_supervisor()
        supervisor.quota.set(90, weekly=14)

        result, message = supervisor.quota.evaluate("implementation", self.policy["quota"])

        self.assertEqual(result, "low")
        self.assertIn("configured low range", message)

    def test_five_hour_only_observation_still_uses_hard_reserve(self):
        supervisor = self.make_supervisor()
        supervisor.quota.set(19, 90)

        result, message = supervisor.quota.evaluate("implementation", self.policy["quota"])

        self.assertEqual(result, "low")
        self.assertIn("configured low range", message)

    def test_malformed_supplied_optional_quota_fields_fail_closed(self):
        supervisor = self.make_supervisor()
        with self.assertRaises(SupervisorError):
            supervisor.quota.set(50, weekly=float("nan"))
        supervisor.quota.set(50, 50)
        ledger_path = self.root / ".dev-supervisor/quota.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["observations"][-1]["weekly_percent_left"] = "not-a-percent"
        supervisor_module.atomic_write_json(ledger_path, ledger)

        result, _ = supervisor.quota.evaluate("implementation", self.policy["quota"])
        self.assertEqual(result, "unknown")

        error = StringIO()
        (self.root / "dev-supervisor.json").write_text(json.dumps(self.policy), encoding="utf-8")
        with patch.object(supervisor_module, "repository_root", return_value=self.root):
            with redirect_stdout(StringIO()), redirect_stderr(error), self.assertRaises(SystemExit) as exit_error:
                supervisor_module.main([
                    "quota", "set", "--five-hour", "50", "--weekly", "50",
                    "--weekly-reset", "still-not-a-timestamp",
                ])
        self.assertEqual(exit_error.exception.code, 2)
        self.assertIn("unrecognized arguments", error.getvalue())

    def test_unknown_required_five_hour_dimension_fails_closed(self):
        supervisor = self.make_supervisor()
        supervisor.quota.set(50, 50)
        ledger_path = self.root / ".dev-supervisor/quota.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["observations"][-1]["five_hour_percent_left"] = None
        supervisor_module.atomic_write_json(ledger_path, ledger)

        result, message = supervisor.quota.evaluate("implementation", self.policy["quota"])

        self.assertEqual(result, "unknown")
        self.assertIn("malformed", message)

    def test_fresh_observation_is_consumed_before_first_model_call_and_blocks_second(self):
        policy = deepcopy(self.policy)
        policy["milestones"] = []
        observed_authorization = []

        def successful(role, ticket, run_dir):
            observed_authorization.append(self.quota_authorization(supervisor.quota.snapshot()))
            path = self.root / "apps/search.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("done\n", encoding="utf-8")
            return InvocationResult(0, report(role, ticket, files=["apps/search.py"]), {})

        runner = FakeModelRunner([successful])
        supervisor = self.make_supervisor(runner, policy=policy)
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertEqual(observed_authorization[0]["status"], "consumed")
        self.assertIn("reuse count is exhausted", state["message"])
        authorization = state["quota_consumptions"][0]
        self.assertEqual(authorization["observation_id"], supervisor.quota.snapshot()["observation_id"])
        self.assertEqual(authorization["invocation_id"], observed_authorization[0]["invocation_id"])

    def test_failed_invocation_requires_new_observation_before_retry(self):
        runner = FakeModelRunner([
            lambda role, ticket, run_dir: InvocationResult(1, None, {}, error="failed"),
            lambda role, ticket, run_dir: InvocationResult(1, None, {}, error="failed again"),
        ])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)
        failed = supervisor.run()
        self.assertEqual(failed["phase"], "INVOCATION_FAILED")

        waiting = supervisor.resume()
        self.assertEqual(waiting["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(len(runner.calls), 1)

        self.set_quota(supervisor)
        retried = supervisor.resume()
        self.assertEqual(retried["phase"], "INVOCATION_FAILED")
        self.assertEqual(len(runner.calls), 2)
        ledger = json.loads((self.root / ".dev-supervisor/quota.json").read_text(encoding="utf-8"))
        self.assertEqual(len(ledger["observations"]), 2)
        self.assertEqual(
            [item["authorizations"][-1]["status"] for item in ledger["observations"]],
            ["consumed", "consumed"],
        )

    def test_t29_manual_observation_cannot_authorize_environment_recovery(self):
        self.amend_plan_for_pilot_runtime()
        policy = deepcopy(self.policy)
        policy["bootstrap_ticket"] = "T29"
        policy["initial_completed_tickets"] = ["T10", "T12", "T11", "T28"]
        blocked = report(
            "implementation", "T29", status="environment_blocked",
            files=["tools/pilot-a/runner.py"],
        )
        blocked["blockers"] = ["sandbox capability unavailable"]
        runner = FakeModelRunner([
            self.write_action("tools/pilot-a/runner.py", blocked),
        ])
        supervisor = self.make_supervisor(runner, policy=policy)
        self.set_quota(supervisor, five=30, weekly=89)

        state = supervisor.run()

        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(state["quota_resume_phase"], "RECOVER_MODEL")
        self.assertEqual(runner.calls, [("implementation", "T29")])
        self.assertIn("fresh trusted observation per call", state["message"])
        self.assertTrue(state["quota_consumptions"][0]["recovery"] is False)

    def test_one_completed_recovery_does_not_invoke_diagnostic_before_next_terra(self):
        recovery_report = report(
            "implementation", "T10", status="environment_blocked", files=["apps/search.py"],
        )
        runner = FakeModelRunner([
            self.write_action("apps/search.py", recovery_report),
        ])
        supervisor = self.make_supervisor(runner)
        self.repeated_recovery_checkpoint(supervisor, count=1)
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(runner.calls[0], ("implementation", "T10"))
        self.assertNotIn(("diagnostic", "T10"), runner.calls)
        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(state["quota_resume_phase"], "DIAGNOSTIC_PENDING")

    def test_repeated_same_ticket_recovery_requests_diagnostic_sol(self):
        runner = FakeModelRunner([])
        supervisor = self.make_supervisor(runner)
        _, run_ids = self.repeated_recovery_checkpoint(supervisor, count=2)

        state = supervisor.run()

        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(state["quota_resume_phase"], "DIAGNOSTIC_PENDING")
        self.assertEqual(state["pending_role"], "diagnostic")
        self.assertEqual(state["diagnostic"]["completed_recovery_run_ids"], run_ids)
        self.assertEqual(state["diagnostic"]["threshold"], 2)
        self.assertEqual(runner.calls, [])

    def test_t29_style_repeated_recovery_qualifies_deterministically(self):
        self.amend_plan_for_pilot_runtime()
        policy = deepcopy(self.policy)
        policy["bootstrap_ticket"] = "T29"
        runner = FakeModelRunner([])
        supervisor = self.make_supervisor(runner, policy=policy)
        _, run_ids = self.repeated_recovery_checkpoint(supervisor, count=3, ticket="T29")

        state = supervisor.run()

        self.assertEqual(state["quota_resume_phase"], "DIAGNOSTIC_PENDING")
        self.assertEqual(state["diagnostic"]["completed_recovery_count"], 3)
        self.assertEqual(state["diagnostic"]["completed_recovery_run_ids"], run_ids)

    def test_fresh_ticket_activation_resets_pre_prerequisite_recovery_window(self):
        supervisor = self.make_supervisor()
        state, old_run_ids = self.repeated_recovery_checkpoint(
            supervisor, count=2, ticket="T13",
        )
        fresh_run_id = "20260922T130000.000000Z-implementation-t13"
        state["history"].append({
            "at": NOW.isoformat(), "from": "READY", "to": "IMPLEMENTING",
            "message": f"implementation invocation {fresh_run_id} started",
        })
        supervisor.save_state(state)

        self.assertEqual(supervisor._completed_recovery_run_ids(state, "T13"), [])
        self.assertFalse(supervisor._maybe_trigger_diagnostic(state))
        self.assertEqual(state["phase"], "RECOVER_MODEL")
        self.assertEqual(len(old_run_ids), 2)

    def test_t13_environment_report_has_deterministic_host_handoff(self):
        supervisor = self.make_supervisor()
        product = self.root / "apps/search.py"
        product.parent.mkdir(parents=True, exist_ok=True)
        product.write_text("preserved T13 work\n", encoding="utf-8")
        environment = self.environment_report("T13", ["apps/search.py"])
        environment.update({
            "summary": (
                "Repaired T13 keyboard Claim-span capture so completed pointer and "
                "Shift+Arrow selections are captured without re-rendering during selection. "
                "Focused UI checks pass. The required same-origin real-process runtime "
                "verification is blocked only because this sandbox forbids socket creation "
                "(EPERM); supervisor host verification remains required."
            ),
            "blockers": [
                "Sandbox socket creation is denied: both required real-process runtime tests "
                "fail at socket.socket(... ) with PermissionError: [Errno 1] Operation not permitted."
            ],
            "checks_run": [
                "cd apps/local-ui && npm test (pass: 3 test files, 0 failures)",
                "cd apps/local-ui && node --check src/app.js (pass)",
                "git diff --check (pass)",
                "python3 -m unittest discover -s apps/local-agent/runtime/tests -v "
                "(7 unit tests passed; 2 real-process tests environment-blocked by socket EPERM)",
            ],
        })
        active = {
            "role": "implementation", "ticket": "T13", "report": environment,
            "changed_files": ["apps/search.py"],
        }

        self.assertEqual(supervisor._environment_verification_handoff(active), {
            "capability": "t13-loopback-bind-eperm",
            "required_checks": ["T13 same-origin real-process acceptance checks"],
            "report_status": "environment_blocked",
            "acceptance_resolved": False,
        })

    def test_diagnostic_consumes_exactly_one_fresh_quota_observation(self):
        supervisor = None
        run_ids = []

        def diagnose(role, ticket, run_dir):
            self.assertEqual(self.quota_authorization(supervisor.quota.snapshot())["status"], "consumed")
            return InvocationResult(
                0, self.diagnostic_report(ticket, "HUMAN_DECISION_REQUIRED", run_ids), {},
            )

        runner = FakeModelRunner([diagnose])
        supervisor = self.make_supervisor(runner)
        _, run_ids = self.repeated_recovery_checkpoint(supervisor, count=2)
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "HUMAN_GATE")
        self.assertEqual(runner.calls, [("diagnostic", "T10")])
        self.assertEqual(len(state["quota_consumptions"]), 1)
        self.assertEqual(state["quota_consumptions"][0]["role"], "diagnostic")
        self.assertEqual(self.quota_authorization(supervisor.quota.snapshot())["status"], "consumed")

    def test_product_fix_requires_another_fresh_observation_before_terra(self):
        run_ids = []

        def diagnose(role, ticket, run_dir):
            return InvocationResult(0, self.diagnostic_report(ticket, "PRODUCT_FIX", run_ids), {})

        runner = FakeModelRunner([diagnose])
        supervisor = self.make_supervisor(runner)
        _, run_ids = self.repeated_recovery_checkpoint(supervisor, count=2)
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(state["quota_resume_phase"], "RECOVER_MODEL")
        self.assertEqual(runner.calls, [("diagnostic", "T10")])
        self.assertEqual(state["quota_consumptions"][0]["role"], "diagnostic")

    def test_host_verification_classification_runs_deterministic_checks_not_terra(self):
        policy = self.host_handoff_policy(deepcopy(self.policy))
        environment = self.environment_report(files=["apps/search.py"])
        run_ids = []

        def diagnose(role, ticket, run_dir):
            return InvocationResult(
                0, self.diagnostic_report(ticket, "HOST_VERIFICATION_REQUIRED", run_ids), {},
            )

        runner = FakeModelRunner([diagnose])
        commands = FakeCommandRunner(statuses=[1], outputs=["deterministic failure\n"])
        supervisor = self.make_supervisor(runner, commands, policy)
        _, run_ids = self.repeated_recovery_checkpoint(
            supervisor, count=2, environment=environment,
        )
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "VERIFICATION_FAILED")
        self.assertEqual(runner.calls, [("diagnostic", "T10")])
        self.assertEqual(commands.calls, 1)
        self.assertEqual(state["diagnostic"]["resulting_transition"], "VERIFYING")

    def test_f04_failed_host_diagnosis_resumes_into_configured_verification_without_quota(self):
        (self.root / "docs/architecture/implementation-plan.md").write_text(
            "| Milestone | Tickets | Gate |\n"
            "|---|---|---|\n"
            "| 2 useful memory | F04 → 10 → 12 → 11 | pilot |\n"
            "| 3 MVP UI | 13, 15–17 | ui |\n",
            encoding="utf-8",
        )
        (self.root / "docs/architecture/tickets/f04-prerequisite.md").write_text(
            "# F04\n\n- Files/modules: `apps/search.py`.\n", encoding="utf-8",
        )
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "Add F04 fixture")
        environment = self.environment_report("F04", ["apps/search.py"])
        environment.update({
            "summary": (
                "F04 implementation is complete; mandatory real-process host verification remains."
            ),
            "blockers": [
                "AF_INET loopback socket creation fails with PermissionError EPERM, so the "
                "real-process runtime lifecycle check cannot run here."
            ],
            "checks_run": [
                "python3 -m unittest discover -s apps/local-agent/runtime/tests -v "
                "(7 passed; 2 real-process checks blocked)",
                "git diff --check passed",
            ],
        })
        run_ids = []

        def diagnose(role, ticket, run_dir):
            return InvocationResult(
                0, self.diagnostic_report(ticket, "HOST_VERIFICATION_REQUIRED", run_ids), {},
            )

        runner = FakeModelRunner([diagnose])
        commands = FakeCommandRunner(
            statuses=[0, 1], outputs=["generic: ok\n", "PermissionError: EPERM\n"],
        )
        legacy_policy = deepcopy(self.policy)
        legacy_policy["ticket_verification_commands"].pop("F04")
        legacy = self.make_supervisor(runner, commands, legacy_policy)
        _, run_ids = self.repeated_recovery_checkpoint(
            legacy, count=2, ticket="F04", environment=environment,
        )
        self.set_quota(legacy)

        failed = legacy.run()

        self.assertEqual(failed["phase"], "DIAGNOSTIC_FAILED")
        self.assertIn('"host_verification_handoff_candidate": null', runner.prompts[-1])
        fixed = self.make_supervisor(runner, commands)
        fixed_state = fixed.load_state()
        self.assertIsNotNone(
            fixed._diagnostic_evidence(fixed_state)["host_verification_handoff_candidate"]
        )
        self.assertEqual(
            fixed.advertised_resume_command(fixed_state), "./dev resume",
            fixed._diagnostic_failed_recovery_error(fixed_state),
        )
        product_before = fixed._product_snapshot()
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()
        consumptions_before = deepcopy(fixed_state["quota_consumptions"])

        resumed = fixed.resume()

        self.assertEqual(resumed["phase"], "VERIFICATION_FAILED")
        self.assertEqual(resumed["diagnostic"]["resulting_transition"], "VERIFYING")
        self.assertTrue(any(
            item.get("from") == "DIAGNOSTIC_FAILED" and item.get("to") == "VERIFYING"
            for item in resumed["history"]
        ))
        self.assertEqual(runner.calls, [("diagnostic", "F04")])
        self.assertEqual(commands.calls, 2)
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)
        self.assertEqual(resumed["quota_consumptions"], consumptions_before)
        self.assertEqual(fixed._product_snapshot(), product_before)

    def test_unsafe_diagnostic_failed_has_no_fake_resume(self):
        runner = FakeModelRunner([])
        supervisor = self.make_supervisor(runner)
        state = supervisor.load_state()
        state.update({
            "phase": "DIAGNOSTIC_FAILED", "active_run": None,
            "diagnostic": {"status": "classified", "classification": "PRODUCT_FIX"},
            "message": "unsupported failed diagnostic fixture",
        })
        supervisor.save_state(state)
        self.set_quota(supervisor)
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()

        self.assertIsNone(supervisor.advertised_resume_command(state))
        refused = supervisor.resume()

        self.assertEqual(refused["phase"], "DIAGNOSTIC_FAILED")
        self.assertIn("Operator reconciliation is required", refused["message"])
        self.assertIsNone(supervisor.advertised_resume_command(refused))
        self.assertEqual(runner.calls, [])
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)

    def test_prior_host_verification_same_product_snapshot_cannot_repeat(self):
        policy = self.host_handoff_policy(deepcopy(self.policy))
        commands = FakeCommandRunner()
        supervisor = self.make_supervisor(FakeModelRunner([]), commands, policy)
        state, _ = self.repaired_host_reverification_checkpoint(
            supervisor, product_changed=False,
        )
        state["phase"] = "DIAGNOSTIC_REVIEW"

        supervisor._process_diagnostic(state)

        self.assertEqual(state["phase"], "DIAGNOSTIC_FAILED")
        self.assertEqual(commands.calls, 0)

    def test_product_fix_and_changed_snapshot_permit_deterministic_host_reverification(self):
        policy = self.host_handoff_policy(deepcopy(self.policy))
        commands = FakeCommandRunner(outputs=["generic: ok\n", "real process lifecycle: ok\n"])
        runner = FakeModelRunner([])
        supervisor = self.make_supervisor(runner, commands, policy)
        self.set_quota(supervisor)
        state, failed_snapshot = self.repaired_host_reverification_checkpoint(supervisor)
        product_before = supervisor._product_snapshot()
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()
        consumptions_before = deepcopy(state["quota_consumptions"])

        reconciled = supervisor.recover_environment("loopback-bind-eperm")

        self.assertEqual(reconciled["phase"], "VERIFYING")
        self.assertNotEqual(product_before["fingerprint"], failed_snapshot["fingerprint"])
        self.assertEqual(supervisor._product_snapshot(), product_before)
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)
        self.assertEqual(reconciled["quota_consumptions"], consumptions_before)
        self.assertEqual(runner.calls, [])
        self.assertTrue(supervisor._run_verification(reconciled))
        self.assertEqual(commands.calls, 2)

    def assert_repaired_snapshot_reverification_fails_closed(self, **checkpoint_options):
        policy = self.host_handoff_policy(deepcopy(self.policy))
        supervisor = self.make_supervisor(FakeModelRunner([]), FakeCommandRunner(), policy)
        self.repaired_host_reverification_checkpoint(supervisor, **checkpoint_options)
        with self.assertRaises(SupervisorError):
            supervisor.recover_environment("loopback-bind-eperm")
        self.assertEqual(supervisor.load_state()["phase"], "DIAGNOSTIC_FAILED")

    def test_malformed_repaired_snapshot_evidence_fails_closed(self):
        self.assert_repaired_snapshot_reverification_fails_closed(malformed_fix=True)

    def test_contradictory_repaired_snapshot_evidence_fails_closed(self):
        self.assert_repaired_snapshot_reverification_fails_closed(contradictory=True)

    def test_stale_repaired_snapshot_evidence_fails_closed(self):
        policy = self.host_handoff_policy(deepcopy(self.policy))
        supervisor = self.make_supervisor(FakeModelRunner([]), FakeCommandRunner(), policy)
        self.repaired_host_reverification_checkpoint(supervisor)
        (self.root / "apps/search.py").write_text("stale mutation\n", encoding="utf-8")
        with self.assertRaises(SupervisorError):
            supervisor.recover_environment("loopback-bind-eperm")
        self.assertEqual(supervisor.load_state()["phase"], "DIAGNOSTIC_FAILED")

    def test_diagnostic_architecture_and_human_classifications_use_safe_paths(self):
        for classification, expected_phase, expected_resume in (
            ("ARCHITECTURE_DECISION", "QUOTA_CHECK_REQUIRED", "ARCHITECTURE_PENDING"),
            ("HUMAN_DECISION_REQUIRED", "HUMAN_GATE", None),
        ):
            with self.subTest(classification=classification):
                with tempfile.TemporaryDirectory() as raw:
                    root = Path(raw)
                    git(root, "init", "-b", "master")
                    git(root, "config", "user.name", "Supervisor Test")
                    git(root, "config", "user.email", "supervisor@example.invalid")
                    (root / "docs/architecture/tickets").mkdir(parents=True)
                    (root / "docs/architecture/implementation-plan.md").write_text(
                        "| Milestone | Tickets | Gate |\n|---|---|---|\n| 2 | 10 → 12 | x |\n", encoding="utf-8",
                    )
                    (root / "docs/architecture/tickets/10-search.md").write_text("# T10\n", encoding="utf-8")
                    (root / "docs/architecture/tickets/12-next.md").write_text("# T12\n", encoding="utf-8")
                    (root / ".gitignore").write_text(".dev-supervisor/\n", encoding="utf-8")
                    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
                    git(root, "add", ".")
                    git(root, "commit", "-m", "Seed")
                    policy = deepcopy(self.policy)
                    policy.update({
                        "implementation_plan": "docs/architecture/implementation-plan.md",
                        "authoritative_documents": ["docs/architecture/implementation-plan.md"],
                        "bootstrap_ticket": "T10", "initial_completed_tickets": [],
                        "verification_commands": [{"name": "fake", "command": ["fake"]}],
                    })
                    local_supervisor = Supervisor(
                        root, policy=policy, assets_dir=MODULE_PATH.parent,
                        model_runner=FakeModelRunner([]), command_runner=FakeCommandRunner(), now=lambda: NOW,
                    )
                    original_root = self.root
                    self.root = root
                    try:
                        _, local_ids = self.repeated_recovery_checkpoint(local_supervisor, count=2)

                        def diagnose(role, ticket, run_dir, ids=local_ids, value=classification):
                            return InvocationResult(0, self.diagnostic_report(ticket, value, ids), {})

                        local_supervisor.model_runner = FakeModelRunner([diagnose])
                        self.set_quota(local_supervisor)
                        state = local_supervisor.run()
                    finally:
                        self.root = original_root
                    self.assertEqual(state["phase"], expected_phase)
                    if expected_resume:
                        self.assertEqual(state["quota_resume_phase"], expected_resume)
                    else:
                        self.assertEqual(state["gate"]["kind"], "product_decision")

    def test_preserved_same_ticket_checkpoint_allows_architecture_invocation(self):
        def architecture(role, ticket, run_dir):
            return InvocationResult(0, report(role, ticket, status="fail"), {})

        supervisor, runner, waiting = self.architecture_diagnostic_checkpoint(architecture)
        product_before = supervisor._product_snapshot()
        waiting["phase"] = waiting.pop("quota_resume_phase")
        waiting.pop("pending_role", None)
        supervisor.save_state(waiting)
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "ARCHITECTURE_FAILED")
        self.assertEqual(runner.calls, [("diagnostic", "T10"), ("architecture", "T10")])
        self.assertEqual(supervisor._product_snapshot(), product_before)
        self.assertEqual(state["active_run"]["preserved_implementation_checkpoint"]["ticket"], "T10")

    def test_preserved_architecture_commit_stages_only_architecture_delta(self):
        def architecture(role, ticket, run_dir):
            path = self.root / "docs/architecture/contracts.md"
            path.write_text("# Resolved contract\n", encoding="utf-8")
            return InvocationResult(
                0, report(role, ticket, files=["docs/architecture/contracts.md"]), {},
            )

        supervisor, runner, waiting = self.architecture_diagnostic_checkpoint(architecture)
        product_before = supervisor._product_snapshot()
        self.set_quota(supervisor)

        state = supervisor.resume()

        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(state["quota_resume_phase"], "RECOVER_MODEL")
        self.assertEqual(runner.calls, [("diagnostic", "T10"), ("architecture", "T10")])
        self.assertEqual(supervisor._product_snapshot(), product_before)
        self.assertEqual(git(self.root, "show", "--pretty=format:", "--name-only", "HEAD"), "docs/architecture/contracts.md")
        self.assertEqual(
            git(self.root, "status", "--short", "--untracked-files=all"),
            "?? apps/search.py",
        )

    def test_architecture_inserted_prerequisite_replaces_same_ticket_recovery(self):
        plan_path = self.root / "docs/architecture/implementation-plan.md"
        plan_path.write_text(
            "| Milestone | Tickets | Gate |\n"
            "|---|---|---|\n"
            "| 2 useful memory | 09 → 10 → 12 → 11 | pilot |\n"
            "| 3 MVP UI | 13, 15–17 | ui |\n",
            encoding="utf-8",
        )
        (self.root / "docs/architecture/tickets/09-prior.md").write_text("# T09\n", encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "Add prior ticket")

        def architecture(role, ticket, run_dir):
            plan_path.write_text(
                "| Milestone | Tickets | Gate |\n"
                "|---|---|---|\n"
                "| 2 useful memory | 09 → F04 → 10 → 12 → 11 | pilot |\n"
                "| 3 MVP UI | 13, 15–17 | ui |\n",
                encoding="utf-8",
            )
            (self.root / "docs/architecture/tickets/f04-prerequisite.md").write_text(
                "# F04\n\n- Files/modules: `apps/search.py`.\n", encoding="utf-8",
            )
            return InvocationResult(0, report(role, ticket, files=[
                "docs/architecture/implementation-plan.md",
                "docs/architecture/tickets/f04-prerequisite.md",
            ]), {})

        supervisor, runner, waiting = self.architecture_diagnostic_checkpoint(architecture)
        waiting["completed_tickets"] = ["T09"]
        supervisor.save_state(waiting)
        product_before = supervisor._product_snapshot()
        self.set_quota(supervisor)

        state = supervisor.resume()

        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(state["quota_resume_phase"], "RECOVER_MODEL")
        self.assertEqual(state["current_ticket"], "F04")
        self.assertEqual(state["recovery_context"]["kind"], "architecture_prerequisite")
        self.assertEqual(state["recovery_context"]["deferred_ticket"], "T10")
        self.assertEqual(runner.calls, [("diagnostic", "T10"), ("architecture", "T10")])
        self.assertEqual(supervisor._product_snapshot(), product_before)

    def test_repaired_diagnostic_schedules_missing_prerequisite_with_preserved_product(self):
        (self.root / "docs/architecture/implementation-plan.md").write_text(
            "| Milestone | Tickets | Gate |\n"
            "|---|---|---|\n"
            "| 2 useful memory | 09 → F04 → 10 → 12 → 11 | pilot |\n"
            "| 3 MVP UI | 13, 15–17 | ui |\n",
            encoding="utf-8",
        )
        (self.root / "docs/architecture/tickets/09-prior.md").write_text("# T09\n", encoding="utf-8")
        (self.root / "docs/architecture/tickets/f04-prerequisite.md").write_text(
            "# F04\n\n- Files/modules: `apps/search.py`.\n", encoding="utf-8",
        )
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "Insert prerequisite")
        product = self.root / "apps/search.py"
        product.parent.mkdir(parents=True)
        product.write_text("preserved later-ticket work\n", encoding="utf-8")
        runner = FakeModelRunner([
            self.write_action(
                "apps/search.py",
                report("implementation", "F04", files=["apps/search.py"]),
            ),
        ])
        policy = deepcopy(self.policy)
        policy["ticket_verification_commands"].pop("F04", None)
        supervisor = self.make_supervisor(runner, policy=policy)
        state = supervisor.load_state()
        workspace = {
            "head": supervisor.git.head(), "files": supervisor.git.changed_files(),
            "fingerprint": supervisor.git.fingerprint(), "product": supervisor._product_snapshot(),
        }
        diagnostic_report = self.diagnostic_report("T10", "PRODUCT_FIX", [])
        state.update({
            "phase": "DIAGNOSTIC_REVIEW",
            "current_ticket": "T10",
            "completed_tickets": ["T09"],
            "diagnostic": {
                "status": "completed", "ticket": "T10", "exit_code": 0,
                "report": diagnostic_report, "evidence_run_ids": [],
                "workspace_before": workspace, "workspace_after": workspace,
                "repair_commit": supervisor.git.head(),
            },
        })
        supervisor.save_state(state)
        product_before = supervisor._product_snapshot()

        supervisor._process_diagnostic(state)

        self.assertEqual((state["phase"], state["current_ticket"]), ("QUOTA_CHECK_REQUIRED", "F04"))
        self.assertEqual(state["quota_resume_phase"], "RECOVER_MODEL")
        self.assertEqual(state["recovery_context"]["kind"], "architecture_prerequisite")
        self.assertEqual(state["recovery_context"]["deferred_ticket"], "T10")
        self.assertEqual(supervisor._product_snapshot(), product_before)

        self.set_quota(supervisor)
        resumed = supervisor.resume()

        self.assertEqual((resumed["phase"], resumed["current_ticket"]), ("QUOTA_CHECK_REQUIRED", "T10"))
        self.assertIn("F04", resumed["completed_tickets"])
        self.assertEqual(runner.calls, [("implementation", "F04")])
        self.assertEqual(git(self.root, "status", "--short", "--untracked-files=all"), "")

    def test_shared_current_ticket_path_is_not_rejected_as_later_owned(self):
        (self.root / "docs/architecture/implementation-plan.md").write_text(
            "| Milestone | Tickets | Gate |\n"
            "|---|---|---|\n"
            "| 2 useful memory | F04 → 10 → 12 → 11 | pilot |\n"
            "| 3 MVP UI | 13, 15–17 | ui |\n",
            encoding="utf-8",
        )
        (self.root / "docs/architecture/tickets/f04-prerequisite.md").write_text(
            "# F04\n\n- Files/modules: `apps/shared`.\n", encoding="utf-8",
        )
        (self.root / "docs/architecture/tickets/13-person-ui.md").write_text(
            "# T13\n\n- Files/modules: `apps/shared`.\n", encoding="utf-8",
        )
        supervisor = self.make_supervisor()

        later_owned = supervisor._later_ticket_owned_paths("F04")

        self.assertNotIn(("apps/shared", "T13"), later_owned)

    def test_preserved_architecture_entry_blocks_modified_product_without_consuming_quota(self):
        supervisor, runner, waiting = self.architecture_diagnostic_checkpoint(
            lambda role, ticket, run_dir: InvocationResult(0, report(role, ticket, status="fail"), {}),
        )
        (self.root / "apps/search.py").write_text("modified after diagnostic\n", encoding="utf-8")
        self.set_quota(supervisor)
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()

        state = supervisor.resume()

        self.assertEqual(state["phase"], "GIT_BLOCKED")
        self.assertEqual(runner.calls, [("diagnostic", "T10")])
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)
        self.assertEqual(self.quota_authorization(supervisor.quota.snapshot())["status"], "available")

    def test_preserved_architecture_entry_blocks_additional_product_without_consuming_quota(self):
        supervisor, runner, waiting = self.architecture_diagnostic_checkpoint(
            lambda role, ticket, run_dir: InvocationResult(0, report(role, ticket, status="fail"), {}),
        )
        (self.root / "apps/extra.py").write_text("unexpected extra\n", encoding="utf-8")
        self.set_quota(supervisor)
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()

        state = supervisor.resume()

        self.assertEqual(state["phase"], "GIT_BLOCKED")
        self.assertEqual(runner.calls, [("diagnostic", "T10")])
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)
        self.assertEqual(self.quota_authorization(supervisor.quota.snapshot())["status"], "available")

    def test_preserved_architecture_entry_blocks_cross_ticket_checkpoint(self):
        supervisor, runner, waiting = self.architecture_diagnostic_checkpoint(
            lambda role, ticket, run_dir: InvocationResult(0, report(role, ticket, status="fail"), {}),
        )
        waiting["recovery_context"]["ticket"] = "T12"
        waiting["diagnostic"]["origin_recovery_context"]["ticket"] = "T12"
        supervisor.save_state(waiting)
        self.set_quota(supervisor)
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()

        state = supervisor.resume()

        self.assertEqual(state["phase"], "GIT_BLOCKED")
        self.assertEqual(runner.calls, [("diagnostic", "T10")])
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)

    def test_git_blocked_clean_start_rejection_resumes_valid_architecture_checkpoint(self):
        def architecture(role, ticket, run_dir):
            return InvocationResult(0, report(role, ticket, status="fail"), {})

        supervisor, runner, waiting = self.architecture_diagnostic_checkpoint(architecture)
        waiting.pop("quota_resume_phase", None)
        waiting.pop("pending_role", None)
        waiting["phase"] = "GIT_BLOCKED"
        waiting["message"] = "working tree has unexpected pre-existing changes: apps/search.py"
        waiting["history"].append({
            "at": NOW.isoformat(), "from": "ARCHITECTURE_PENDING", "to": "GIT_BLOCKED",
            "message": waiting["message"],
        })
        supervisor.save_state(waiting)
        self.set_quota(supervisor)

        state = supervisor.resume()

        self.assertEqual(state["phase"], "ARCHITECTURE_FAILED")
        self.assertEqual(runner.calls, [("diagnostic", "T10"), ("architecture", "T10")])
        self.assertTrue(any(
            item.get("from") == "GIT_BLOCKED" and item.get("to") == "ARCHITECTURE_PENDING"
            for item in state["history"]
        ))

    def test_report_invalid_resume_enters_report_only_recovery_without_consuming_quota(self):
        supervisor, runner, invalid = self.invalid_architecture_report_checkpoint()
        product_before = supervisor._product_snapshot()
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()
        consumptions_before = deepcopy(invalid["quota_consumptions"])
        self.assertEqual(supervisor.advertised_resume_command(invalid), "./dev resume")

        waiting = supervisor.resume()

        self.assertEqual(waiting["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(waiting["quota_resume_phase"], "RECOVER_MODEL")
        self.assertEqual(waiting["recovery_context"]["kind"], "report_invalid")
        self.assertEqual(runner.calls, [("diagnostic", "T10"), ("architecture", "T10")])
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)
        self.assertEqual(waiting["quota_consumptions"], consumptions_before)
        self.assertEqual(supervisor._product_snapshot(), product_before)
        self.assertTrue(any(
            item.get("from") == "REPORT_INVALID" and item.get("to") == "RECOVER_MODEL"
            for item in waiting["history"]
        ))

    def test_malformed_replacement_report_remains_report_invalid(self):
        supervisor, runner, _ = self.invalid_architecture_report_checkpoint()
        waiting = supervisor.resume()
        runner.actions.append(
            lambda role, ticket, run_dir: InvocationResult(0, {"role": role, "ticket": ticket}, {}),
        )
        self.set_quota(supervisor)

        state = supervisor.resume()

        self.assertEqual(state["phase"], "REPORT_INVALID")
        self.assertIn("Structured report failed closed", state["message"])
        self.assertEqual(runner.calls, [
            ("diagnostic", "T10"), ("architecture", "T10"), ("architecture", "T10"),
        ])
        self.assertIn("REPORT RECOVERY RUN", runner.prompts[-1])

    def test_contradictory_replacement_report_remains_report_invalid(self):
        supervisor, runner, _ = self.invalid_architecture_report_checkpoint()
        supervisor.resume()
        runner.actions.append(
            lambda role, ticket, run_dir: InvocationResult(
                0,
                report(
                    role, ticket, files=["docs/architecture/contracts.md"], ambiguity=True,
                ),
                {},
            ),
        )
        self.set_quota(supervisor)

        state = supervisor.resume()

        self.assertEqual(state["phase"], "REPORT_INVALID")
        self.assertEqual(state["message"], "PASS report also asserted architecture deviation or ambiguity")
        self.assertEqual(runner.calls, [
            ("diagnostic", "T10"), ("architecture", "T10"), ("architecture", "T10"),
        ])

    def test_valid_replacement_report_continues_existing_architecture_pipeline(self):
        supervisor, runner, _ = self.invalid_architecture_report_checkpoint()
        implementation_before = (self.root / "apps/search.py").read_bytes()
        supervisor.resume()
        runner.actions.append(
            lambda role, ticket, run_dir: InvocationResult(
                0, report(role, ticket, files=["docs/architecture/contracts.md"]), {},
            ),
        )
        self.set_quota(supervisor)

        state = supervisor.resume()

        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(state["quota_resume_phase"], "RECOVER_MODEL")
        self.assertEqual(runner.calls, [
            ("diagnostic", "T10"), ("architecture", "T10"), ("architecture", "T10"),
        ])
        self.assertEqual((self.root / "apps/search.py").read_bytes(), implementation_before)
        self.assertEqual(
            git(self.root, "show", "--pretty=format:", "--name-only", "HEAD"),
            "docs/architecture/contracts.md",
        )
        self.assertEqual(
            git(self.root, "status", "--short", "--untracked-files=all"),
            "?? apps/search.py",
        )

    def test_report_recovery_blocks_changed_architecture_delta_before_invocation(self):
        supervisor, runner, invalid = self.invalid_architecture_report_checkpoint()
        (self.root / "docs/architecture/contracts.md").write_text(
            "# Changed after invalid report\n", encoding="utf-8",
        )
        self.set_quota(supervisor)
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()

        state = supervisor.resume()

        self.assertEqual(state["phase"], "REPORT_INVALID")
        self.assertIn("Automatic report recovery is unavailable", state["message"])
        self.assertEqual(runner.calls, [("diagnostic", "T10"), ("architecture", "T10")])
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)
        self.assertIsNone(supervisor.advertised_resume_command(state))

    def test_unrelated_report_invalid_fails_closed_with_truthful_instruction(self):
        runner = FakeModelRunner([])
        supervisor = self.make_supervisor(runner)
        state = supervisor.load_state()
        state.update({
            "phase": "REPORT_INVALID", "active_run": None,
            "message": "unsupported invalid report fixture",
        })
        state["history"].append({
            "at": NOW.isoformat(), "from": "READY", "to": "REPORT_INVALID",
            "message": state["message"],
        })
        supervisor.save_state(state)
        self.set_quota(supervisor)
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()

        refused = supervisor.resume()

        self.assertEqual(refused["phase"], "REPORT_INVALID")
        self.assertIn("Operator reconciliation is required", refused["message"])
        self.assertEqual(runner.calls, [])
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)
        self.assertIsNone(supervisor.advertised_resume_command(refused))

    def test_malformed_unknown_or_ambiguous_diagnostic_fails_closed(self):
        run_ids = ["run-a", "run-b"]
        base = self.diagnostic_report("T10", "PRODUCT_FIX", run_ids)
        self.assertTrue(validate_diagnostic_report({**base, "classification": "UNKNOWN"}, "T10", run_ids))
        self.assertTrue(validate_diagnostic_report(
            {**base, "alternative_classification": "SUPERVISOR_BUG"}, "T10", run_ids,
        ))
        self.assertTrue(validate_diagnostic_report(None, "T10", run_ids))

        runner = FakeModelRunner([])
        supervisor = self.make_supervisor(runner)
        _, supplied = self.repeated_recovery_checkpoint(supervisor, count=2)
        runner.actions.append(lambda role, ticket, run_dir: InvocationResult(
            0, {**self.diagnostic_report(ticket, "PRODUCT_FIX", supplied), "classification": "UNKNOWN"}, {},
        ))
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "DIAGNOSTIC_FAILED")
        self.assertNotIn(("implementation", "T10"), runner.calls)
        self.assertIsNone(supervisor.advertised_resume_command(state))

    def test_pending_diagnostic_survives_restart_and_periodic_checkpoint(self):
        supervisor = self.make_supervisor()
        self.repeated_recovery_checkpoint(supervisor, count=2)
        waiting = supervisor.run()
        recorded = deepcopy(waiting["diagnostic"])
        restarted = self.make_supervisor()

        restored = restarted.load_state()

        self.assertEqual(restored["diagnostic"], recorded)
        restored["phase"] = "DIAGNOSTIC_PENDING"
        restarted._checkpoint_data(restored)["model_invocations"] = 999
        self.assertTrue(restarted._maybe_periodic_gate(restored, "DIAGNOSTIC_PENDING"))
        self.assertEqual(restored["diagnostic"], recorded)
        self.assertEqual(restored["gate"]["resume_phase"], "DIAGNOSTIC_PENDING")

    def test_completed_diagnostic_artifacts_reconcile_after_restart(self):
        supervisor = self.make_supervisor()
        state, run_ids = self.repeated_recovery_checkpoint(supervisor, count=2)
        product = supervisor._product_snapshot()
        workspace = {
            "head": supervisor.git.head(), "files": supervisor.git.changed_files(),
            "fingerprint": supervisor.git.fingerprint(), "product": product,
        }
        diagnostic_run = "20260922T130000.000000Z-diagnostic-t10"
        run_dir = self.root / ".dev-supervisor/runs" / diagnostic_run
        run_dir.mkdir(parents=True)
        (run_dir / "process-outcome.json").write_text(json.dumps({
            "completed": True, "exit_status": 0, "rate_limited": False,
            "duration_seconds": 3.0,
        }), encoding="utf-8")
        (run_dir / "final-report.json").write_text(json.dumps(
            self.diagnostic_report("T10", "HUMAN_DECISION_REQUIRED", run_ids)
        ), encoding="utf-8")
        state.update({
            "phase": "DIAGNOSTIC_REVIEW",
            "diagnostic": {
                "status": "running", "ticket": "T10", "run_id": diagnostic_run,
                "evidence_run_ids": run_ids, "workspace_before": workspace,
                "product_snapshot_before": product,
            },
        })
        supervisor.save_state(state)

        restarted = self.make_supervisor()
        result = restarted.resume()

        self.assertEqual(result["phase"], "HUMAN_GATE")
        self.assertEqual(result["diagnostic"]["classification"], "HUMAN_DECISION_REQUIRED")
        self.assertTrue(result["diagnostic"]["accounting_recorded"])

    def test_supervisor_bug_repair_cannot_modify_product_paths(self):
        run_ids = []

        def diagnose(role, ticket, run_dir):
            return InvocationResult(0, self.diagnostic_report(ticket, "SUPERVISOR_BUG", run_ids), {})

        def unsafe_repair(role, ticket, run_dir):
            (self.root / "apps/search.py").write_text("tampered product\n", encoding="utf-8")
            path = self.root / "tools/dev-supervisor/fix.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# repair\n", encoding="utf-8")
            return InvocationResult(0, {
                "role": "supervisor_repair", "ticket": ticket, "status": "repaired",
                "summary": "unsafe mixed repair", "files_changed": ["tools/dev-supervisor/fix.py"],
                "checks_run": ["supervisor tests"],
            }, {})

        runner = FakeModelRunner([diagnose, unsafe_repair])
        supervisor = self.make_supervisor(runner)
        _, run_ids = self.repeated_recovery_checkpoint(supervisor, count=2)
        before = supervisor._product_snapshot()["fingerprint"]
        self.set_quota(supervisor)
        self.assertEqual(supervisor.run()["quota_resume_phase"], "SUPERVISOR_REPAIR_PENDING")
        self.set_quota(supervisor)

        state = supervisor.resume()

        self.assertEqual(state["phase"], "SUPERVISOR_REPAIR_FAILED")
        self.assertNotEqual(supervisor._product_snapshot()["fingerprint"], before)
        self.assertEqual(git(self.root, "rev-list", "--count", "HEAD"), "1")

    def test_product_fingerprint_mismatch_before_repair_fails_without_consuming_new_quota(self):
        run_ids = []

        def diagnose(role, ticket, run_dir):
            return InvocationResult(0, self.diagnostic_report(ticket, "SUPERVISOR_BUG", run_ids), {})

        runner = FakeModelRunner([diagnose])
        supervisor = self.make_supervisor(runner)
        _, run_ids = self.repeated_recovery_checkpoint(supervisor, count=2)
        self.set_quota(supervisor)
        supervisor.run()
        (self.root / "apps/search.py").write_text("changed between stages\n", encoding="utf-8")
        self.set_quota(supervisor)

        state = supervisor.resume()

        self.assertEqual(state["phase"], "SUPERVISOR_REPAIR_FAILED")
        self.assertEqual(self.quota_authorization(supervisor.quota.snapshot())["status"], "available")
        self.assertEqual(runner.calls, [("diagnostic", "T10")])

    def test_valid_supervisor_repair_commits_only_supervisor_files_and_reclassifies(self):
        run_ids = []

        def diagnose(role, ticket, run_dir):
            return InvocationResult(0, self.diagnostic_report(ticket, "SUPERVISOR_BUG", run_ids), {})

        def repair(role, ticket, run_dir):
            path = self.root / "tools/dev-supervisor/fix.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# bounded supervisor repair\n", encoding="utf-8")
            return InvocationResult(0, {
                "role": "supervisor_repair", "ticket": ticket, "status": "repaired",
                "summary": "bounded repair", "files_changed": ["tools/dev-supervisor/fix.py"],
                "checks_run": ["supervisor tests", "Python compilation", "git diff --check"],
            }, {})

        runner = FakeModelRunner([diagnose, repair])
        supervisor = self.make_supervisor(runner)
        _, run_ids = self.repeated_recovery_checkpoint(supervisor, count=2)
        product_before = supervisor._product_snapshot()
        self.set_quota(supervisor)
        supervisor.run()
        self.set_quota(supervisor)

        state = supervisor.resume()

        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(state["quota_resume_phase"], "DIAGNOSTIC_PENDING")
        self.assertEqual(supervisor._product_snapshot(), product_before)
        commit = state["diagnostic_history"][-1]["supervisor_repair_commit"]
        self.assertEqual(git(self.root, "show", "--format=", "--name-only", commit), "tools/dev-supervisor/fix.py")
        self.assertEqual(len(state["quota_consumptions"]), 2)
        self.assertEqual(
            [item["role"] for item in state["quota_consumptions"]],
            ["diagnostic", "supervisor_repair"],
        )

    def test_external_supervisor_repair_commits_engine_not_controlled_project(self):
        run_ids = []

        def diagnose(role, ticket, run_dir):
            return InvocationResult(0, self.diagnostic_report(ticket, "SUPERVISOR_BUG", run_ids), {})

        with tempfile.TemporaryDirectory() as raw_engine:
            engine = Path(raw_engine)
            git(engine, "init", "-b", "main")
            git(engine, "config", "user.name", "Supervisor Test")
            git(engine, "config", "user.email", "supervisor@example.invalid")
            (engine / "prompts").mkdir()
            (engine / "schemas").mkdir()
            (engine / "supervisor.py").write_text("# engine before\n", encoding="utf-8")
            (engine / "prompts/supervisor-repair.md").write_text(
                (MODULE_PATH.parent / "prompts/supervisor-repair.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (engine / "prompts/diagnose.md").write_text(
                (MODULE_PATH.parent / "prompts/diagnose.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (engine / "schemas/supervisor-repair-report.schema.json").write_text(
                (MODULE_PATH.parent / "schemas/supervisor-repair-report.schema.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (engine / "schemas/diagnostic-report.schema.json").write_text(
                (MODULE_PATH.parent / "schemas/diagnostic-report.schema.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            git(engine, "add", ".")
            git(engine, "commit", "-m", "Seed engine")

            def repair(role, ticket, run_dir):
                (engine / "supervisor.py").write_text("# engine repaired\n", encoding="utf-8")
                return InvocationResult(0, {
                    "role": "supervisor_repair", "ticket": ticket, "status": "repaired",
                    "summary": "bounded external repair", "files_changed": ["supervisor.py"],
                    "checks_run": ["supervisor tests", "Python compilation", "git diff --check"],
                }, {})

            policy = deepcopy(self.policy)
            policy["supervisor_repair_repository"] = "external"
            model_runner = FakeModelRunner([diagnose])
            repair_runner = FakeModelRunner([repair])
            commands = FakeCommandRunner()
            supervisor = Supervisor(
                self.root, policy=policy, assets_dir=engine,
                model_runner=model_runner, supervisor_repair_runner=repair_runner,
                command_runner=commands, now=lambda: NOW,
            )
            _, run_ids = self.repeated_recovery_checkpoint(supervisor, count=2)
            product_before = supervisor._product_snapshot()
            project_head = supervisor.git.head()
            self.set_quota(supervisor)
            waiting = supervisor.run()
            self.assertEqual(waiting["phase"], "QUOTA_CHECK_REQUIRED", waiting.get("message"))
            self.assertEqual(waiting["quota_resume_phase"], "SUPERVISOR_REPAIR_PENDING")
            self.set_quota(supervisor)

            state = supervisor.resume()

            self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED", state.get("message"))
            self.assertEqual(supervisor.git.head(), project_head)
            self.assertEqual(supervisor._product_snapshot(), product_before)
            repair_record = state["diagnostic_history"][-1]
            self.assertEqual(repair_record["repair_repository"], "external")
            repair_commit = repair_record["supervisor_repair_commit"]
            self.assertEqual(git(engine, "show", "--format=", "--name-only", repair_commit), "supervisor.py")
            self.assertEqual(repair_runner.calls, [("supervisor_repair", "T10")])
            self.assertEqual(commands.calls, 2)

    def test_post_repair_unmatched_environment_block_routes_to_ticket_verification(self):
        policy = deepcopy(self.policy)
        policy["milestones"] = [{
            "name": "test gate", "after_ticket": "T10", "before_ticket": "T12", "message": "stop",
        }]
        environment = self.environment_report()
        supervisor = self.make_supervisor(commands=FakeCommandRunner(), policy=policy)
        state, run_ids = self.repeated_recovery_checkpoint(
            supervisor, count=2, environment=environment,
        )
        context = state["recovery_context"]
        context["host_verification_required"] = (
            "Run the ticket's real-process checks during deterministic supervisor verification."
        )
        repair_path = self.root / "tools/dev-supervisor/fix.py"
        repair_path.parent.mkdir(parents=True, exist_ok=True)
        repair_path.write_text("# repaired unmatched environment route\n", encoding="utf-8")
        git(self.root, "add", "tools/dev-supervisor/fix.py")
        git(self.root, "commit", "-m", "Repair supervisor route")
        repair_commit = git(self.root, "rev-parse", "HEAD")
        product = supervisor._product_snapshot()
        workspace = {
            "head": repair_commit, "files": supervisor.git.changed_files(),
            "fingerprint": supervisor.git.fingerprint(), "product": product,
        }
        diagnostic_run = "20260922T130000.000000Z-diagnostic-t10"
        diagnostic_report = self.diagnostic_report("T10", "SUPERVISOR_BUG", run_ids)
        diagnostic_dir = self.root / ".dev-supervisor/runs" / diagnostic_run
        diagnostic_dir.mkdir(parents=True)
        (diagnostic_dir / "final-report.json").write_text(
            json.dumps(diagnostic_report), encoding="utf-8",
        )
        (diagnostic_dir / "diagnostic-evidence.json").write_text(json.dumps({
            "supplied_run_ids": run_ids, "git": {"product_snapshot": product},
        }), encoding="utf-8")
        state.update({
            "phase": "DIAGNOSTIC_REVIEW",
            "diagnostic": {
                "status": "completed", "ticket": "T10", "run_id": diagnostic_run,
                "trigger": "validated_supervisor_repair_requires_reclassification",
                "origin_phase": "SUPERVISOR_REPAIR", "origin_recovery_context": dict(context),
                "repair_commit": repair_commit, "evidence_run_ids": list(run_ids),
                "product_snapshot_before": product, "workspace_before": workspace,
                "workspace_after": workspace, "exit_code": 0,
                "report": diagnostic_report,
            },
        })
        supervisor.save_state(state)

        supervisor._process_diagnostic(state)

        self.assertEqual(state["phase"], "VERIFYING")
        self.assertIsNone(state["recovery_context"])
        handoff = state["active_run"]["diagnostic_completion_handoff"]
        self.assertEqual(handoff["kind"], "post_repair_ticket_completion")
        self.assertNotIn("host_verification_handoff", state["active_run"])

        completed = supervisor.run()

        self.assertEqual(completed["phase"], "HUMAN_GATE")
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "Implement T10 search")

    def test_post_repair_completion_cannot_bypass_configured_host_check(self):
        policy = self.host_handoff_policy(deepcopy(self.policy))
        environment = self.environment_report()
        supervisor = self.make_supervisor(policy=policy)
        state, run_ids = self.repeated_recovery_checkpoint(
            supervisor, count=2, environment=environment,
        )
        repair_path = self.root / "tools/dev-supervisor/fix.py"
        repair_path.parent.mkdir(parents=True, exist_ok=True)
        repair_path.write_text("# unrelated supervisor repair\n", encoding="utf-8")
        git(self.root, "add", "tools/dev-supervisor/fix.py")
        git(self.root, "commit", "-m", "Repair supervisor")
        repair_commit = git(self.root, "rev-parse", "HEAD")
        product = supervisor._product_snapshot()
        diagnostic_run = "20260922T130000.000000Z-diagnostic-t10"
        diagnostic_report = self.diagnostic_report("T10", "SUPERVISOR_BUG", run_ids)
        diagnostic_dir = self.root / ".dev-supervisor/runs" / diagnostic_run
        diagnostic_dir.mkdir(parents=True)
        (diagnostic_dir / "final-report.json").write_text(
            json.dumps(diagnostic_report), encoding="utf-8",
        )
        (diagnostic_dir / "diagnostic-evidence.json").write_text(json.dumps({
            "supplied_run_ids": run_ids, "git": {"product_snapshot": product},
        }), encoding="utf-8")
        diagnostic = {
            "status": "classified", "ticket": "T10", "run_id": diagnostic_run,
            "classification": "SUPERVISOR_BUG",
            "trigger": "validated_supervisor_repair_requires_reclassification",
            "origin_phase": "SUPERVISOR_REPAIR",
            "origin_recovery_context": dict(state["recovery_context"]),
            "repair_commit": repair_commit, "evidence_run_ids": list(run_ids),
            "product_snapshot_before": product,
            "product_fingerprint_after": product["fingerprint"],
            "report": diagnostic_report,
        }

        self.assertIsNone(supervisor._post_repair_completion_handoff(state, diagnostic))

    def test_post_repair_completion_accepts_displaced_active_run_through_validated_lineage(self):
        environment = self.environment_report()
        supervisor = self.make_supervisor()
        state, run_ids = self.repeated_recovery_checkpoint(
            supervisor, count=2, environment=environment,
        )
        active_run_id = state["active_run"]["id"]
        repair_path = self.root / "tools/dev-supervisor/fix.py"
        repair_path.parent.mkdir(parents=True, exist_ok=True)
        repair_path.write_text("# repaired displaced evidence route\n", encoding="utf-8")
        git(self.root, "add", "tools/dev-supervisor/fix.py")
        git(self.root, "commit", "-m", "Repair supervisor route")
        repair_commit = git(self.root, "rev-parse", "HEAD")
        product = supervisor._product_snapshot()

        prior_run = "20260922T120000.000000Z-diagnostic-t10"
        prior_report = self.diagnostic_report("T10", "SUPERVISOR_BUG", run_ids)
        prior_dir = self.root / ".dev-supervisor/runs" / prior_run
        prior_dir.mkdir(parents=True)
        (prior_dir / "final-report.json").write_text(
            json.dumps(prior_report), encoding="utf-8",
        )
        (prior_dir / "diagnostic-evidence.json").write_text(json.dumps({
            "supplied_run_ids": run_ids, "git": {"product_snapshot": product},
        }), encoding="utf-8")

        displaced = [prior_run, "20260922T121000.000000Z-supervisor-repair-t10"]
        diagnostic_run = "20260922T130000.000000Z-diagnostic-t10"
        diagnostic_report = self.diagnostic_report("T10", "SUPERVISOR_BUG", displaced)
        diagnostic_dir = self.root / ".dev-supervisor/runs" / diagnostic_run
        diagnostic_dir.mkdir(parents=True)
        (diagnostic_dir / "final-report.json").write_text(
            json.dumps(diagnostic_report), encoding="utf-8",
        )
        (diagnostic_dir / "diagnostic-evidence.json").write_text(json.dumps({
            "supplied_run_ids": displaced, "git": {"product_snapshot": product},
        }), encoding="utf-8")
        diagnostic = {
            "status": "classified", "ticket": "T10", "run_id": diagnostic_run,
            "classification": "SUPERVISOR_BUG",
            "trigger": "validated_supervisor_repair_requires_reclassification",
            "origin_phase": "SUPERVISOR_REPAIR",
            "origin_recovery_context": dict(state["recovery_context"]),
            "repair_commit": repair_commit, "evidence_run_ids": displaced,
            "product_snapshot_before": product,
            "product_fingerprint_after": product["fingerprint"],
            "report": diagnostic_report,
        }

        self.assertNotIn(active_run_id, displaced)
        handoff = supervisor._post_repair_completion_handoff(state, diagnostic)

        self.assertIsNotNone(handoff)
        self.assertEqual(handoff["kind"], "post_repair_ticket_completion")

        foreign_product = {"entries": []}
        foreign_product["fingerprint"] = supervisor._snapshot_fingerprint(foreign_product)
        (prior_dir / "diagnostic-evidence.json").write_text(json.dumps({
            "supplied_run_ids": run_ids,
            "git": {"product_snapshot": foreign_product},
        }), encoding="utf-8")

        self.assertIsNone(supervisor._post_repair_completion_handoff(state, diagnostic))

    def test_diagnostic_evidence_keeps_active_run_when_newer_runs_fill_bound(self):
        supervisor = self.make_supervisor()
        state, _ = self.repeated_recovery_checkpoint(
            supervisor, count=2, environment=self.environment_report(),
        )
        active_run_id = state["active_run"]["id"]
        for index in range(self.policy["diagnostic"]["max_recent_runs"]):
            later = self.root / ".dev-supervisor/runs" / (
                f"20260923T1{index}0000.000000Z-supervisor-repair-t10"
            )
            later.mkdir(parents=True)

        evidence = supervisor._diagnostic_evidence(state)

        self.assertIn(active_run_id, evidence["supplied_run_ids"])
        self.assertEqual(
            len(evidence["supplied_run_ids"]),
            self.policy["diagnostic"]["max_recent_runs"],
        )

    def test_closed_pilot_gate_cannot_be_bypassed_by_diagnostic_path(self):
        supervisor = self.make_supervisor()
        state = supervisor.load_state()
        state.update({
            "phase": "HUMAN_GATE", "current_ticket": "T10",
            "gate": {"kind": "milestone", "name": "Pilot-A", "head": git(self.root, "rev-parse", "HEAD"), "ticket": "T10"},
            "diagnostic": {"status": "pending", "ticket": "T10"},
        })
        supervisor.save_state(state)

        result = supervisor.resume()

        self.assertEqual(result["phase"], "HUMAN_GATE")
        self.assertEqual(result["gate"]["name"], "Pilot-A")

    def test_consumed_observation_remains_consumed_after_restart(self):
        runner = FakeModelRunner([
            lambda role, ticket, run_dir: InvocationResult(1, None, {}, error="failed"),
        ])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)
        supervisor.run()

        restarted = self.make_supervisor(runner)
        state = restarted.resume()

        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(self.quota_authorization(restarted.quota.snapshot())["status"], "consumed")

    def test_periodic_checkpoint_release_does_not_revive_consumed_observation(self):
        policy = deepcopy(self.policy)
        policy["milestones"] = []
        policy["periodic_checkpoint"]["max_model_invocations"] = 1
        runner = FakeModelRunner([
            self.write_action("apps/search.py", report("implementation", "T10", files=["apps/search.py"])),
        ])
        supervisor = self.make_supervisor(runner, policy=policy)
        self.set_quota(supervisor)
        checkpoint = supervisor.run()
        self.assertEqual(checkpoint["phase"], "PERIODIC_CHECKPOINT")

        supervisor_fix = self.root / "tools/dev-supervisor/quota-fix.txt"
        supervisor_fix.parent.mkdir(parents=True, exist_ok=True)
        supervisor_fix.write_text("fix\n", encoding="utf-8")
        git(self.root, "add", "tools/dev-supervisor/quota-fix.txt")
        git(self.root, "commit", "-m", "Fix supervisor quota")

        released = supervisor.release_gate("reviewed one invocation")
        self.assertEqual(released["phase"], "VERIFYING")
        self.assertEqual(supervisor.quota.evaluate("implementation", policy["quota"])[0], "unknown")
        state = supervisor.resume()

        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(len(runner.calls), 1)

    def test_unconsumed_observation_still_expires_by_ttl(self):
        supervisor = self.make_supervisor()
        self.set_quota(supervisor)
        later = Supervisor(
            self.root,
            policy=deepcopy(self.policy),
            assets_dir=MODULE_PATH.parent,
            model_runner=FakeModelRunner([]),
            command_runner=FakeCommandRunner(),
            now=lambda: NOW + timedelta(minutes=31),
        )

        state = later.run()

        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertIn("TTL expired", state["message"])

    def test_new_below_reserve_observation_does_not_authorize_retry(self):
        runner = FakeModelRunner([
            lambda role, ticket, run_dir: InvocationResult(1, None, {}, error="failed"),
        ])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)
        supervisor.run()
        self.assertEqual(supervisor.resume()["phase"], "QUOTA_CHECK_REQUIRED")

        self.set_quota(supervisor, five=19, weekly=90)
        state = supervisor.resume()

        self.assertEqual(state["phase"], "QUOTA_LOW")
        self.assertEqual(len(runner.calls), 1)

    def test_missing_or_ambiguous_consumption_state_fails_closed(self):
        supervisor = self.make_supervisor()
        self.set_quota(supervisor)
        ledger_path = self.root / ".dev-supervisor/quota.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["observations"][-1].pop("authorizations")
        supervisor_module.atomic_write_json(ledger_path, ledger)

        state = supervisor.run()

        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertIn("contradictory", state["message"])

    def test_observation_has_no_reset_time_fields(self):
        supervisor = self.make_supervisor()
        self.set_quota(supervisor)
        observation = supervisor.quota.snapshot()
        self.assertNotIn("five_hour_reset_at", observation)
        self.assertNotIn("weekly_reset_at", observation)

    def test_rate_limit_failure_is_not_retried(self):
        def exhausted(role, ticket, run_dir):
            return InvocationResult(1, None, {}, rate_limited=True, error="rate limit")

        runner = FakeModelRunner([exhausted])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(state["phase"], "QUOTA_EXHAUSTED")
        state = supervisor.resume()
        self.assertEqual(state["phase"], "QUOTA_EXHAUSTED")
        self.assertEqual(len(runner.calls), 1)

    def test_failed_verification_prevents_commit(self):
        runner = FakeModelRunner([
            self.write_action("apps/search.py", report("implementation", "T10", files=["apps/search.py"])),
        ])
        supervisor = self.make_supervisor(runner, FakeCommandRunner([1]))
        self.set_quota(supervisor)
        before = git(self.root, "rev-parse", "HEAD")
        state = supervisor.run()
        self.assertEqual(state["phase"], "VERIFICATION_FAILED")
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), before)

    def test_dirty_unexpected_git_state_blocks(self):
        runner = FakeModelRunner([])
        supervisor = self.make_supervisor(runner)
        supervisor.load_state()
        self.set_quota(supervisor)
        (self.root / "unexpected.txt").write_text("user work\n", encoding="utf-8")
        state = supervisor.run()
        self.assertEqual(state["phase"], "GIT_BLOCKED")
        self.assertEqual(runner.calls, [])
        self.assertTrue((self.root / "unexpected.txt").exists())

    def test_resume_reconciles_commit_without_duplicate_invocation_or_commit(self):
        policy = deepcopy(self.policy)
        policy["milestones"] = [{
            "name": "test gate", "after_ticket": "T10", "before_ticket": "T12", "message": "stop",
        }]
        runner = FakeModelRunner([])
        supervisor = self.make_supervisor(runner, policy=policy)
        state = supervisor.load_state()
        starting_head = git(self.root, "rev-parse", "HEAD")
        (self.root / "apps").mkdir()
        (self.root / "apps/search.py").write_text("done\n", encoding="utf-8")
        fingerprint = supervisor.git.fingerprint()
        message = "Implement T10 search"
        git(self.root, "add", "--all")
        git(self.root, "commit", "-m", message)
        committed = git(self.root, "rev-parse", "HEAD")
        state.update({
            "phase": "COMMITTING",
            "active_run": {"id": "prior", "role": "implementation", "ticket": "T10", "report": {}},
            "pending_commit": {
                "message": message, "starting_head": starting_head, "fingerprint": fingerprint,
                "role": "implementation", "ticket": "T10",
            },
        })
        supervisor.save_state(state)

        resumed = supervisor.resume()

        self.assertEqual(resumed["phase"], "HUMAN_GATE")
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), committed)
        self.assertEqual(git(self.root, "rev-list", "--count", "HEAD"), "2")
        self.assertEqual(runner.calls, [])

    def test_final_ticket_completes_one_immutable_epoch_without_inferring_a_ticket(self):
        policy = deepcopy(self.policy)
        policy.update({
            "bootstrap_ticket": "T13", "initial_completed_tickets": ["T10", "T12", "T11"],
            "ticket_verification_commands": {},
        })
        runner = FakeModelRunner([
            self.write_action("apps/final.py", report("implementation", "T13", files=["apps/final.py"])),
        ])
        supervisor = self.make_supervisor(runner, FakeCommandRunner(), policy)
        (self.root / "docs/architecture/implementation-plan.md").write_text(
            "| Milestone | Tickets | Gate |\n|---|---|---|\n| 1 final | 10 → 12 → 11 → 13 | done |\n",
            encoding="utf-8",
        )
        git(self.root, "add", "docs/architecture/implementation-plan.md")
        git(self.root, "commit", "-m", "Bound final-epoch fixture")
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "PLAN_COMPLETED", state["message"])
        self.assertEqual(state["current_ticket"], "T13")
        self.assertEqual(git(self.root, "rev-list", "--count", "HEAD"), "3")
        self.assertEqual(len(state["plan_epochs"]), 1)
        epoch = state["plan_epochs"][0]
        self.assertEqual(epoch["epoch_id"], state["current_plan_epoch_id"])
        self.assertIsNone(epoch["prior_epoch_id"])
        self.assertEqual(epoch["completion"]["ticket"], "T13")
        self.assertEqual(epoch["completion"]["commit"], git(self.root, "rev-parse", "HEAD"))
        status = supervisor.status()
        self.assertEqual(status["current_frontier"]["remaining_tickets"], [])
        self.assertEqual(status["final_result"], epoch["completion"])
        supervisor.stop_path.write_text('{"requested_at":"fixture"}\n', encoding="utf-8")
        self.assertEqual(supervisor.resume()["phase"], "PLAN_COMPLETED")
        self.assertTrue(supervisor.stop_path.exists())
        self.assertEqual(runner.calls, [("implementation", "T13")])

    def test_final_commit_reconciliation_is_idempotent_after_state_write_interruption(self):
        policy = deepcopy(self.policy)
        policy.update({
            "bootstrap_ticket": "T13", "initial_completed_tickets": ["T10", "T12", "T11"],
            "ticket_verification_commands": {},
        })
        runner = FakeModelRunner([])
        supervisor = self.make_supervisor(runner, policy=policy)
        (self.root / "docs/architecture/implementation-plan.md").write_text(
            "| Milestone | Tickets | Gate |\n|---|---|---|\n| 1 final | 10 → 12 → 11 → 13 | done |\n",
            encoding="utf-8",
        )
        git(self.root, "add", "docs/architecture/implementation-plan.md")
        git(self.root, "commit", "-m", "Bound final-epoch fixture")
        state = supervisor.load_state()
        starting_head = git(self.root, "rev-parse", "HEAD")
        (self.root / "apps").mkdir()
        (self.root / "apps/final.py").write_text("done\n", encoding="utf-8")
        fingerprint = supervisor.git.fingerprint()
        message = "Implement T13 person ui"
        git(self.root, "add", "--all")
        git(self.root, "commit", "-m", message)
        committed = git(self.root, "rev-parse", "HEAD")
        state.update({
            "phase": "COMMITTING",
            "active_run": {
                "id": "final-prior", "role": "implementation", "ticket": "T13",
                "report": report("implementation", "T13", files=["apps/final.py"]),
                "verification_results": [],
            },
            "pending_commit": {
                "message": message, "starting_head": starting_head, "fingerprint": fingerprint,
                "role": "implementation", "ticket": "T13", "final_ticket": True,
            },
        })
        supervisor.save_state(state)

        resumed = supervisor.resume()

        self.assertEqual(resumed["phase"], "PLAN_COMPLETED", resumed["message"])
        self.assertEqual(resumed["plan_epochs"][0]["completion"]["commit"], committed)
        self.assertEqual(git(self.root, "rev-list", "--count", "HEAD"), "3")
        self.assertEqual(supervisor.resume()["phase"], "PLAN_COMPLETED")
        self.assertEqual(git(self.root, "rev-list", "--count", "HEAD"), "3")
        self.assertEqual(runner.calls, [])

    def test_legacy_final_state_migration_fails_closed_with_report(self):
        supervisor = self.make_supervisor()
        legacy = supervisor.initial_state()
        plan = supervisor._plan_tickets()
        legacy.update({
            "version": 4, "phase": "READY", "current_ticket": plan[-1],
            "completed_tickets": plan,
        })
        legacy.pop("plan_epochs")
        legacy.pop("current_plan_epoch_id")
        supervisor.runtime.mkdir(parents=True, exist_ok=True)
        supervisor.state_path.write_text(json.dumps(legacy), encoding="utf-8")

        migration = supervisor._legacy_state_migration_report(legacy)

        self.assertEqual(migration["status"], "unsupported")
        self.assertIn("final-commit evidence", migration["reason"])
        with self.assertRaisesRegex(SupervisorError, "migration report"):
            supervisor.load_state()

        pending = deepcopy(legacy)
        pending.update({"phase": "COMMITTING", "completed_tickets": plan[:-1]})
        pending_migration = supervisor._legacy_state_migration_report(pending)
        self.assertEqual(pending_migration["status"], "unsupported")
        self.assertIn("final-ticket commit", pending_migration["reason"])

    def test_explicit_v6_to_v7_state_migration_is_dry_run_safe_idempotent_and_rollbackable(self):
        supervisor = self.make_supervisor()
        source = supervisor.load_state()
        source["version"] = 6
        source.pop("pending_push")
        supervisor.runtime.mkdir(parents=True, exist_ok=True)
        supervisor_module.atomic_write_json(supervisor.state_path, source)
        before = supervisor_module.read_json(supervisor.state_path)

        dry_run = supervisor.state_migration_dry_run()
        self.assertEqual(dry_run, supervisor.state_migration_dry_run())
        self.assertEqual(supervisor_module.read_json(supervisor.state_path), before)
        with patch.object(supervisor_module, "atomic_write_json", side_effect=OSError("injected write fault")):
            with self.assertRaisesRegex(OSError, "injected write fault"):
                supervisor.apply_state_migration()
        self.assertEqual(supervisor_module.read_json(supervisor.state_path), before)

        self.assertEqual(supervisor.apply_state_migration(), dry_run)
        migrated = supervisor.load_state(read_only=True)
        self.assertEqual(migrated["version"], 7)
        self.assertIsNone(migrated["pending_push"])
        self.assertEqual(migrated["state_predecessor"]["checksum"], dry_run["source_checksum"])
        self.assertFalse(supervisor.apply_state_migration()["writes_required"])
        rollback = supervisor.rollback_state_migration()
        self.assertEqual(rollback["target_checksum"], dry_run["source_checksum"])
        self.assertEqual(supervisor_module.read_json(supervisor.state_path), before)

    def test_pilot_a_milestone_stops_before_t13(self):
        self.amend_plan_for_pilot_runtime()
        policy = deepcopy(self.policy)
        policy["bootstrap_ticket"] = "T28"
        policy["initial_completed_tickets"] = ["T10", "T12", "T11"]
        runner = FakeModelRunner([
            self.write_action("apps/runtime.py", report("implementation", "T28", files=["apps/runtime.py"])),
            self.write_action("tools/pilot-a/runner.py", report("implementation", "T29", files=["tools/pilot-a/runner.py"])),
        ])
        host_output = (
            "test_public_flow_uses_one_runtime_dispatcher (test_runtime.RuntimeProcessTests.test_public_flow_uses_one_runtime_dispatcher) ... ok\n"
            "test_sigint_restart_reuses_port_data_and_resets_csrf (test_runtime.RuntimeProcessTests.test_sigint_restart_reuses_port_data_and_resets_csrf) ... ok\n"
            "\n----------------------------------------------------------------------\nRan 9 tests in 0.100s\n\nOK\n"
        )
        t29_host_output = (
            "test_synthetic_subprocess_rehearsal (test_runner.PilotProcessTests.test_synthetic_subprocess_rehearsal) ... ok\n"
            "\n----------------------------------------------------------------------\nRan 13 tests in 0.100s\n\nOK\n"
        )
        commands = FakeCommandRunner(outputs=["generic: ok\n", host_output, "generic: ok\n", t29_host_output])
        supervisor = self.make_supervisor(runner, commands, policy)
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.set_quota(supervisor)
        state = supervisor.resume()
        self.assertEqual(state["phase"], "HUMAN_GATE")
        self.assertEqual(state["current_ticket"], "T13")
        self.assertIn("real-data validation", state["message"])
        self.assertEqual(runner.calls, [("implementation", "T28"), ("implementation", "T29")])

    def test_stale_milestone_gate_cannot_release_past_new_incomplete_tickets(self):
        self.amend_plan_for_pilot_runtime()
        supervisor = self.make_supervisor()
        state = supervisor.load_state()
        state.update({
            "phase": "HUMAN_GATE",
            "current_ticket": "T13",
            "completed_tickets": ["T10", "T12", "T11"],
            "gate": {
                "kind": "milestone", "name": "Pilot-A backend technical pilot",
                "head": git(self.root, "rev-parse", "HEAD"), "ticket": "T13",
            },
        })
        supervisor.save_state(state)

        with self.assertRaisesRegex(SupervisorError, "first incomplete ticket T28"):
            supervisor.release_gate("must not skip amended work")

        unchanged = supervisor.load_state(read_only=True)
        self.assertEqual((unchanged["phase"], unchanged["current_ticket"]), ("HUMAN_GATE", "T13"))
        self.assertEqual(unchanged["completed_tickets"], ["T10", "T12", "T11"])

    def test_reconcile_plan_gate_preserves_history_quota_and_checkpoint_counters(self):
        self.amend_plan_for_pilot_runtime()
        supervisor = self.make_supervisor()
        self.set_quota(supervisor, five=73, weekly=24)
        quota_before = supervisor.quota.snapshot()
        state = supervisor.load_state()
        original_history = [{"at": NOW.isoformat(), "from": "COMMITTING", "to": "HUMAN_GATE", "message": "old gate"}]
        checkpoint = {
            "baseline_at": (NOW - timedelta(minutes=5)).isoformat(),
            "active_runtime_seconds": 7.5,
            "completed_tickets": 1,
            "model_invocations": 0,
        }
        state.update({
            "phase": "HUMAN_GATE",
            "current_ticket": "T13",
            "completed_tickets": ["T10", "T12", "T11"],
            "active_run": None,
            "pending_commit": None,
            "starting_head": None,
            "history": list(original_history),
            "periodic_checkpoint": dict(checkpoint),
            "gate": {
                "kind": "milestone", "name": "Pilot-A backend technical pilot",
                "head": "old-head", "ticket": "T13",
            },
        })
        supervisor.save_state(state)

        reconciled = supervisor.reconcile_plan_gate("approved ADR inserted T28 and T29")

        self.assertEqual((reconciled["phase"], reconciled["current_ticket"]), ("HUMAN_GATE", "T28"))
        self.assertEqual(reconciled["completed_tickets"], ["T10", "T12", "T11"])
        self.assertEqual(reconciled["periodic_checkpoint"], checkpoint)
        self.assertEqual(supervisor.quota.snapshot(), quota_before)
        self.assertEqual(reconciled["history"][:-1], original_history)
        self.assertEqual(reconciled["history"][-1]["from"], "HUMAN_GATE")
        self.assertEqual(reconciled["history"][-1]["to"], "HUMAN_GATE")
        self.assertEqual(len(reconciled["plan_reconciliations"]), 1)
        self.assertEqual(reconciled["plan_reconciliations"][0]["from_current_ticket"], "T13")
        self.assertEqual(reconciled["plan_reconciliations"][0]["to_current_ticket"], "T28")
        self.assertEqual(reconciled["gate"]["after_ticket"], "T29")
        self.assertEqual(reconciled["gate"]["before_ticket"], "T13")
        self.assertIsNone(reconciled["active_run"])

        released = supervisor.release_gate("intentionally authorize T28")
        self.assertEqual((released["phase"], released["current_ticket"]), ("READY", "T28"))
        self.assertEqual(released["periodic_checkpoint"]["completed_tickets"], 0)
        self.assertEqual(released["periodic_checkpoint"]["model_invocations"], 0)

    def test_external_architecture_adoption_requires_explicit_release(self):
        supervisor = self.make_supervisor()
        original = self.periodic_ready_checkpoint(supervisor)
        plan_path = self.root / "docs/architecture/implementation-plan.md"
        plan_path.write_text(
            "| Milestone | Tickets | Gate |\n"
            "|---|---|---|\n"
            "| 2 useful memory | 10 → F04 → 12 → 11 | pilot |\n"
            "| 3 MVP UI | 13, 15–17 | ui |\n",
            encoding="utf-8",
        )
        (self.root / "docs/architecture/tickets/f04-extraction-spike.md").write_text(
            "# F04: extraction spike\n", encoding="utf-8",
        )
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "External architecture plan reconciliation")

        adopted = supervisor.adopt_external_architecture("Reviewed external architecture reconciliation")

        self.assertEqual((adopted["phase"], adopted["current_ticket"]), ("HUMAN_GATE", "F04"))
        self.assertEqual(adopted["gate"]["kind"], "architecture_adoption")
        self.assertEqual(adopted["gate"]["checkpoint_head"], original["gate"]["head"])
        self.assertEqual(adopted["completed_tickets"], ["T10"])
        self.assertEqual(adopted["plan_reconciliations"][-1]["kind"], "external_architecture")

        released = supervisor.release_gate("Reviewed adopted architecture plan")
        self.assertEqual((released["phase"], released["current_ticket"]), ("READY", "F04"))

    def test_external_architecture_adoption_rejects_product_paths(self):
        supervisor = self.make_supervisor()
        self.periodic_ready_checkpoint(supervisor)
        (self.root / "apps").mkdir()
        (self.root / "apps/facebook.py").write_text("blocked\n", encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "Mixed external change")

        with self.assertRaisesRegex(SupervisorError, "permits only paths"):
            supervisor.adopt_external_architecture("must reject product implementation")

        unchanged = supervisor.load_state(read_only=True)
        self.assertEqual((unchanged["phase"], unchanged["current_ticket"]), ("PERIODIC_CHECKPOINT", "T12"))

    def test_external_architecture_adoption_rejects_noninserting_plan(self):
        supervisor = self.make_supervisor()
        self.periodic_ready_checkpoint(supervisor)
        plan_path = self.root / "docs/architecture/implementation-plan.md"
        plan_path.write_text(plan_path.read_text(encoding="utf-8") + "\nPlanning note.\n", encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "External architecture note")

        with self.assertRaisesRegex(SupervisorError, "did not insert pending work"):
            supervisor.adopt_external_architecture("must reject non-inserting plan")

    def test_valid_periodic_checkpoint_enters_bounded_plan_reconciliation(self):
        supervisor = self.make_supervisor()
        original = self.periodic_ready_checkpoint(supervisor)

        reconciled = supervisor.reconcile_plan_gate("insert demonstrated prerequisite before current work")

        self.assertEqual((reconciled["phase"], reconciled["current_ticket"]), ("ARCHITECTURE_PENDING", "T12"))
        self.assertIsNone(reconciled["gate"])
        self.assertIsNone(reconciled["active_run"])
        self.assertEqual(reconciled["completed_tickets"], ["T10"])
        self.assertEqual(reconciled["recovery_context"]["kind"], "periodic_plan_reconciliation")
        self.assertEqual(reconciled["recovery_context"]["deferred_ticket"], "T12")
        self.assertEqual(reconciled["recovery_context"]["checkpoint_head"], original["gate"]["head"])
        self.assertEqual(reconciled["periodic_checkpoint"]["completed_tickets"], 0)
        self.assertEqual(reconciled["periodic_checkpoint"]["model_invocations"], 0)
        self.assertEqual(len(reconciled["plan_reconciliation_requests"]), 1)

    def test_periodic_plan_reconciliation_commits_and_adopts_inserted_next_ticket(self):
        plan_path = "docs/architecture/implementation-plan.md"
        ticket_path = "docs/architecture/tickets/f04-inserted-repair.md"

        def amend_plan(role, ticket, run_dir):
            self.assertEqual((role, ticket), ("architecture", "T12"))
            (self.root / plan_path).write_text(
                "| Milestone | Tickets | Gate |\n"
                "|---|---|---|\n"
                "| 2 useful memory | 10 → F04 → 12 → 11 | pilot |\n"
                "| 3 MVP UI | 13, 15–17 | ui |\n",
                encoding="utf-8",
            )
            (self.root / ticket_path).write_text(
                "# F04: inserted repair\n\n- Prerequisites: completed T10.\n",
                encoding="utf-8",
            )
            return InvocationResult(
                0,
                report("architecture", "T12", files=[plan_path, ticket_path]),
                {},
            )

        runner = FakeModelRunner([amend_plan])
        supervisor = self.make_supervisor(runner)
        self.periodic_ready_checkpoint(supervisor)
        supervisor.reconcile_plan_gate("insert one demonstrated repair")
        self.set_quota(supervisor)

        reconciled = supervisor.resume()

        self.assertEqual(reconciled["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(reconciled["current_ticket"], "F04")
        self.assertEqual(reconciled["completed_tickets"], ["T10"])
        self.assertEqual(runner.calls, [("architecture", "T12")])
        self.assertEqual(reconciled["plan_reconciliations"][-1]["kind"], "periodic")
        self.assertEqual(reconciled["plan_reconciliations"][-1]["from_current_ticket"], "T12")
        self.assertEqual(reconciled["plan_reconciliations"][-1]["to_current_ticket"], "F04")
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "Resolve T12 architecture blocker")

    def test_periodic_plan_reconciliation_rejects_stale_or_nonquiescent_checkpoint(self):
        supervisor = self.make_supervisor()
        state = self.periodic_ready_checkpoint(supervisor)
        state["gate"]["head"] = "0" * 40
        supervisor.save_state(state)
        with self.assertRaisesRegex(SupervisorError, "stale or its product tree changed"):
            supervisor.reconcile_plan_gate("must reject stale checkpoint")

        supervisor = self.make_supervisor()
        state = self.periodic_ready_checkpoint(supervisor)
        state["active_run"] = {"id": "still-active"}
        supervisor.save_state(state)
        with self.assertRaisesRegex(SupervisorError, "no active or pending run"):
            supervisor.reconcile_plan_gate("must reject nonquiescent checkpoint")

    def test_periodic_plan_reconciliation_rejects_noninserting_architecture_change(self):
        plan_path = "docs/architecture/implementation-plan.md"

        def amend_without_insertion(role, ticket, run_dir):
            path = self.root / plan_path
            path.write_text(path.read_text(encoding="utf-8") + "\nPlanning note only.\n", encoding="utf-8")
            return InvocationResult(0, report("architecture", "T12", files=[plan_path]), {})

        runner = FakeModelRunner([amend_without_insertion])
        supervisor = self.make_supervisor(runner)
        self.periodic_ready_checkpoint(supervisor)
        supervisor.reconcile_plan_gate("request must insert pending work")
        self.set_quota(supervisor)

        reconciled = supervisor.resume()

        self.assertEqual(reconciled["phase"], "SCOPE_BLOCKED")
        self.assertIn("did not insert pending work", reconciled["message"])
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "Seed")

    def test_ordinary_periodic_release_with_unchanged_plan_remains_ready(self):
        runner = FakeModelRunner([
            self.write_action(
                "apps/commitments.py",
                report("implementation", "T12", files=["apps/commitments.py"]),
            ),
        ])
        supervisor = self.make_supervisor(runner)
        self.periodic_ready_checkpoint(supervisor)

        self.assertIsNone(supervisor.advertised_resume_command(supervisor.load_state(read_only=True)))
        waiting = supervisor.resume()
        self.assertEqual((waiting["phase"], waiting["current_ticket"]), ("PERIODIC_CHECKPOINT", "T12"))
        self.assertEqual(runner.calls, [])

        released = supervisor.release_gate("reviewed ordinary periodic checkpoint")

        self.assertEqual((released["phase"], released["current_ticket"]), ("READY", "T12"))
        self.assertIsNone(released["gate"])
        self.assertEqual(released["completed_tickets"], ["T10"])
        self.assertNotIn("plan_reconciliation_requests", released)
        self.set_quota(supervisor)

        resumed = supervisor.resume()

        self.assertEqual(runner.calls, [("implementation", "T12")])
        self.assertEqual(resumed["current_ticket"], "T11")

    def test_post_implementation_periodic_resume_runs_verification_scope_and_commit_without_terra(self):
        commands = FakeCommandRunner()
        supervisor, runner, checkpoint = self.post_implementation_periodic_checkpoint(commands=commands)
        consumptions = deepcopy(checkpoint["quota_consumptions"])
        self.assertEqual(supervisor.advertised_resume_command(checkpoint), "./dev resume")

        resumed = supervisor.resume()

        self.assertNotEqual(resumed["phase"], "PERIODIC_CHECKPOINT")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertEqual(commands.calls, 1)
        self.assertEqual(resumed["quota_consumptions"], consumptions)
        transitions = [(item["from"], item["to"]) for item in resumed["history"]]
        self.assertIn(("PERIODIC_CHECKPOINT", "VERIFYING"), transitions)
        self.assertIn(("VERIFYING", "SCOPE_PENDING"), transitions)
        self.assertIn(("SCOPE_PENDING", "COMMITTING"), transitions)
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "Implement T10 search")
        self.assertTrue((self.root / "apps/search.py").is_file())
        self.assertEqual(supervisor.git.changed_files(), [])

    def test_post_implementation_periodic_resume_cannot_bypass_failed_verification(self):
        commands = FakeCommandRunner(statuses=[1], outputs=["verification failed\n"])
        supervisor, runner, checkpoint = self.post_implementation_periodic_checkpoint(commands=commands)
        starting_head = git(self.root, "rev-parse", "HEAD")

        resumed = supervisor.resume()

        self.assertEqual(resumed["phase"], "VERIFICATION_FAILED")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertEqual(commands.calls, 1)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), starting_head)
        self.assertEqual(supervisor.git.changed_files(), ["apps/search.py"])
        self.assertEqual(resumed["active_run"]["report"], checkpoint["active_run"]["report"])

    def test_stale_post_implementation_periodic_checkpoint_has_no_fake_resume(self):
        commands = FakeCommandRunner()
        supervisor, runner, checkpoint = self.post_implementation_periodic_checkpoint(commands=commands)
        (self.root / "apps/search.py").write_text("tampered after checkpoint\n", encoding="utf-8")

        stale = supervisor.load_state(read_only=True)
        self.assertIsNone(supervisor.advertised_resume_command(stale))
        resumed = supervisor.resume()

        self.assertEqual(resumed["phase"], "PERIODIC_CHECKPOINT")
        self.assertEqual(resumed["active_run"]["id"], checkpoint["active_run"]["id"])
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertEqual(commands.calls, 0)
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "Seed")

    def test_jsonl_usage_parsing(self):
        usage = parse_usage_lines([
            '{"type":"thread.started"}',
            '{"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":3,"output_tokens":4,"reasoning_output_tokens":2}}',
            '{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":1}}',
            'not json',
        ])
        self.assertEqual(usage["input_tokens"], 15)
        self.assertEqual(usage["cached_input_tokens"], 3)
        self.assertEqual(usage["output_tokens"], 5)
        self.assertEqual(usage["reasoning_output_tokens"], 2)
        self.assertEqual(len(usage["turn_completed_events"]), 2)

    def test_malformed_structured_report_fails_closed(self):
        def malformed(role, ticket, run_dir):
            return InvocationResult(0, {"role": role}, {})

        runner = FakeModelRunner([malformed])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(state["phase"], "REPORT_INVALID")
        self.assertEqual(git(self.root, "rev-list", "--count", "HEAD"), "1")

    def test_checked_in_output_schema_uses_supported_codex_subset(self):
        def keywords(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield key
                    yield from keywords(child)
            elif isinstance(value, list):
                for child in value:
                    yield from keywords(child)

        for name in (
            "agent-report.schema.json", "diagnostic-report.schema.json",
            "supervisor-repair-report.schema.json",
        ):
            with self.subTest(schema=name):
                schema = json.loads(
                    (MODULE_PATH.parent / "schemas" / name).read_text(encoding="utf-8")
                )
                self.assertEqual(validate_codex_output_schema(schema), [])
                used = set(keywords(schema))
                self.assertNotIn("uniqueItems", used)
                self.assertNotIn("minLength", used)

    def test_schema_compatibility_check_rejects_known_unsupported_keywords(self):
        base = {
            "type": "object", "properties": {}, "required": [],
            "additionalProperties": False,
        }
        for keyword in supervisor_module.CODEX_UNSUPPORTED_SCHEMA_KEYWORDS:
            with self.subTest(keyword=keyword):
                candidate = deepcopy(base)
                candidate[keyword] = True
                errors = validate_codex_output_schema(candidate)
                self.assertTrue(any(keyword in error for error in errors), errors)

    def test_invalid_codex_schema_fails_before_model_runner_is_called(self):
        assets = self.root / ".dev-supervisor/test-assets"
        (assets / "schemas").mkdir(parents=True)
        incompatible = {
            "type": "object",
            "properties": {
                "files_changed": {
                    "type": "array", "items": {"type": "string"}, "uniqueItems": True,
                },
            },
            "required": ["files_changed"],
            "additionalProperties": False,
        }
        (assets / "schemas/agent-report.schema.json").write_text(
            json.dumps(incompatible), encoding="utf-8",
        )
        runner = FakeModelRunner([])
        supervisor = Supervisor(
            self.root, policy=deepcopy(self.policy), assets_dir=assets,
            model_runner=runner, command_runner=FakeCommandRunner(), now=lambda: NOW,
        )
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "GIT_BLOCKED")
        self.assertIn("uniqueItems", state["message"])
        self.assertEqual(runner.calls, [])

    def test_report_validation_enforces_invariants_not_in_output_schema(self):
        duplicate_files = report(
            "implementation", "T10", files=["apps/search.py", "apps/search.py"],
        )
        empty_item = report("implementation", "T10")
        empty_item["checks_run"] = [""]

        self.assertIn(
            "files_changed must be unique",
            validate_report(duplicate_files, "implementation", "T10"),
        )
        self.assertIn(
            "checks_run must be an array of nonempty strings",
            validate_report(empty_item, "implementation", "T10"),
        )

    def test_missing_structured_report_fails_closed(self):
        def missing(role, ticket, run_dir):
            return InvocationResult(0, None, {}, error="final report file was not created")

        runner = FakeModelRunner([missing])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(state["phase"], "REPORT_INVALID")
        self.assertEqual(git(self.root, "rev-list", "--count", "HEAD"), "1")

    def test_schema_rejection_without_workspace_changes_is_explicitly_retryable(self):
        policy = deepcopy(self.policy)
        policy["milestones"] = [{
            "name": "test gate", "after_ticket": "T10", "before_ticket": "T12", "message": "stop",
        }]

        def schema_rejected(role, ticket, run_dir):
            return InvocationResult(
                1, None, {}, error="invalid_json_schema: uniqueItems is not permitted",
                duration_seconds=4,
            )

        runner = FakeModelRunner([
            schema_rejected,
            self.write_action("apps/search.py", report("implementation", "T10", files=["apps/search.py"])),
        ])
        supervisor = self.make_supervisor(runner, policy=policy)
        self.set_quota(supervisor)
        failed = supervisor.run()
        self.assertEqual(failed["phase"], "INVOCATION_FAILED")
        self.assertEqual(failed["active_run"]["changed_files"], [])
        self.assertTrue(supervisor.git.is_clean())

        (self.root / "tools/dev-supervisor").mkdir(parents=True)
        (self.root / "tools/dev-supervisor/schema-fix.txt").write_text("fixed\n", encoding="utf-8")
        git(self.root, "add", "tools/dev-supervisor/schema-fix.txt")
        git(self.root, "commit", "-m", "Fix supervisor schema")

        waiting = supervisor.resume()
        self.assertEqual(waiting["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(runner.calls, [("implementation", "T10")])

        self.set_quota(supervisor)
        resumed = supervisor.resume()

        self.assertEqual(resumed["phase"], "HUMAN_GATE")
        self.assertEqual(runner.calls, [("implementation", "T10"), ("implementation", "T10")])
        self.assertNotIn("A prior invocation of this SAME ticket was interrupted", runner.prompts[1])
        self.assertIn("This is not an interrupted-invocation recovery run", runner.prompts[1])

    def test_failed_invocation_with_changes_is_not_retried(self):
        def failed_after_change(role, ticket, run_dir):
            (self.root / "partial.txt").write_text("partial\n", encoding="utf-8")
            return InvocationResult(1, None, {}, error="process failed", duration_seconds=4)

        runner = FakeModelRunner([failed_after_change])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)
        failed = supervisor.run()
        self.assertEqual(failed["phase"], "INVOCATION_FAILED")

        resumed = supervisor.resume()

        self.assertEqual(resumed["phase"], "GIT_BLOCKED")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertEqual((self.root / "partial.txt").read_text(), "partial\n")

    def test_blocked_implementation_resume_enters_existing_recovery_without_reusing_quota(self):
        blocked = report(
            "implementation", "T10", status="blocked", files=["apps/search.py"],
        )
        runner = FakeModelRunner([
            self.write_action("apps/search.py", blocked),
            self.write_action("apps/search.py", blocked),
        ])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)

        failed = supervisor.run()

        self.assertEqual(failed["phase"], "IMPLEMENTATION_FAILED")
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()
        consumptions_before = deepcopy(failed["quota_consumptions"])

        waiting = supervisor.resume()

        self.assertEqual(waiting["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(waiting["quota_resume_phase"], "RECOVER_MODEL")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)
        self.assertEqual(waiting["quota_consumptions"], consumptions_before)
        self.assertTrue(any(
            item.get("from") == "IMPLEMENTATION_FAILED" and item.get("to") == "RECOVER_MODEL"
            for item in waiting["history"]
        ))

        self.set_quota(supervisor)
        recovered = supervisor.resume()

        self.assertEqual(recovered["phase"], "IMPLEMENTATION_FAILED")
        self.assertEqual(runner.calls, [
            ("implementation", "T10"), ("implementation", "T10"),
        ])
        self.assertTrue(recovered["active_run"]["recovery"])
        self.assertIn("returned a blocked or environment-blocked report", runner.prompts[-1])
        self.assertIn("do not broaden scope", runner.prompts[-1])

    def test_evidence_check_runs_without_model_recovery(self):
        blocked = report("implementation", "T10", status="blocked", files=["apps/search.py"])
        runner = FakeModelRunner([self.write_action("apps/search.py", blocked)])
        supervisor = self.make_supervisor(runner)
        supervisor.policy["evidence_check_commands"] = {
            "T10": [{"name": "focused evidence", "command": ["fake-check"]}],
        }
        self.set_quota(supervisor)
        failed = supervisor.run()
        self.assertEqual(failed["phase"], "IMPLEMENTATION_FAILED")

        checked = supervisor.run_evidence_checks("T10")

        self.assertEqual(checked["phase"], "IMPLEMENTATION_FAILED")
        self.assertTrue(checked["active_run"]["evidence_checks_passed"])
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertIn("owner live PASS/FAIL", checked["message"])

    def test_configured_owner_evidence_uses_human_gate_and_bounded_release(self):
        record_path = "docs/architecture/t10-live-evidence.md"
        changed = ["apps/search.py", record_path]
        blocked = report("implementation", "T10", status="blocked", files=changed)

        def prepare(role, ticket, run_dir):
            (self.root / "apps").mkdir(exist_ok=True)
            (self.root / "apps/search.py").write_text("prepared\n", encoding="utf-8")
            record = self.root / record_path
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text("Status: PENDING\n", encoding="utf-8")
            return InvocationResult(0, blocked, {})

        policy = deepcopy(self.policy)
        policy["evidence_check_commands"] = {
            "T10": [{"name": "focused evidence", "command": ["fake-check"]}],
        }
        policy["human_evidence_gates"] = {
            "T10": {
                "message": "Owner live PASS/FAIL is required.",
                "record_paths": [record_path],
            },
        }
        runner = FakeModelRunner([prepare])
        supervisor = self.make_supervisor(runner, policy=policy)
        self.set_quota(supervisor)

        gated = supervisor.run()

        self.assertEqual(gated["phase"], "HUMAN_GATE")
        self.assertEqual(gated["gate"]["kind"], "evidence")
        self.assertEqual(gated["gate"]["resume_phase"], "RECOVER_MODEL")
        self.assertEqual(gated["active_run"]["report"]["status"], "blocked")
        self.assertIn("./dev evidence check --ticket T10", supervisor.status()["next_actions"])

        checked = supervisor.run_evidence_checks("T10")

        self.assertEqual(checked["phase"], "HUMAN_GATE")
        self.assertTrue(checked["active_run"]["evidence_checks_passed"])
        with self.assertRaisesRegex(SupervisorError, "evidence record is unchanged"):
            supervisor.release_gate("owner run complete")

        (self.root / record_path).write_text(
            "Status: FAIL\nDate: 2026-09-22\nOwner attestation: recorded\n",
            encoding="utf-8",
        )
        released = supervisor.release_gate("Owner recorded bounded FAIL")

        self.assertEqual(released["phase"], "RECOVER_MODEL")
        self.assertIsNone(released["gate"])
        self.assertEqual(released["recovery_context"]["kind"], "human_evidence")
        self.assertEqual(released["recovery_context"]["record_paths"], [record_path])
        self.assertEqual(released["recovery_context"]["release_note"], "Owner recorded bounded FAIL")
        self.assertEqual(runner.calls, [("implementation", "T10")])

    def test_owner_evidence_gate_rejects_non_record_mutation(self):
        record_path = "docs/architecture/t10-live-evidence.md"
        changed = ["apps/search.py", record_path]
        blocked = report("implementation", "T10", status="blocked", files=changed)

        def prepare(role, ticket, run_dir):
            (self.root / "apps").mkdir(exist_ok=True)
            (self.root / "apps/search.py").write_text("prepared\n", encoding="utf-8")
            record = self.root / record_path
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text("Status: PENDING\n", encoding="utf-8")
            return InvocationResult(0, blocked, {})

        policy = deepcopy(self.policy)
        policy["evidence_check_commands"] = {
            "T10": [{"name": "focused evidence", "command": ["fake-check"]}],
        }
        policy["human_evidence_gates"] = {
            "T10": {"message": "Owner run required.", "record_paths": [record_path]},
        }
        supervisor = self.make_supervisor(FakeModelRunner([prepare]), policy=policy)
        self.set_quota(supervisor)
        supervisor.run()
        supervisor.run_evidence_checks("T10")
        (self.root / record_path).write_text("Status: PASS\n", encoding="utf-8")
        (self.root / "apps/search.py").write_text("operator mutation\n", encoding="utf-8")

        with self.assertRaisesRegex(SupervisorError, "outside the configured evidence record"):
            supervisor.release_gate("owner run complete")

    def test_repeated_blocked_implementation_recoveries_trigger_existing_diagnostic(self):
        blocked = report(
            "implementation", "T10", status="blocked", files=["apps/search.py"],
        )
        runner = FakeModelRunner([
            self.write_action("apps/search.py", blocked),
            self.write_action("apps/search.py", blocked),
            self.write_action("apps/search.py", blocked),
        ])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)
        self.assertEqual(supervisor.run()["phase"], "IMPLEMENTATION_FAILED")

        for offset, expected_calls in enumerate((2, 3), 1):
            waiting = supervisor.resume()
            self.assertEqual(waiting["phase"], "QUOTA_CHECK_REQUIRED")
            self.assertEqual(waiting["quota_resume_phase"], "RECOVER_MODEL")
            supervisor.now = lambda offset=offset: NOW + timedelta(seconds=offset)
            self.set_quota(supervisor)
            failed = supervisor.resume()
            self.assertEqual(failed["phase"], "IMPLEMENTATION_FAILED")
            self.assertEqual(len(runner.calls), expected_calls)

        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()
        consumptions_before = deepcopy(failed["quota_consumptions"])
        escalated = supervisor.resume()

        self.assertEqual(escalated["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(escalated["quota_resume_phase"], "DIAGNOSTIC_PENDING")
        self.assertEqual(escalated["diagnostic"]["status"], "pending")
        self.assertEqual(escalated["diagnostic"]["completed_recovery_count"], 2)
        self.assertEqual(len(runner.calls), 3)
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)
        self.assertEqual(escalated["quota_consumptions"], consumptions_before)

    def test_blocked_implementation_recovery_fails_closed_when_checkpoint_changed(self):
        blocked = report(
            "implementation", "T10", status="blocked", files=["apps/search.py"],
        )
        runner = FakeModelRunner([self.write_action("apps/search.py", blocked)])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)
        failed = supervisor.run()
        self.assertEqual(failed["phase"], "IMPLEMENTATION_FAILED")
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()
        (self.root / "apps/search.py").write_text("changed after checkpoint\n", encoding="utf-8")

        refused = supervisor.resume()

        self.assertEqual(refused["phase"], "GIT_BLOCKED")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)

    def test_blocked_implementation_recovery_rejects_contradictory_state(self):
        blocked = report(
            "implementation", "T10", status="blocked", files=["apps/search.py"],
        )
        runner = FakeModelRunner([self.write_action("apps/search.py", blocked)])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)
        failed = supervisor.run()
        self.assertEqual(failed["phase"], "IMPLEMENTATION_FAILED")
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()
        failed["active_run"]["report"]["next_ticket_safe"] = True
        supervisor.save_state(failed)

        refused = supervisor.resume()

        self.assertEqual(refused["phase"], "REPORT_INVALID")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)

    def test_environment_block_recovers_preserved_untracked_work_without_architecture_review(self):
        environment_report = report(
            "implementation", "T10", status="environment_blocked", files=["apps/search.py"],
        )
        environment_report["blockers"] = ["sandbox capability unavailable"]
        runner = FakeModelRunner([
            self.write_action("apps/search.py", environment_report),
            self.write_action("apps/search.py", report("implementation", "T10", files=["apps/search.py"])),
        ])
        policy = deepcopy(self.policy)
        policy["milestones"] = [{
            "name": "test gate", "after_ticket": "T10", "before_ticket": "T12", "message": "stop",
        }]
        supervisor = self.make_supervisor(runner, policy=policy)
        self.set_quota(supervisor)

        state = supervisor.run()
        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.set_quota(supervisor)
        state = supervisor.resume()

        self.assertEqual(state["phase"], "HUMAN_GATE")
        self.assertEqual(runner.calls, [("implementation", "T10"), ("implementation", "T10")])
        self.assertIn("environment-blocked", runner.prompts[1])
        self.assertIn("do not repeat completed work", runner.prompts[1])
        self.assertNotIn(("architecture", "T10"), runner.calls)

    def test_environment_block_with_architecture_flag_still_routes_to_architecture(self):
        blocked = report("implementation", "T10", status="environment_blocked")
        blocked["ambiguity"] = True
        blocked["architecture_deviation"] = True
        runner = FakeModelRunner([
            lambda role, ticket, run_dir: InvocationResult(0, blocked, {}),
            lambda role, ticket, run_dir: InvocationResult(0, report("architecture", "T10", status="fail"), {}),
        ])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)

        state = supervisor.run()
        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.set_quota(supervisor)
        state = supervisor.resume()

        self.assertEqual(state["phase"], "ARCHITECTURE_FAILED")
        self.assertEqual(runner.calls, [("implementation", "T10"), ("architecture", "T10")])

    def test_valid_environment_block_hands_off_to_host_verification_and_commits(self):
        policy = self.host_handoff_policy(deepcopy(self.policy))
        policy["milestones"] = [{
            "name": "test gate", "after_ticket": "T10", "before_ticket": "T12", "message": "stop",
        }]
        runner = FakeModelRunner([
            self.write_action("apps/search.py", self.environment_report()),
        ])
        commands = FakeCommandRunner(
            outputs=["generic verification: ok\n", "real process lifecycle: ok\n"],
        )
        supervisor = self.make_supervisor(runner, commands, policy)
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "HUMAN_GATE")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertEqual(commands.calls, 2)
        self.assertTrue(any("acceptance remains unresolved" in item["message"] for item in state["history"]))
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "Implement T10 search")

    def test_environment_block_without_matching_host_capability_recovers_model(self):
        policy = self.host_handoff_policy(deepcopy(self.policy))
        policy["milestones"] = [{
            "name": "test gate", "after_ticket": "T10", "before_ticket": "T12", "message": "stop",
        }]
        blocked = self.environment_report()
        blocked["blockers"] = ["GPU unavailable"]
        runner = FakeModelRunner([
            self.write_action("apps/search.py", blocked),
            self.write_action("apps/search.py", report("implementation", "T10", files=["apps/search.py"])),
        ])
        commands = FakeCommandRunner(outputs=["generic: ok\n", "real process lifecycle: ok\n"])
        supervisor = self.make_supervisor(runner, commands, policy)
        self.set_quota(supervisor)

        state = supervisor.run()
        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.set_quota(supervisor)
        state = supervisor.resume()

        self.assertEqual(state["phase"], "HUMAN_GATE")
        self.assertEqual(runner.calls, [("implementation", "T10"), ("implementation", "T10")])

    def test_unmatched_environment_recovery_does_not_invent_mandatory_host_check(self):
        policy = self.host_handoff_policy(deepcopy(self.policy))
        blocked = self.environment_report()
        blocked["blockers"] = [
            "AF_INET socket creation fails with PermissionError, blocking an unconfigured real-process check."
        ]
        policy["ticket_verification_commands"].pop("T10")
        runner = FakeModelRunner([
            self.write_action("apps/search.py", blocked),
            self.write_action("apps/search.py", report("implementation", "T10", files=["apps/search.py"])),
        ])
        supervisor = self.make_supervisor(runner, policy=policy)
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        context = state["recovery_context"]
        self.assertIs(context["host_verification_required"], False)
        self.assertIn("No configured mandatory ticket host check", context["host_verification_unavailable"])

        # Existing checkpoints stored a truthy instruction string even when no
        # policy-owned handoff existed. They must also receive corrective guidance.
        context["host_verification_required"] = (
            "Run the ticket's real-process checks during deterministic supervisor verification."
        )
        supervisor.save_state(state)
        self.set_quota(supervisor)
        supervisor.resume()
        prompt = runner.prompts[-1]
        self.assertIn("no mandatory host verification is available", prompt)
        self.assertNotIn("required host verification remains mandatory", prompt)

    def test_product_blocker_cannot_use_host_handoff(self):
        policy = self.host_handoff_policy(deepcopy(self.policy))
        blocked = self.environment_report()
        blocked["product_decision_required"] = True
        runner = FakeModelRunner([self.write_action("apps/search.py", blocked)])
        supervisor = self.make_supervisor(runner, FakeCommandRunner(), policy)
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "HUMAN_GATE")
        self.assertNotIn("host_verification_handoff", state.get("active_run") or {})

    def test_skipped_host_verification_fails_closed(self):
        policy = self.host_handoff_policy(deepcopy(self.policy))
        runner = FakeModelRunner([self.write_action("apps/search.py", self.environment_report())])
        commands = FakeCommandRunner(outputs=["generic: ok\n", "real process lifecycle: skipped\n"])
        supervisor = self.make_supervisor(runner, commands, policy)
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "VERIFICATION_FAILED")
        self.assertIn("Output evidence failed closed", state["message"])
        self.assertEqual(runner.calls, [("implementation", "T10")])

    def test_unavailable_host_verification_evidence_fails_closed(self):
        policy = self.host_handoff_policy(deepcopy(self.policy))
        runner = FakeModelRunner([self.write_action("apps/search.py", self.environment_report())])
        commands = FakeCommandRunner(outputs=["generic: ok\n", ""])
        supervisor = self.make_supervisor(runner, commands, policy)
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "VERIFICATION_FAILED")
        self.assertIn("required output did not match", state["message"])
        self.assertEqual(runner.calls, [("implementation", "T10")])

    def test_failed_host_verification_enters_verification_failed(self):
        policy = self.host_handoff_policy(deepcopy(self.policy))
        runner = FakeModelRunner([self.write_action("apps/search.py", self.environment_report())])
        commands = FakeCommandRunner(
            statuses=[0, 1], outputs=["generic: ok\n", "real process lifecycle: failed\n"],
        )
        supervisor = self.make_supervisor(runner, commands, policy)
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "VERIFICATION_FAILED")
        self.assertEqual(runner.calls, [("implementation", "T10")])

    def test_verification_failure_recovery_allows_unchanged_content_after_supervisor_commit(self):
        supervisor, runner, _, failed = self.failed_host_checkpoint()
        quota_before = (self.root / ".dev-supervisor/quota.json").read_bytes()
        timing_before = (self.root / ".dev-supervisor/timing-history.json").read_bytes()
        checkpoint_before = deepcopy(failed["periodic_checkpoint"])
        history_before = list(failed["history"])

        (self.root / "tools/dev-supervisor").mkdir(parents=True)
        (self.root / "tools/dev-supervisor/fix.txt").write_text("supervisor fix\n", encoding="utf-8")
        git(self.root, "add", "tools/dev-supervisor/fix.txt")
        git(self.root, "commit", "-m", "Supervisor-only fix")

        recovered = supervisor.recover_verification_failure()
        prompt = supervisor._prompt("implementation", recovered)

        self.assertEqual(recovered["phase"], "RECOVER_MODEL")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertIn("test_public_flow_uses_one_runtime_dispatcher", prompt)
        self.assertIn("KeyError: 0", prompt)
        self.assertIn('reminders[\\"data\\"][0]', prompt)
        self.assertEqual(recovered["periodic_checkpoint"], checkpoint_before)
        self.assertEqual(recovered["history"][:len(history_before)], history_before)
        self.assertEqual((self.root / ".dev-supervisor/quota.json").read_bytes(), quota_before)
        self.assertEqual((self.root / ".dev-supervisor/timing-history.json").read_bytes(), timing_before)
        self.assertEqual(recovered["active_run"]["verification_results"], failed["active_run"]["verification_results"])

    def test_verification_failure_recovery_blocks_modified_tracked_content(self):
        supervisor, runner, _, _ = self.failed_host_checkpoint()
        (self.root / "seed.txt").write_text("modified after checkpoint\n", encoding="utf-8")

        state = supervisor.resume()

        self.assertEqual(state["phase"], "GIT_BLOCKED")
        self.assertEqual(runner.calls, [("implementation", "T10")])

    def test_verification_failure_recovery_blocks_modified_untracked_content(self):
        supervisor, runner, _, _ = self.failed_host_checkpoint()
        (self.root / "apps/search.py").write_text("modified untracked content\n", encoding="utf-8")

        state = supervisor.resume()

        self.assertEqual(state["phase"], "GIT_BLOCKED")
        self.assertEqual(runner.calls, [("implementation", "T10")])

    def test_verification_failure_recovery_blocks_added_product_path(self):
        supervisor, runner, _, _ = self.failed_host_checkpoint()
        (self.root / "apps/extra.py").write_text("added after checkpoint\n", encoding="utf-8")

        state = supervisor.resume()

        self.assertEqual(state["phase"], "GIT_BLOCKED")
        self.assertEqual(runner.calls, [("implementation", "T10")])

    def test_verification_failure_recovery_blocks_removed_product_path(self):
        supervisor, runner, _, _ = self.failed_host_checkpoint()
        (self.root / "apps/search.py").unlink()

        state = supervisor.resume()

        self.assertEqual(state["phase"], "GIT_BLOCKED")
        self.assertEqual(runner.calls, [("implementation", "T10")])

    def test_recovered_host_failure_invokes_model_before_any_verification_retry(self):
        supervisor, runner, commands, _ = self.failed_host_checkpoint()
        recovered = supervisor.recover_verification_failure()
        self.assertEqual(recovered["phase"], "RECOVER_MODEL")

        runner.actions.append(
            lambda role, ticket, run_dir: InvocationResult(
                0, report(role, ticket, status="fail", files=["apps/search.py", "seed.txt"]), {},
            )
        )
        state = supervisor.resume()
        self.assertEqual(state["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.set_quota(supervisor)
        state = supervisor.resume()

        self.assertEqual(state["phase"], "IMPLEMENTATION_FAILED")
        self.assertEqual(runner.calls, [("implementation", "T10"), ("implementation", "T10")])
        self.assertEqual(commands.calls, 2)
        self.assertIn("KeyError: 0", runner.prompts[-1])

    def test_recorded_t28_eperm_report_does_not_repeat_model_invocation(self):
        self.amend_plan_for_pilot_runtime()
        policy = deepcopy(self.policy)
        policy.update({
            "bootstrap_ticket": "T28", "initial_completed_tickets": [],
            "milestones": [{
                "name": "test gate", "after_ticket": "T28", "before_ticket": "T29", "message": "stop",
            }],
        })
        recorded = self.environment_report("T28", ["apps/runtime.py"])
        recorded.update({
            "summary": "Preserved T28 implementation provides runtime lifecycle support; required real-process verification remains mandatory on a host.",
            "blockers": [
                "This execution sandbox denies AF_INET socket creation with PermissionError: EPERM, so the required real-process lifecycle checks cannot run here.",
            ],
            "checks_run": [
                "python3 -m unittest discover -s apps/local-agent/runtime/tests -v (7 passed; 2 real-process tests blocked by socket EPERM)",
                "git diff --check",
            ],
        })
        runner = FakeModelRunner([self.write_action("apps/runtime.py", recorded)])
        host_output = (
            "test_public_flow_uses_one_runtime_dispatcher (test_runtime.RuntimeProcessTests.test_public_flow_uses_one_runtime_dispatcher) ... ok\n"
            "test_sigint_restart_reuses_port_data_and_resets_csrf (test_runtime.RuntimeProcessTests.test_sigint_restart_reuses_port_data_and_resets_csrf) ... ok\n"
            "\n----------------------------------------------------------------------\nRan 9 tests in 0.100s\n\nOK\n"
        )
        commands = FakeCommandRunner(outputs=["generic: ok\n", host_output])
        supervisor = self.make_supervisor(runner, commands, policy)
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "HUMAN_GATE")
        self.assertEqual(runner.calls, [("implementation", "T28")])
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "Implement T28 local runtime")

    def test_periodic_recovery_checkpoint_reconciles_to_verification_without_model(self):
        legacy_policy = deepcopy(self.policy)
        legacy_policy["periodic_checkpoint"]["max_model_invocations"] = 1
        blocked = self.environment_report()
        runner = FakeModelRunner([self.write_action("apps/search.py", blocked)])
        legacy = self.make_supervisor(runner, policy=legacy_policy)
        self.set_quota(legacy)

        checkpoint = legacy.run()

        self.assertEqual(checkpoint["phase"], "PERIODIC_CHECKPOINT")
        self.assertEqual(checkpoint["gate"]["resume_phase"], "RECOVER_MODEL")
        counters = deepcopy(checkpoint["periodic_checkpoint"])
        history_length = len(checkpoint["history"])

        (self.root / "tools/dev-supervisor").mkdir(parents=True)
        (self.root / "tools/dev-supervisor/host-handoff-fix.txt").write_text("fix\n", encoding="utf-8")
        git(self.root, "add", "tools/dev-supervisor/host-handoff-fix.txt")
        git(self.root, "commit", "-m", "Fix host handoff")
        supervisor_fix_head = git(self.root, "rev-parse", "HEAD")

        fixed_policy = self.host_handoff_policy(deepcopy(legacy_policy))
        fixed_policy["milestones"] = [{
            "name": "test gate", "after_ticket": "T10", "before_ticket": "T12", "message": "stop",
        }]
        commands = FakeCommandRunner(outputs=["generic: ok\n", "real process lifecycle: ok\n"])
        fixed = self.make_supervisor(runner, commands, fixed_policy)
        reconciled = fixed.recover_environment("loopback-bind-eperm")

        self.assertEqual(reconciled["phase"], "PERIODIC_CHECKPOINT")
        self.assertEqual(reconciled["gate"]["resume_phase"], "VERIFYING")
        self.assertEqual(reconciled["periodic_checkpoint"], counters)
        self.assertGreater(len(reconciled["history"]), history_length)
        released = fixed.release_gate("reviewed deterministic host handoff")
        self.assertEqual(released["phase"], "VERIFYING")

        final = fixed.resume()

        self.assertEqual(final["phase"], "HUMAN_GATE")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertEqual(git(self.root, "rev-parse", "HEAD^"), supervisor_fix_head)

    def test_ticket_specific_verification_commands_run_after_implementation_pass(self):
        policy = deepcopy(self.policy)
        policy["ticket_verification_commands"] = {
            "T10": [{"name": "required host lifecycle check", "command": ["host-check"]}],
        }
        policy["milestones"] = [{
            "name": "test gate", "after_ticket": "T10", "before_ticket": "T12", "message": "stop",
        }]
        commands = FakeCommandRunner()
        supervisor = self.make_supervisor(
            FakeModelRunner([self.write_action("apps/search.py", report("implementation", "T10", files=["apps/search.py"]))]),
            commands, policy,
        )
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "HUMAN_GATE")
        self.assertEqual(commands.calls, 2)

    def test_unittest_evidence_accepts_current_multiline_warning_shape(self):
        errors = supervisor_module.Supervisor._verification_output_errors(
            self.t28_unittest_check(), self.successful_unittest_output(multiline=True),
        )
        self.assertEqual(errors, [])

    def test_unittest_evidence_accepts_same_line_ok(self):
        errors = supervisor_module.Supervisor._verification_output_errors(
            self.t28_unittest_check(), self.successful_unittest_output(),
        )
        self.assertEqual(errors, [])

    def test_unittest_evidence_fails_closed_for_missing_or_bad_required_test(self):
        base = self.successful_unittest_output()
        cases = {
            "absent": base.replace(
                "test_public_flow_uses_one_runtime_dispatcher (test_runtime.RuntimeProcessTests.test_public_flow_uses_one_runtime_dispatcher) ... ok\n",
                "",
            ),
            "fail": base.replace(
                "test_public_flow_uses_one_runtime_dispatcher (test_runtime.RuntimeProcessTests.test_public_flow_uses_one_runtime_dispatcher) ... ok",
                "test_public_flow_uses_one_runtime_dispatcher (test_runtime.RuntimeProcessTests.test_public_flow_uses_one_runtime_dispatcher) ... FAIL",
            ),
            "error": base.replace(
                "test_public_flow_uses_one_runtime_dispatcher (test_runtime.RuntimeProcessTests.test_public_flow_uses_one_runtime_dispatcher) ... ok",
                "test_public_flow_uses_one_runtime_dispatcher (test_runtime.RuntimeProcessTests.test_public_flow_uses_one_runtime_dispatcher) ... ERROR",
            ),
            "skipped": base.replace(
                "test_public_flow_uses_one_runtime_dispatcher (test_runtime.RuntimeProcessTests.test_public_flow_uses_one_runtime_dispatcher) ... ok",
                "test_public_flow_uses_one_runtime_dispatcher (test_runtime.RuntimeProcessTests.test_public_flow_uses_one_runtime_dispatcher) ... skipped 'unavailable'",
            ),
        }
        for name, output in cases.items():
            with self.subTest(name=name):
                errors = supervisor_module.Supervisor._verification_output_errors(
                    self.t28_unittest_check(), output,
                )
                self.assertTrue(errors)

    def test_unittest_evidence_requires_successful_suite_completion(self):
        output = self.successful_unittest_output().replace("\nOK\n", "\nFAILED (failures=1)\n")
        errors = supervisor_module.Supervisor._verification_output_errors(self.t28_unittest_check(), output)
        self.assertIn("unittest suite did not finish with one successful OK status", errors)

    def test_unittest_evidence_nonzero_exit_fails_even_with_successful_output(self):
        policy = self.host_handoff_policy(deepcopy(self.policy))
        policy["ticket_verification_commands"]["T10"][0].pop("required_output_patterns")
        policy["ticket_verification_commands"]["T10"][0]["unittest_evidence"] = {
            "expected_test_count": 2,
            "required_tests": [
                "test_public_flow_uses_one_runtime_dispatcher",
                "test_sigint_restart_reuses_port_data_and_resets_csrf",
            ],
        }
        output = self.successful_unittest_output().replace("Ran 9 tests", "Ran 2 tests")
        runner = FakeModelRunner([
            self.write_action("apps/search.py", report("implementation", "T10", files=["apps/search.py"])),
        ])
        commands = FakeCommandRunner(statuses=[0, 1], outputs=["generic: ok\n", output])
        supervisor = self.make_supervisor(runner, commands, policy)
        self.set_quota(supervisor)

        state = supervisor.run()

        self.assertEqual(state["phase"], "VERIFICATION_FAILED")
        self.assertEqual(state["active_run"]["verification_results"][-1]["exit_status"], 1)

    def test_exit_zero_false_negative_log_can_be_reconciled_without_rerun(self):
        old_policy = self.host_handoff_policy(deepcopy(self.policy))
        old_policy["ticket_verification_commands"]["T10"][0]["required_output_patterns"] = [
            r"(?m)^test_public_flow_uses_one_runtime_dispatcher .* \.\.\. ok$",
            r"(?m)^test_sigint_restart_reuses_port_data_and_resets_csrf .* \.\.\. ok$",
        ]
        output = self.successful_unittest_output(multiline=True).replace("Ran 9 tests", "Ran 2 tests")
        runner = FakeModelRunner([
            self.write_action("apps/search.py", self.environment_report()),
        ])
        commands = FakeCommandRunner(outputs=["generic: ok\n", output])
        old_supervisor = self.make_supervisor(runner, commands, old_policy)
        self.set_quota(old_supervisor)
        failed = old_supervisor.run()
        self.assertEqual(failed["phase"], "VERIFICATION_FAILED")

        fixed_policy = self.host_handoff_policy(deepcopy(self.policy))
        fixed_policy["ticket_verification_commands"]["T10"][0].pop("required_output_patterns")
        fixed_policy["ticket_verification_commands"]["T10"][0]["unittest_evidence"] = {
            "expected_test_count": 2,
            "required_tests": [
                "test_public_flow_uses_one_runtime_dispatcher",
                "test_sigint_restart_reuses_port_data_and_resets_csrf",
            ],
        }
        fixed = self.make_supervisor(runner, commands, fixed_policy)
        reconciled = fixed.reconcile_verification_evidence()

        self.assertEqual(reconciled["phase"], "VERIFYING")
        self.assertTrue(reconciled["active_run"]["verification_results"][-1]["passed"])
        self.assertEqual(commands.calls, 2)
        self.assertEqual(runner.calls, [("implementation", "T10")])

    def test_periodic_gate_after_ticket_threshold(self):
        policy = deepcopy(self.policy)
        policy["milestones"] = []
        policy["periodic_checkpoint"]["max_completed_tickets"] = 1
        runner = FakeModelRunner([
            self.write_action("apps/search.py", report("implementation", "T10", files=["apps/search.py"])),
        ])
        supervisor = self.make_supervisor(runner, policy=policy)
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(state["phase"], "PERIODIC_CHECKPOINT")
        self.assertEqual(state["gate"]["reason"], "PERIODIC_CHECKPOINT")
        self.assertIn("completed tickets", state["message"])
        self.assertEqual(runner.calls, [("implementation", "T10")])

    def test_periodic_gate_after_runtime_threshold(self):
        policy = deepcopy(self.policy)
        policy["periodic_checkpoint"]["max_active_runtime_seconds"] = 1

        def slow_pass(role, ticket, run_dir):
            (self.root / "apps").mkdir(exist_ok=True)
            (self.root / "apps/search.py").write_text("done\n", encoding="utf-8")
            return InvocationResult(
                0, report(role, ticket, files=["apps/search.py"]), {}, duration_seconds=2,
            )

        runner = FakeModelRunner([slow_pass])
        commands = FakeCommandRunner()
        supervisor = self.make_supervisor(runner, commands, policy)
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(state["phase"], "PERIODIC_CHECKPOINT")
        self.assertEqual(state["gate"]["resume_phase"], "VERIFYING")
        self.assertEqual(commands.calls, 0)

    def test_periodic_gate_after_model_invocation_threshold(self):
        policy = deepcopy(self.policy)
        policy["periodic_checkpoint"]["max_model_invocations"] = 1
        runner = FakeModelRunner([
            self.write_action("apps/search.py", report("implementation", "T10", files=["apps/search.py"])),
        ])
        supervisor = self.make_supervisor(runner, policy=policy)
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(state["phase"], "PERIODIC_CHECKPOINT")
        self.assertIn("model invocations", state["message"])

        released = supervisor.release_gate("operator reviewed partial pipeline")
        self.assertEqual(released["phase"], "VERIFYING")
        self.assertEqual(released["periodic_checkpoint"]["model_invocations"], 0)
        self.assertEqual(released["periodic_checkpoint"]["active_runtime_seconds"], 0)

    def test_periodic_threshold_does_not_interrupt_running_invocation(self):
        policy = deepcopy(self.policy)
        policy["periodic_checkpoint"]["max_active_runtime_seconds"] = 1
        events = []

        def action(role, ticket, run_dir):
            events.append("started")
            path = self.root / "apps/search.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("complete\n", encoding="utf-8")
            events.append("completed")
            return InvocationResult(0, report(role, ticket, files=["apps/search.py"]), {}, duration_seconds=2)

        supervisor = self.make_supervisor(FakeModelRunner([action]), policy=policy)
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(events, ["started", "completed"])
        self.assertEqual(state["phase"], "PERIODIC_CHECKPOINT")
        self.assertTrue(state["active_run"]["invocation_completed"])

    def test_watchdog_warning_does_not_terminate(self):
        notices = []
        outcome = run_process_with_watchdog(
            [sys.executable, "-c", "import time; time.sleep(0.12)"],
            cwd=self.root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            warning_seconds=0.03, hard_timeout_seconds=1,
            terminate_grace_seconds=0.05, notify=notices.append,
        )
        self.assertEqual(outcome.exit_code, 0)
        self.assertTrue(outcome.warning_emitted)
        self.assertFalse(outcome.interrupted)
        self.assertTrue(any("WARNING" in item for item in notices))

    def test_watchdog_timeout_produces_resumable_interrupted_state(self):
        def timeout(role, ticket, run_dir):
            path = self.root / "apps/search.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("partial\n", encoding="utf-8")
            return InvocationResult(
                -15, None, {}, duration_seconds=90, interrupted=True,
                interrupt_reason="watchdog_timeout",
            )

        runner = FakeModelRunner([timeout])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(state["phase"], "INTERRUPTED")
        self.assertEqual(state["recovery_context"]["reason"], "watchdog_timeout")
        self.assertTrue((self.root / "apps/search.py").exists())
        self.assertIn("./dev resume", state["message"])

        waiting = supervisor.resume()
        self.assertEqual(waiting["phase"], "QUOTA_CHECK_REQUIRED")
        self.assertEqual(runner.calls, [("implementation", "T10")])

    def test_ctrl_c_during_model_invocation_preserves_partial_tree(self):
        def interrupt(role, ticket, run_dir):
            path = self.root / "apps/search.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("partial model work\n", encoding="utf-8")
            raise KeyboardInterrupt

        supervisor = self.make_supervisor(FakeModelRunner([interrupt]))
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(state["phase"], "INTERRUPTED")
        self.assertEqual((self.root / "apps/search.py").read_text(), "partial model work\n")
        self.assertEqual(state["recovery_context"]["kind"], "model")

    def test_ctrl_c_during_verification_preserves_partial_tree(self):
        policy = deepcopy(self.policy)
        policy["milestones"] = [{
            "name": "test gate", "after_ticket": "T10", "before_ticket": "T12", "message": "stop",
        }]
        runner = FakeModelRunner([
            self.write_action("apps/search.py", report("implementation", "T10", files=["apps/search.py"])),
        ])
        supervisor = self.make_supervisor(runner, InterruptingCommandRunner(), policy)
        self.set_quota(supervisor)
        state = supervisor.run()
        self.assertEqual(state["phase"], "INTERRUPTED")
        self.assertTrue((self.root / "apps/search.py").exists())
        self.assertEqual(git(self.root, "rev-list", "--count", "HEAD"), "1")

    def test_resume_after_incomplete_model_invocation_uses_recovery_prompt(self):
        policy = deepcopy(self.policy)
        policy["milestones"] = [{
            "name": "test gate", "after_ticket": "T10", "before_ticket": "T12", "message": "stop",
        }]
        runner = FakeModelRunner([
            self.write_action("apps/search.py", report("implementation", "T10", files=["apps/search.py"])),
        ])
        supervisor = self.make_supervisor(runner, policy=policy)
        self.set_quota(supervisor)
        state = supervisor.load_state()
        starting_head = git(self.root, "rev-parse", "HEAD")
        original = supervisor.runs_dir / "incomplete"
        original.mkdir(parents=True)
        (self.root / "apps").mkdir()
        (self.root / "apps/search.py").write_text("partial\n", encoding="utf-8")
        state.update({
            "phase": "IMPLEMENTING", "starting_head": starting_head,
            "active_run": {
                "id": "incomplete", "role": "implementation", "ticket": "T10",
                "starting_head": starting_head, "verification_results": [],
            },
        })
        supervisor.save_state(state)
        resumed = supervisor.resume()
        self.assertEqual(resumed["phase"], "HUMAN_GATE")
        self.assertEqual(runner.calls, [("implementation", "T10")])
        self.assertIn("RECOVERY RUN", runner.prompts[0])

    def test_resume_after_completed_invocation_before_state_write(self):
        policy = deepcopy(self.policy)
        policy["milestones"] = [{
            "name": "test gate", "after_ticket": "T10", "before_ticket": "T12", "message": "stop",
        }]
        runner = FakeModelRunner([])
        supervisor = self.make_supervisor(runner, policy=policy)
        self.set_quota(supervisor)
        state = supervisor.load_state()
        starting_head = git(self.root, "rev-parse", "HEAD")
        run_dir = supervisor.runs_dir / "completed"
        run_dir.mkdir(parents=True)
        (self.root / "apps").mkdir()
        (self.root / "apps/search.py").write_text("done\n", encoding="utf-8")
        atomic = supervisor_module.atomic_write_json
        atomic(run_dir / "final-report.json", report("implementation", "T10", files=["apps/search.py"]))
        atomic(run_dir / "usage.json", {})
        (run_dir / "events.jsonl").write_text('{"type":"turn.completed","usage":{}}\n', encoding="utf-8")
        state.update({
            "phase": "IMPLEMENTING", "starting_head": starting_head,
            "active_run": {
                "id": "completed", "role": "implementation", "ticket": "T10",
                "starting_head": starting_head, "verification_results": [],
            },
        })
        supervisor.save_state(state)
        resumed = supervisor.resume()
        self.assertEqual(resumed["phase"], "HUMAN_GATE")
        self.assertEqual(runner.calls, [])
        self.assertEqual(git(self.root, "rev-list", "--count", "HEAD"), "2")

    def test_resume_after_verification_interruption_does_not_repeat_model(self):
        policy = deepcopy(self.policy)
        policy["milestones"] = [{
            "name": "test gate", "after_ticket": "T10", "before_ticket": "T12", "message": "stop",
        }]
        runner = FakeModelRunner([
            self.write_action("apps/search.py", report("implementation", "T10", files=["apps/search.py"])),
        ])
        commands = InterruptingCommandRunner()
        supervisor = self.make_supervisor(runner, commands, policy)
        self.set_quota(supervisor)
        interrupted = supervisor.run()
        self.assertEqual(interrupted["phase"], "INTERRUPTED")
        resumed = supervisor.resume()
        self.assertEqual(resumed["phase"], "HUMAN_GATE")
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(commands.calls, 2)

    def test_partial_working_tree_is_preserved_after_interruption(self):
        runner = FakeModelRunner([
            lambda role, ticket, run_dir: InvocationResult(
                -15, None, {}, interrupted=True, interrupt_reason="network_loss",
            ),
        ])
        supervisor = self.make_supervisor(runner)
        self.set_quota(supervisor)
        (self.root / "partial.txt").write_text("before\n", encoding="utf-8")
        # This is deliberately pre-created after the model start check via the action replacement below.
        (self.root / "partial.txt").unlink()
        def action(role, ticket, run_dir):
            (self.root / "partial.txt").write_text("preserve me\n", encoding="utf-8")
            return InvocationResult(-15, None, {}, interrupted=True, interrupt_reason="network_loss")
        runner.actions = [action]
        state = supervisor.run()
        self.assertEqual(state["phase"], "INTERRUPTED")
        self.assertEqual((self.root / "partial.txt").read_text(), "preserve me\n")

    def test_human_quota_checkpoint_states_survive_restart(self):
        supervisor = self.make_supervisor()
        state = supervisor.load_state()
        for phase in ("HUMAN_GATE", "QUOTA_CHECK_REQUIRED", "QUOTA_LOW", "QUOTA_EXHAUSTED", "PERIODIC_CHECKPOINT", "INTERRUPTED"):
            with self.subTest(phase=phase):
                state["phase"] = phase
                state["message"] = phase
                supervisor.save_state(state)
                restarted = self.make_supervisor().load_state()
                self.assertEqual(restarted["phase"], phase)

    def test_watchdog_timeout_leaves_no_child_process(self):
        outcome = run_process_with_watchdog(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            cwd=self.root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            warning_seconds=0.02, hard_timeout_seconds=0.06, terminate_grace_seconds=0.05,
        )
        self.assertTrue(outcome.interrupted)
        with self.assertRaises(ProcessLookupError):
            os.kill(outcome.child_pid, 0)

    def test_dashboard_with_known_quota(self):
        supervisor = self.make_supervisor()
        self.set_quota(supervisor)
        dashboard = supervisor.dashboard()
        self.assertIn("QUOTA", dashboard)
        self.assertIn("5-hour: 90%", dashboard)
        self.assertIn("Next model permitted now: yes", dashboard)

    def test_dashboard_with_unknown_quota(self):
        dashboard = self.make_supervisor().dashboard()
        self.assertIn("Status: UNKNOWN", dashboard)
        self.assertIn("5-hour: unknown", dashboard)
        self.assertIn("Next model permitted now: no", dashboard)

    def test_quota_waiting_dashboard_uses_pending_diagnostic_role(self):
        supervisor = self.make_supervisor()
        state = supervisor.load_state()
        state.update({
            "phase": "QUOTA_CHECK_REQUIRED", "pending_role": "diagnostic",
            "quota_resume_phase": "DIAGNOSTIC_PENDING",
            "active_run": {"role": "implementation", "ticket": "T10"},
        })
        supervisor.save_state(state)

        dashboard = supervisor.dashboard()

        self.assertIn("Role: diagnostic · gpt-5.6-sol · reasoning high", dashboard)
        self.assertIn("Applicable ranges:", dashboard)

    def test_dashboard_has_pipeline_current_and_next_sections(self):
        dashboard = self.make_supervisor().dashboard()
        for heading in ("PROJECT", "PIPELINE", "CURRENT RUN", "PERIODIC CHECKPOINT", "NEXT"):
            self.assertIn(heading, dashboard)
        self.assertIn("Current: T10", dashboard)
        self.assertIn("Upcoming: T12, T11, T13", dashboard)

    def test_completed_failed_run_dashboard_uses_persisted_duration(self):
        supervisor = self.make_supervisor()
        state = supervisor.load_state()
        state.update({
            "phase": "INVOCATION_FAILED",
            "active_run": {
                "id": "failed", "role": "implementation", "ticket": "T10",
                "started_at": (NOW - timedelta(hours=7, minutes=7)).isoformat(),
                "finished_at": (NOW - timedelta(hours=7, minutes=6, seconds=56)).isoformat(),
                "duration_seconds": 4.2, "invocation_completed": True,
            },
        })
        supervisor.save_state(state)

        status = supervisor.status()
        dashboard = supervisor.dashboard()

        self.assertEqual(status["current_run_elapsed_seconds"], 4.2)
        self.assertIn("Elapsed: 4s", dashboard)
        self.assertNotIn("Elapsed: 7h07m", dashboard)

    def test_active_run_dashboard_uses_live_elapsed_time(self):
        supervisor = self.make_supervisor()
        state = supervisor.load_state()
        state.update({
            "phase": "IMPLEMENTING",
            "active_run": {
                "id": "active", "role": "implementation", "ticket": "T10",
                "started_at": (NOW - timedelta(seconds=65)).isoformat(),
                "invocation_completed": False,
            },
        })
        supervisor.save_state(state)

        status = supervisor.status()

        self.assertEqual(status["current_run_elapsed_seconds"], 65)
        self.assertIn("Elapsed: 1m05s", supervisor.dashboard())

    def test_dashboard_has_no_quota_forecast(self):
        dashboard = self.make_supervisor().dashboard()
        self.assertNotIn("ETA", dashboard)
        self.assertNotIn("forecast", dashboard.lower())

    def test_timing_history_does_not_create_a_quota_forecast(self):
        supervisor = self.make_supervisor()
        supervisor._record_timing("tickets", {"ticket": "T08", "duration_seconds": 600})
        supervisor._record_timing("tickets", {"ticket": "T09", "duration_seconds": 1200})
        dashboard = supervisor.dashboard()
        self.assertNotIn("ETA", dashboard)
        self.assertNotIn("forecast", dashboard.lower())

    def test_malformed_timing_history_fails_safely(self):
        supervisor = self.make_supervisor()
        supervisor.runtime.mkdir(parents=True, exist_ok=True)
        supervisor.timing_path.write_text("not json", encoding="utf-8")
        dashboard = supervisor.dashboard()
        self.assertIn("PROJECT", dashboard)


class ImmutableEngineUpdateTests(unittest.TestCase):
    def setUp(self):
        SupervisorTests.setUp(self)

    def tearDown(self):
        SupervisorTests.tearDown(self)

    def make_supervisor(self, *args, **kwargs):
        return SupervisorTests.make_supervisor(self, *args, **kwargs)

    def _candidate_engine(self) -> Path:
        candidate = Path(tempfile.mkdtemp(dir=self.temporary.name)) / "candidate"
        shutil.copytree(MODULE_PATH.parent, candidate, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        git(candidate, "init", "-b", "main")
        git(candidate, "config", "user.name", "Engine Test")
        git(candidate, "config", "user.email", "engine@example.invalid")
        git(candidate, "add", ".")
        git(candidate, "commit", "-m", "Candidate engine")
        return candidate

    def test_immutable_binding_requires_host_local_lease_and_stale_host_cannot_write(self):
        candidate = self._candidate_engine()
        supervisor = self.make_supervisor()
        supervisor.runtime.mkdir()
        state = supervisor.initial_state()
        state["phase"] = "HUMAN_GATE"
        supervisor.save_state(state)
        supervisor.engine_binding_path.write_text(json.dumps({"engine_root": str(MODULE_PATH.parent)}), encoding="utf-8")
        report = supervisor.engine_update_dry_run(candidate, run_tests=False)
        os.environ["DEV_SUPERVISOR_HOST_ID"] = "test-host"
        try:
            supervisor.host_owner_path.write_text(json.dumps({
                "version": 1, "host_id": "test-host", "lease_id": "local-lease",
                "engine_build_id": report["identity"]["build_id"],
            }), encoding="utf-8")
            with patch.object(supervisor, "engine_update_dry_run", return_value=report):
                activated = supervisor.activate_engine_update(candidate, go=True)
            self.assertEqual(activated["status"], "activated")
            self.assertTrue((supervisor.runtime / activated["archive"]).exists())
            with self.assertRaisesRegex(SupervisorError, "active engine path"):
                supervisor.save_state(supervisor.load_state(read_only=True))
            current = Supervisor(self.root, policy=deepcopy(self.policy), assets_dir=candidate,
                                 model_runner=FakeModelRunner([]), command_runner=FakeCommandRunner(), now=lambda: NOW)
            archive_path = current.runtime / activated["archive"]
            archive_bytes = archive_path.read_bytes()
            archive_path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(SupervisorError, "invalid JSON"):
                current.rollback_engine_update()
            self.assertEqual(json.loads(current.engine_binding_path.read_text(encoding="utf-8"))["identity"], report["identity"])
            archive_path.write_bytes(archive_bytes)
            rolled_back = current.rollback_engine_update()
            self.assertEqual(rolled_back["status"], "rolled_back")
        finally:
            os.environ.pop("DEV_SUPERVISOR_HOST_ID", None)

    def test_binding_rejects_incompatible_ranges_before_state_write(self):
        candidate = self._candidate_engine()
        supervisor = Supervisor(self.root, policy=deepcopy(self.policy), assets_dir=candidate,
                                model_runner=FakeModelRunner([]), command_runner=FakeCommandRunner(), now=lambda: NOW)
        supervisor.runtime.mkdir()
        state = supervisor.initial_state()
        supervisor.save_state(state)
        identity = supervisor._engine_identity(candidate)
        supervisor.engine_binding_path.write_text(json.dumps({
            "version": 2, "engine_root": str(candidate), "identity": identity,
            "compatibility": {"state": {"minimum": 8, "maximum": 8},
                              "policy": {"minimum": 3, "maximum": 3},
                              "protocol": {"minimum": 1, "maximum": 1}},
        }), encoding="utf-8")
        supervisor.host_owner_path.write_text(json.dumps({
            "version": 1, "host_id": "test-host", "lease_id": "local-lease",
            "engine_build_id": identity["build_id"],
        }), encoding="utf-8")
        os.environ["DEV_SUPERVISOR_HOST_ID"] = "test-host"
        try:
            with self.assertRaisesRegex(SupervisorError, "incompatible"):
                supervisor.save_state(state)
        finally:
            os.environ.pop("DEV_SUPERVISOR_HOST_ID", None)


class LegacyCutoverTests(unittest.TestCase):
    def setUp(self):
        SupervisorTests.setUp(self)

    def tearDown(self):
        SupervisorTests.tearDown(self)

    def _engine(self, name: str) -> Path:
        engine = Path(tempfile.mkdtemp(dir=self.temporary.name)) / name
        shutil.copytree(MODULE_PATH.parent, engine, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        git(engine, "init", "-b", "main")
        git(engine, "config", "user.name", "Cutover Test")
        git(engine, "config", "user.email", "cutover@example.invalid")
        git(engine, "add", ".")
        git(engine, "commit", "-m", name)
        return engine

    def _legacy_runtime(self, legacy: Path) -> Supervisor:
        (self.root / "docs/architecture/implementation-plan.md").write_text(
            "| Milestone | Tickets | Gate |\n|---|---|---|\n| 1 | T30 | human |\n", encoding="utf-8",
        )
        policy = json.loads((MODULE_PATH.parent / "tests/fixtures/t30-compatibility/policy.json").read_text(encoding="utf-8"))
        policy["implementation_plan"] = "docs/architecture/implementation-plan.md"
        (self.root / "dev-supervisor.json").write_text(json.dumps(policy), encoding="utf-8")
        runtime = self.root / ".dev-supervisor"
        runtime.mkdir()
        (runtime / "engine.json").write_text(json.dumps({"engine_root": str(legacy)}), encoding="utf-8")
        quota = json.loads((MODULE_PATH.parent / "tests/fixtures/t30-compatibility/quota.json").read_text(encoding="utf-8"))
        (runtime / "quota.json").write_text(json.dumps(quota), encoding="utf-8")
        (runtime / "runs/r1").mkdir(parents=True)
        (runtime / "runs/r1/invocation.json").write_text('{"legacy": true}\n', encoding="utf-8")
        supervisor = Supervisor(self.root, assets_dir=MODULE_PATH.parent, now=lambda: NOW)
        state = {
            "version": 4, "phase": "HUMAN_GATE", "current_ticket": "T30", "completed_tickets": [],
            "active_run": None, "pending_commit": None,
            "gate": {
                "ticket": "T30", "head": supervisor.git.head(),
                "fingerprint": supervisor.git.fingerprint(), "kind": "milestone",
                "name": "Supervisor 2.0 cutover approval",
            },
            "updated_at": "2026-09-20T12:00:00Z",
        }
        (runtime / "state.json").write_text(json.dumps(state), encoding="utf-8")
        return supervisor

    def test_qualified_cutover_is_opt_in_archives_exact_predecessor_and_rolls_back(self):
        legacy, candidate = self._engine("legacy"), self._engine("candidate")
        supervisor = self._legacy_runtime(legacy)
        before_head, before_snapshot = supervisor.git.head(), supervisor._product_snapshot()
        dry_run = supervisor.legacy_cutover_dry_run(candidate)
        self.assertEqual(dry_run["status"], "supported")
        self.assertEqual(supervisor.git.head(), before_head)
        self.assertEqual(supervisor._product_snapshot(), before_snapshot)
        self.assertEqual(json.loads(supervisor.state_path.read_text(encoding="utf-8"))["version"], 4)
        identity = dry_run["candidate"]["identity"]
        supervisor.host_owner_path.write_text(json.dumps({
            "version": 1, "host_id": "cutover-host", "lease_id": "lease", "engine_build_id": identity["build_id"],
        }), encoding="utf-8")
        os.environ["DEV_SUPERVISOR_HOST_ID"] = "cutover-host"
        try:
            with self.assertRaisesRegex(SupervisorError, "human go"):
                supervisor.apply_legacy_cutover(candidate, source_checksum=dry_run["source_checksum"], go=False)
            result = supervisor.apply_legacy_cutover(candidate, source_checksum=dry_run["source_checksum"], go=True)
            self.assertEqual(result["status"], "cutover_applied")
            archive = json.loads((supervisor.runtime / result["archive"]).read_text(encoding="utf-8"))
            self.assertEqual(archive["state"]["version"], 4)
            self.assertIn("state.json", archive["source_files"])
            self.assertIn("runs/r1/invocation.json", archive["artifacts"])
            self.assertEqual(json.loads(supervisor.state_path.read_text(encoding="utf-8"))["version"], 7)
            converted_quota = json.loads((supervisor.runtime / "quota.json").read_text(encoding="utf-8"))
            self.assertEqual(converted_quota["observations"][0]["authorizations"][0]["status"], "invalidated")
            self.assertEqual(supervisor.git.head(), before_head)
            self.assertEqual(supervisor._product_snapshot(), before_snapshot)
            current = Supervisor(self.root, assets_dir=candidate, now=lambda: NOW)
            rolled_back = current.rollback_legacy_cutover()
            self.assertEqual(rolled_back["status"], "rolled_back")
            self.assertEqual(json.loads(supervisor.state_path.read_text(encoding="utf-8"))["version"], 4)
            self.assertEqual(supervisor.git.head(), before_head)
            self.assertEqual(supervisor._product_snapshot(), before_snapshot)
        finally:
            os.environ.pop("DEV_SUPERVISOR_HOST_ID", None)

    def test_active_and_dirty_unsupported_sources_are_rejected_without_writes(self):
        legacy, candidate = self._engine("legacy"), self._engine("candidate")
        supervisor = self._legacy_runtime(legacy)
        original = supervisor.state_path.read_bytes()
        state = json.loads(original)
        state["active_run"] = {"id": "active"}
        supervisor.state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(SupervisorError, "active model/check/commit"):
            supervisor.legacy_cutover_dry_run(candidate)
        self.assertEqual(supervisor.state_path.read_text(encoding="utf-8"), json.dumps(state))
        state["active_run"] = None
        state["gate"]["fingerprint"] = "0" * 64
        supervisor.state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(SupervisorError, "dirty state is unsupported"):
            supervisor.legacy_cutover_dry_run(candidate)

    def test_exact_clean_legacy_milestone_without_historical_fingerprint_is_supported(self):
        legacy, candidate = self._engine("legacy"), self._engine("candidate")
        supervisor = self._legacy_runtime(legacy)
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "Prepare clean legacy milestone")
        state = json.loads(supervisor.state_path.read_text(encoding="utf-8"))
        message = "Qualification is complete; activate one immutable successor."
        state.update({
            "last_commit": supervisor.git.head(),
            "message": message,
            "gate": {
                "head": supervisor.git.head(), "kind": "milestone",
                "name": "Supervisor 2.0 cutover approval", "ticket": "T30",
            },
            "history": [{
                "at": NOW.isoformat(), "from": "COMMITTING",
                "to": "HUMAN_GATE", "message": message,
            }],
        })
        supervisor.state_path.write_text(json.dumps(state), encoding="utf-8")

        report = supervisor.legacy_cutover_dry_run(candidate)

        self.assertEqual(report["status"], "supported")
        (self.root / "unexpected.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(SupervisorError, "dirty state is unsupported"):
            supervisor.legacy_cutover_dry_run(candidate)

    def test_accepted_cutover_closes_sentinel_and_preserves_archive(self):
        legacy, candidate = self._engine("legacy"), self._engine("candidate")
        supervisor = self._legacy_runtime(legacy)
        report = supervisor.legacy_cutover_dry_run(candidate)
        identity = report["candidate"]["identity"]
        supervisor.host_owner_path.write_text(json.dumps({
            "version": 1, "host_id": "cutover-host", "lease_id": "lease",
            "engine_build_id": identity["build_id"],
        }), encoding="utf-8")
        os.environ["DEV_SUPERVISOR_HOST_ID"] = "cutover-host"
        try:
            supervisor.apply_legacy_cutover(
                candidate, source_checksum=report["source_checksum"], go=True,
            )
            current = Supervisor(self.root, assets_dir=candidate, now=lambda: NOW)
            applied_record = json.loads(current.legacy_cutover_path.read_text(encoding="utf-8"))

            state = current.accept_legacy_cutover("Reviewed qualification and accepted 2.0.")

            self.assertEqual(state["phase"], "PLAN_COMPLETED")
            self.assertEqual(state["completed_tickets"], ["T30"])
            self.assertEqual(state["plan_epochs"][0]["completion"]["ticket"], "T30")
            self.assertTrue((current.runtime / report["archive"]).is_file())
            record = json.loads(current.legacy_cutover_path.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "cutover_accepted")
            current.legacy_cutover_path.write_text(json.dumps(applied_record), encoding="utf-8")
            retried = current.accept_legacy_cutover("Reviewed qualification and accepted 2.0.")
            self.assertEqual(retried["phase"], "PLAN_COMPLETED")
            record = json.loads(current.legacy_cutover_path.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "cutover_accepted")
            with self.assertRaisesRegex(SupervisorError, "rollback is closed"):
                current.rollback_legacy_cutover()
        finally:
            os.environ.pop("DEV_SUPERVISOR_HOST_ID", None)

    def test_cutover_acceptance_rejects_nonfinal_or_inexact_state(self):
        legacy, candidate = self._engine("legacy"), self._engine("candidate")
        supervisor = self._legacy_runtime(legacy)
        with self.assertRaisesRegex(SupervisorError, "final milestone sentinel"):
            supervisor.accept_legacy_cutover("Not converted.")


class ColdStartTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.name", "Cold Start Test")
        git(self.root, "config", "user.email", "cold-start@example.invalid")
        (self.root / "README.md").write_text("# New project\n", encoding="utf-8")
        git(self.root, "add", "README.md")
        git(self.root, "commit", "-m", "Seed")
        self.policy = supervisor_module.default_project_policy("main")
        self.supervisor = Supervisor(self.root, policy=self.policy, now=lambda: NOW)
        self.specification = self.root / "user-specification.md"
        self.specification.write_text("Build a small useful thing.\n", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def proposal(self, kind, source_digest, parent_digest, content, name):
        path = self.root / name
        path.write_text(json.dumps({
            "version": 1, "kind": kind, "source_specification_digest": source_digest,
            "parent_revision_digest": parent_digest, "content": content,
        }), encoding="utf-8")
        return path

    @staticmethod
    def requirements_content(suffix=""):
        return {
            "goals": ["deliver value" + suffix], "constraints": ["preserve source"],
            "unknowns": ["scope"], "conflicts": ["none known"], "non_goals": ["autonomy"],
        }

    @staticmethod
    def architecture_content(suffix=""):
        return {
            "alternatives": ["simpler alternative" + suffix], "selected_design": "minimal" + suffix,
            "complexity_rationale": "only necessary complexity" + suffix,
            "system_boundaries": ["local controller"], "data_integrations": ["none"],
            "risks": ["unknown user need"],
        }

    def test_cold_start_requires_exact_two_version_approval_before_plan(self):
        state = self.supervisor.begin_cold_start(self.specification)
        source = state["source_specification"]["digest"]
        self.assertFalse((self.root / self.policy["implementation_plan"]).exists())
        requirements = self.proposal("requirements", source, source, self.requirements_content(), "requirements.json")
        state = self.supervisor.submit_cold_start_revision(requirements)
        requirements_digest = state["revisions"][-1]["digest"]
        with self.assertRaisesRegex(SupervisorError, "exact current requirements"):
            self.supervisor.approve_cold_start_requirements("0" * 64)
        self.supervisor.approve_cold_start_requirements(requirements_digest)
        architecture = self.proposal(
            "architecture", source, requirements_digest, self.architecture_content(), "architecture.json",
        )
        state = self.supervisor.submit_cold_start_revision(architecture)
        architecture_digest = state["revisions"][-1]["digest"]
        with self.assertRaisesRegex(SupervisorError, "exact current requirements and architecture"):
            self.supervisor.approve_cold_start_architecture(requirements_digest, "0" * 64)
        self.supervisor.approve_cold_start_architecture(requirements_digest, architecture_digest)
        plan_source = self.root / "approved-plan.md"
        plan_source.write_text("# Approved plan\n", encoding="utf-8")
        self.supervisor.materialize_cold_start_plan(plan_source, requirements_digest, architecture_digest)
        self.assertEqual((self.root / self.policy["implementation_plan"]).read_text(encoding="utf-8"), "# Approved plan\n")
        status = self.supervisor.cold_start_status()
        self.assertEqual(status["phase"], "PLAN_READY")
        self.assertIn(requirements_digest, status["approval"].values())
        self.assertIn(architecture_digest, status["approval"].values())

    def test_corrections_preserve_lineage_and_invalidate_stale_architecture_approval(self):
        state = self.supervisor.begin_cold_start(self.specification)
        source = state["source_specification"]["digest"]
        first_requirements = self.supervisor.submit_cold_start_revision(
            self.proposal("requirements", source, source, self.requirements_content(), "requirements-1.json")
        )["revisions"][-1]["digest"]
        self.supervisor.approve_cold_start_requirements(first_requirements)
        first_architecture = self.supervisor.submit_cold_start_revision(
            self.proposal("architecture", source, first_requirements, self.architecture_content(), "architecture-1.json")
        )["revisions"][-1]["digest"]
        self.supervisor.correct_cold_start("requirements")
        revised = self.supervisor.submit_cold_start_revision(
            self.proposal("requirements", source, first_requirements, self.requirements_content(" revised"), "requirements-2.json")
        )
        revised_requirements = revised["revisions"][-1]["digest"]
        self.assertEqual(revised["revisions"][-1]["parent_digest"], first_requirements)
        self.assertIsNone(revised["approval"])
        with self.assertRaisesRegex(SupervisorError, "exact current requirements"):
            self.supervisor.approve_cold_start_requirements(first_requirements)
        self.supervisor.approve_cold_start_requirements(revised_requirements)
        second_architecture = self.supervisor.submit_cold_start_revision(
            self.proposal("architecture", source, revised_requirements, self.architecture_content(" revised"), "architecture-2.json")
        )["revisions"][-1]["digest"]
        with self.assertRaisesRegex(SupervisorError, "exact current requirements and architecture"):
            self.supervisor.approve_cold_start_architecture(first_requirements, first_architecture)
        state = self.supervisor.approve_cold_start_architecture(revised_requirements, second_architecture)
        self.assertEqual(state["phase"], "PLAN_READY")
        self.assertEqual(len(state["revisions"]), 4)

    def test_later_architecture_artifact_edit_invalidates_plan_readiness(self):
        state = self.supervisor.begin_cold_start(self.specification)
        source = state["source_specification"]["digest"]
        requirements = self.supervisor.submit_cold_start_revision(
            self.proposal("requirements", source, source, self.requirements_content(), "requirements.json")
        )["revisions"][-1]["digest"]
        self.supervisor.approve_cold_start_requirements(requirements)
        state = self.supervisor.submit_cold_start_revision(
            self.proposal("architecture", source, requirements, self.architecture_content(), "architecture.json")
        )
        architecture = state["revisions"][-1]["digest"]
        self.supervisor.approve_cold_start_architecture(requirements, architecture)
        artifact = self.supervisor.runtime / "cold-start" / state["revisions"][-1]["artifact"]
        artifact.write_text("{}", encoding="utf-8")
        plan_source = self.root / "approved-plan.md"
        plan_source.write_text("# Approved plan\n", encoding="utf-8")
        with self.assertRaisesRegex(SupervisorError, "artifact was changed"):
            self.supervisor.materialize_cold_start_plan(plan_source, requirements, architecture)
        self.assertFalse((self.root / self.policy["implementation_plan"]).exists())


class BacklogCycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.name", "Backlog Test")
        git(self.root, "config", "user.email", "backlog@example.invalid")
        (self.root / "docs/architecture/tickets").mkdir(parents=True)
        (self.root / "docs/architecture/implementation-plan.md").write_text(
            "| Milestone | Tickets | Gate |\n|---|---|---|\n| 1 done | 01 | done |\n", encoding="utf-8")
        (self.root / "BACKLOG.md").write_text("B-1: bounded follow-up\n", encoding="utf-8")
        (self.root / "seed.txt").write_text("seed\n", encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "Seed")
        policy = json.loads((MODULE_PATH.parent / "tests/fixtures/reference-policy.json").read_text(encoding="utf-8"))
        policy.update({"implementation_plan": "docs/architecture/implementation-plan.md", "authoritative_documents": ["docs/architecture/implementation-plan.md"], "bootstrap_ticket": "T01", "initial_completed_tickets": [], "verification_commands": []})
        self.supervisor = Supervisor(self.root, policy=policy, assets_dir=MODULE_PATH.parent, model_runner=FakeModelRunner([]), command_runner=FakeCommandRunner(), now=lambda: NOW)
        state = self.supervisor.load_state()
        state["phase"] = "PLAN_COMPLETED"
        state["plan_epochs"][0]["completion"] = {"ticket": "T01", "commit": git(self.root, "rev-parse", "HEAD")}
        self.supervisor.save_state(state)

    def tearDown(self):
        self.temporary.cleanup()

    def _write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_backlog_requires_exact_review_and_approval_before_a_new_epoch(self):
        selection = self._write("selection.json", {"version": 1, "items": [{"id": "B-1", "source": "BACKLOG.md", "summary": "bounded follow-up"}]})
        cycle = self.supervisor.begin_backlog_cycle(selection)
        self.assertEqual(cycle["phase"], "BACKLOG_REVIEW")
        source_digest = cycle["selection"]["digest"]
        requirements = self._write("requirements.json", {"version": 1, "kind": "requirements", "selection_digest": source_digest, "parent_revision_digest": source_digest, "content": {"requirements": ["R"], "dependencies": ["none"], "duplicates": ["none"], "readiness": ["ready"], "architecture_impact": ["review required"], "outcomes": [{"item_id": "B-1", "disposition": "accepted", "reason": "bounded"}]}})
        cycle = self.supervisor.submit_backlog_revision(requirements)
        self.assertEqual(cycle["phase"], "APPROVAL_WAIT")
        with self.assertRaisesRegex(SupervisorError, "exact approved"):
            self.supervisor.materialize_backlog_epoch(self.root / "none", self.root / "none", self.root, self.root / "none")
        requirements_digest = cycle["revisions"][-1]["digest"]
        self.supervisor.approve_backlog_requirements(requirements_digest)
        architecture = self._write("architecture.json", {"version": 1, "kind": "architecture", "selection_digest": source_digest, "parent_revision_digest": requirements_digest, "content": {"alternatives": ["simple"], "selected_design": "minimal", "complexity_rationale": "bounded", "architecture_delta": ["none"], "risks": ["review"]}})
        cycle = self.supervisor.submit_backlog_revision(architecture)
        architecture_digest = cycle["revisions"][-1]["digest"]
        self.supervisor.approve_backlog_architecture(requirements_digest, architecture_digest)
        plan = self.root / "next-plan.md"
        index = self.root / "next-index.md"
        tickets = self.root / "next-tickets"
        tickets.mkdir()
        plan.write_text("| Milestone | Tickets | Gate |\n|---|---|---|\n| 2 next | 31 | ready |\n", encoding="utf-8")
        index.write_text("# next index\n", encoding="utf-8")
        (tickets / "31-follow-up.md").write_text("# T31\n", encoding="utf-8")
        lineage = self._write("lineage.json", {"version": 1, "ticket_sources": {"T31": ["B-1"]}})
        ready = self.supervisor.materialize_backlog_epoch(plan, index, tickets, lineage)
        self.assertEqual(ready["phase"], "READY_EPOCH")
        state = self.supervisor.load_state()
        self.assertEqual((state["phase"], state["current_ticket"]), ("READY", "T31"))
        self.assertEqual(len(state["plan_epochs"]), 2)
        self.assertEqual(state["plan_epochs"][0]["completion"]["ticket"], "T01")
        self.assertEqual(self.supervisor.status()["current_frontier"]["remaining_tickets"], ["T31"])

    def test_backlog_source_change_fails_closed_and_cannot_advance_the_completed_epoch(self):
        selection = self._write("selection.json", {"version": 1, "items": [{"id": "B-1", "source": "BACKLOG.md", "summary": "bounded follow-up"}]})
        self.supervisor.begin_backlog_cycle(selection)
        (self.root / "BACKLOG.md").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(SupervisorError, "source changed"):
            self.supervisor.backlog_cycle_status()
        state = self.supervisor.load_state()
        self.assertEqual((state["phase"], len(state["plan_epochs"])), ("PLAN_COMPLETED", 1))


class ExistingProjectAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.name", "Admission Test")
        git(self.root, "config", "user.email", "admission@example.invalid")
        (self.root / "src").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
        self.document = self.root / "docs" / "external-architecture.md"
        self.document.write_text("# Reviewed external architecture\n", encoding="utf-8")
        (self.root / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "Seed existing repository")

    def tearDown(self):
        self.temporary.cleanup()

    def manifest(self):
        digest = supervisor_module._admission_digest(self.document)
        path = self.root / "mapping.json"
        path.write_text(json.dumps({
            "version": 1,
            "source_documents": [{"path": "docs/external-architecture.md", "external_id": "EXT-ARCH-1", "digest": digest}],
            "external_identifiers": ["EXT-ARCH-1"],
            "mapping": {"status": "compatible", "covered_requirements": ["EXT-ARCH-1"], "gaps": [], "contradictions": [], "unknowns": []},
        }), encoding="utf-8")
        return path

    def test_scenario_a_inventory_is_read_only_and_returns_finite_external_checklist(self):
        before = git(self.root, "status", "--porcelain=v1", "--untracked-files=all")
        finding = supervisor_module.assess_existing_project(self.root, "A")
        self.assertEqual(finding["status"], "incompatible")
        self.assertEqual(len(finding["gaps"]), 3)
        self.assertIn("Python", finding["inventory"]["languages"])
        self.assertIn("src/main.py", finding["inventory"]["entry_points"])
        self.assertEqual(git(self.root, "status", "--porcelain=v1", "--untracked-files=all"), before)
        self.assertFalse((self.root / ".dev-supervisor").exists())

    def test_both_scenarios_produce_deterministic_approved_indexes(self):
        manifest = self.manifest()
        for scenario in ("A", "B"):
            review = supervisor_module.AdmissionReview(self.root)
            state = review.begin(scenario, manifest)
            self.assertIsNone(state["approval"])
            review.approve(state["assessment_digest"], state["manifest_digest"])
            destination = f"admission-{scenario}.json"
            review.materialize_index(destination)
            index = json.loads((self.root / destination).read_text(encoding="utf-8"))
            self.assertEqual(index["scenario"], scenario)
            self.assertEqual(index["source_documents"][0]["external_id"], "EXT-ARCH-1")
            self.assertEqual(index["mapping"]["status"], "compatible")
            self.assertEqual(
                supervisor_module.content_checksum(index),
                supervisor_module.content_checksum(json.loads((self.root / destination).read_text(encoding="utf-8"))),
            )
            (self.root / ".dev-supervisor" / "admission.json").unlink()

    def test_changed_source_and_existing_control_both_fail_closed(self):
        manifest = self.manifest()
        review = supervisor_module.AdmissionReview(self.root)
        state = review.begin("B", manifest)
        self.document.write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(SupervisorError, "finite source-document gaps"):
            review.approve(state["assessment_digest"], state["manifest_digest"])
        controlled = Path(tempfile.mkdtemp(dir=self.temporary.name))
        git(controlled, "init", "-b", "main")
        git(controlled, "config", "user.name", "Admission Test")
        git(controlled, "config", "user.email", "admission@example.invalid")
        (controlled / "dev-supervisor.json").write_text("{}\n", encoding="utf-8")
        git(controlled, "add", ".")
        git(controlled, "commit", "-m", "Controlled")
        finding = supervisor_module.assess_existing_project(controlled, "A")
        self.assertIn("already has Supervisor control", finding["gaps"][0])
        self.assertFalse((controlled / ".dev-supervisor").exists())


if __name__ == "__main__":
    unittest.main()
