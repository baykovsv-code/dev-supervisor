from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "supervisor.py"
SPEC = importlib.util.spec_from_file_location("controlled_improvement_supervisor", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class ControlledImprovementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-b", "main"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.root, check=True)
        (self.root / "README.md").write_text("test\n", encoding="utf-8")
        plan = self.root / "docs" / "architecture" / "implementation-plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("| 1 safety | 01 | gate |\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=self.root, check=True, capture_output=True)
        self.policy = module.default_project_policy("main")

    def tearDown(self):
        self.temporary.cleanup()

    def _grants(self, **enabled):
        path = self.root / ".dev-supervisor" / "host-capabilities.json"
        path.parent.mkdir(exist_ok=True)
        values = dict.fromkeys(module.CAPABILITY_NAMES, False)
        values.update(enabled)
        path.write_text(json.dumps({"version": 1, "capabilities": values}), encoding="utf-8")

    def _supervisor(self, **enabled):
        policy = deepcopy(self.policy)
        policy["capabilities"].update(enabled)
        self._grants(**enabled)
        return module.Supervisor(self.root, policy=policy, assets_dir=MODULE_PATH.parent)

    def _proposal(self, request, parent):
        path = self.root / "impact.json"
        path.write_text(json.dumps({
            "version": 1, "kind": "architecture_impact", "request_digest": request["request_digest"],
            "parent_revision_digest": parent,
            "content": {"alternatives": ["do nothing"], "selected_design": "bounded review",
                        "complexity_rationale": "one ticket", "architecture_delta": ["none"], "risks": ["approval"]},
        }), encoding="utf-8")
        return path

    def test_disabled_capability_allows_status_but_cannot_create_request(self):
        supervisor = module.Supervisor(self.root, policy=self.policy, assets_dir=MODULE_PATH.parent)
        self.assertEqual(supervisor.improvement_status()["phase"], "ABSENT")
        with self.assertRaisesRegex(module.SupervisorError, "disabled"):
            supervisor.request_improvement("user_improvement", "please improve", "small request")
        self.assertFalse((self.root / ".dev-supervisor" / "improvement.json").exists())

    def test_explicit_user_workflow_preserves_correction_lineage_and_bounds(self):
        supervisor = self._supervisor(user_requested_modification=True)
        request = supervisor.request_improvement("user_improvement", "please improve", "small request")
        first = supervisor.submit_improvement_architecture(self._proposal(request, request["request_digest"]))
        second = supervisor.submit_improvement_architecture(self._proposal(first, first["revisions"][-1]["digest"]))
        self.assertEqual(second["revisions"][-1]["parent_digest"], first["revisions"][-1]["digest"])
        approved = supervisor.approve_improvement_architecture(second["revisions"][-1]["digest"])
        plan = self.root / "plan.md"
        plan.write_text("| 1 improvement | 91 | gate |\n", encoding="utf-8")
        tickets = self.root / "tickets"
        tickets.mkdir()
        (tickets / "91-small.md").write_text("# T91\n", encoding="utf-8")
        ready = supervisor.materialize_improvement_plan(plan, tickets)
        self.assertEqual(ready["phase"], "BOUNDED_PLAN_READY")
        self.assertTrue(supervisor.load_state()["improvement_audit"])

    def test_excess_ticket_bound_escalates_without_splitting(self):
        supervisor = self._supervisor(user_requested_modification=True)
        request = supervisor.request_improvement("user_improvement", "please improve", "small request")
        reviewed = supervisor.submit_improvement_architecture(self._proposal(request, request["request_digest"]))
        supervisor.approve_improvement_architecture(reviewed["revisions"][-1]["digest"])
        plan = self.root / "plan.md"
        plan.write_text("| 1 improvement | 91, 92 | gate |\n", encoding="utf-8")
        result = supervisor.materialize_improvement_plan(plan, self.root)
        self.assertEqual(result["phase"], "ESCALATED_NORMAL_CYCLE")

    def test_self_development_stages_successor_but_has_no_activation_path(self):
        supervisor = self._supervisor(self_modification=True)
        request = supervisor.request_improvement("self_development", "build successor", "small controller repair")
        reviewed = supervisor.submit_improvement_architecture(self._proposal(request, request["request_digest"]))
        supervisor.approve_improvement_architecture(reviewed["revisions"][-1]["digest"])
        plan = self.root / "plan.md"
        plan.write_text("| 1 improvement | 91 | gate |\n", encoding="utf-8")
        tickets = self.root / "tickets"
        tickets.mkdir()
        (tickets / "91-successor.md").write_text("# T91\n", encoding="utf-8")
        supervisor.materialize_improvement_plan(plan, tickets)
        staged = supervisor.stage_successor()
        self.assertEqual(staged["phase"], "SUCCESSOR_STAGED")
        self.assertEqual(staged["successor"]["activation"], "forbidden_pending_t10_t11_quiescent_handoff")
        self.assertTrue((self.root / staged["successor"]["path"] / "supervisor.py").is_file())


if __name__ == "__main__":
    unittest.main()
