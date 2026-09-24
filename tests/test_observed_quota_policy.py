"""Deterministic T07 checks for observed quota authorization only."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "supervisor.py"
SPEC = importlib.util.spec_from_file_location("observed_quota_supervisor", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class ObservedQuotaPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "quota.json"
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.policy = module.default_project_policy("main")
        self.provider = module.ManualQuotaProvider(
            self.path, lambda: self.now, models=self.policy["models"], quota_policy=self.policy["quota"],
        )

    def tearDown(self):
        self.temporary.cleanup()

    def consume(self, observation, invocation):
        return self.provider.consume(observation["observation_id"], role="implementation", ticket="T07", invocation_id=invocation, recovery=False, policy=self.policy["quota"])

    def test_boundaries_medium_freshness_and_high_reuse_exhaustion(self):
        self.policy["quota"]["high_reuse_invocation_count"] = 2
        low = self.provider.set(19, 90)
        self.assertEqual(self.provider.evaluate("implementation", self.policy["quota"])[0], "low")
        medium = self.provider.set(20, 15)
        self.assertEqual(self.provider.evaluate("implementation", self.policy["quota"])[0], "ok")
        self.assertEqual(self.consume(medium, "medium-call")["observation_id"], medium["observation_id"])
        self.assertEqual(self.provider.evaluate("implementation", self.policy["quota"])[0], "unknown")
        high = self.provider.set(50, 45)
        self.consume(high, "high-call-1")
        self.consume(high, "high-call-2")
        self.assertEqual(self.provider.evaluate("implementation", self.policy["quota"])[0], "unknown")

    def test_ttl_rate_signal_and_context_change_invalidate(self):
        observation = self.provider.set(90, 90)
        self.now += timedelta(minutes=31)
        self.assertEqual(self.provider.evaluate("implementation", self.policy["quota"])[0], "unknown")
        self.now -= timedelta(minutes=31)
        self.provider.invalidate(observation["observation_id"], "rate_or_usage_signal")
        self.assertEqual(self.provider.evaluate("implementation", self.policy["quota"])[0], "unknown")
        fresh = self.provider.set(90, 90)
        changed = deepcopy(self.policy)
        changed["models"]["implementation"]["model"] = "different-model"
        provider = module.ManualQuotaProvider(self.path, lambda: self.now, models=changed["models"], quota_policy=changed["quota"])
        self.assertEqual(provider.snapshot()["observation_id"], fresh["observation_id"])
        self.assertEqual(provider.evaluate("implementation", changed["quota"])[0], "unknown")

    def test_consumption_is_idempotent_and_legacy_conversion_rolls_back(self):
        observation = self.provider.set(90, 90)
        first = self.consume(observation, "crash-boundary")
        self.assertEqual(first, self.consume(observation, "crash-boundary"))
        self.assertEqual(len(self.provider.snapshot()["authorizations"]), 1)
        legacy = {
            "version": 2, "current_observation_id": "legacy", "observations": [{
                "observation_id": "legacy", "observed_at": "2026-01-01T00:00:00Z",
                "five_hour_percent_left": 90, "five_hour_reset_at": None,
                "weekly_percent_left": 90, "weekly_reset_at": None, "source": "manual",
                "authorization": {"status": "available"},
            }],
        }
        self.path.write_text(json.dumps(legacy), encoding="utf-8")
        legacy_bytes = self.path.read_bytes()
        with self.assertRaisesRegex(module.SupervisorError, "inspection-only"):
            self.provider.set(90, 90)
        self.assertEqual(self.path.read_bytes(), legacy_bytes)
        report = self.provider.migration_dry_run()
        self.assertTrue(report["writes_required"])
        self.provider.apply_migration()
        self.assertEqual(self.provider.snapshot()["observation_id"], "legacy")
        self.provider.rollback_migration()
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["version"], 2)


if __name__ == "__main__":
    unittest.main()
