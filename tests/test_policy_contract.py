from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "supervisor.py"
SPEC = importlib.util.spec_from_file_location("policy_contract_supervisor", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class PolicyContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.policy = module.default_project_policy("main")

    def tearDown(self):
        self.temporary.cleanup()

    def supervisor(self, policy=None):
        return module.Supervisor(self.root, policy=policy or self.policy, assets_dir=MODULE_PATH.parent)

    def write_host_grants(self, capabilities):
        path = self.root / ".dev-supervisor" / "host-capabilities.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"version": 1, "capabilities": capabilities}), encoding="utf-8")

    def test_capabilities_are_independent_and_intersect_host_and_repository(self):
        self.write_host_grants({
            "self_modification": True,
            "user_requested_modification": False,
            "repository_push": True,
        })
        policy = deepcopy(self.policy)
        policy["capabilities"].update({
            "self_modification": True,
            "user_requested_modification": True,
            "repository_push": False,
        })
        supervisor = self.supervisor(policy)
        self.assertTrue(supervisor.capability_allowed("self_modification"))
        self.assertFalse(supervisor.capability_allowed("user_requested_modification"))
        self.assertFalse(supervisor.capability_allowed("repository_push"))
        provenance = supervisor.effective_configuration()["provenance"]["host_capability_grants"]
        self.assertEqual(provenance["status"], "valid")

    def test_missing_or_malformed_host_values_fail_closed(self):
        self.assertFalse(self.supervisor().capability_allowed("self_modification"))
        self.write_host_grants({"self_modification": "yes"})
        supervisor = self.supervisor()
        self.assertFalse(supervisor.capability_allowed("self_modification"))
        self.assertEqual(
            supervisor.effective_configuration()["provenance"]["host_capability_grants"]["status"],
            "invalid",
        )

    def test_repository_policy_cannot_elevate_an_absent_host_grant(self):
        policy = deepcopy(self.policy)
        policy["capabilities"] = dict.fromkeys(module.CAPABILITY_NAMES, True)
        supervisor = self.supervisor(policy)
        self.assertEqual(supervisor.effective_capabilities, dict.fromkeys(module.CAPABILITY_NAMES, False))

    def test_v2_rejects_unknown_keys_and_contradictory_watchdog_ranges(self):
        policy = deepcopy(self.policy)
        policy["unexpected"] = True
        with self.assertRaisesRegex(module.SupervisorError, "unknown or missing"):
            module.validate_project_policy(policy)
        policy = deepcopy(self.policy)
        policy["model_watchdog"]["warning_seconds"] = 5401
        with self.assertRaisesRegex(module.SupervisorError, "cannot exceed"):
            module.validate_project_policy(policy)

    def test_legacy_dry_run_removes_forecast_without_preserving_it(self):
        legacy = deepcopy(self.policy)
        legacy["version"] = 1
        legacy.pop("capabilities")
        legacy["forecast"] = {"fallback_ticket_hours": [1, 4]}
        migrated, report = module.migrate_legacy_policy(legacy)
        self.assertEqual(report["removed_fields"], ["forecast"])
        self.assertNotIn("forecast", migrated)
        self.assertEqual(migrated["capabilities"], dict.fromkeys(module.CAPABILITY_NAMES, False))


if __name__ == "__main__":
    unittest.main()
