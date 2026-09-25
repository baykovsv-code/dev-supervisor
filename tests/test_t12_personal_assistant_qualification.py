"""T12 rehearsal on the redacted T30 source fixture, never on a live project."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR_TESTS = ROOT / "tests" / "test_supervisor.py"
SPEC = importlib.util.spec_from_file_location("t12_supervisor_tests", SUPERVISOR_TESTS)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class T12PersonalAssistantQualificationTests(MODULE.LegacyCutoverTests):
    """Use the same isolated product/engine construction as the T11 cutover tests."""

    def test_first_controlled_ticket_reentry_has_no_duplicate_invocation_or_commit(self):
        """Retain the crash/re-entry rehearsal in the T12 qualification record."""
        case = MODULE.SupervisorTests("test_resume_reconciles_commit_without_duplicate_invocation_or_commit")
        case.setUp()
        try:
            case.test_resume_reconciles_commit_without_duplicate_invocation_or_commit()
        finally:
            case.tearDown()

    def test_t30_rehearsal_covers_dry_run_cutover_read_only_stop_and_rollback(self):
        legacy, candidate = self._engine("t12-legacy"), self._engine("t12-candidate")
        supervisor = self._legacy_runtime(legacy)
        before_head = supervisor.git.head()
        before_snapshot = supervisor._product_snapshot()
        before_state = supervisor.state_path.read_bytes()

        dry_run = supervisor.legacy_cutover_dry_run(candidate)
        self.assertEqual(dry_run["status"], "supported")
        self.assertEqual(supervisor.state_path.read_bytes(), before_state)
        self.assertEqual(supervisor.git.head(), before_head)
        self.assertEqual(supervisor._product_snapshot(), before_snapshot)

        with self.assertRaisesRegex(MODULE.SupervisorError, "source changed"):
            supervisor.apply_legacy_cutover(candidate, source_checksum="0" * 64, go=True)
        self.assertEqual(supervisor.state_path.read_bytes(), before_state)
        self.assertEqual(supervisor._product_snapshot(), before_snapshot)

        os.environ.pop("DEV_SUPERVISOR_HOST_ID", None)
        with self.assertRaisesRegex(MODULE.SupervisorError, "missing file|writer ownership"):
            supervisor.apply_legacy_cutover(
                candidate, source_checksum=dry_run["source_checksum"], go=True,
            )
        self.assertEqual(supervisor.state_path.read_bytes(), before_state)

        identity = dry_run["candidate"]["identity"]
        supervisor.host_owner_path.write_text(json.dumps({
            "version": 1, "host_id": "t12-host", "lease_id": "t12-lease",
            "engine_build_id": identity["build_id"],
        }), encoding="utf-8")
        os.environ["DEV_SUPERVISOR_HOST_ID"] = "t12-host"
        try:
            with self.assertRaisesRegex(MODULE.SupervisorError, "human go"):
                supervisor.apply_legacy_cutover(candidate, source_checksum=dry_run["source_checksum"], go=False)

            applied = supervisor.apply_legacy_cutover(
                candidate, source_checksum=dry_run["source_checksum"], go=True,
            )
            self.assertEqual(applied["status"], "cutover_applied")
            archive = supervisor.runtime / applied["archive"]
            self.assertTrue(archive.is_file())
            archive_bytes = archive.read_bytes()
            self.assertEqual(supervisor.git.head(), before_head)
            self.assertEqual(supervisor._product_snapshot(), before_snapshot)

            current = MODULE.Supervisor(self.root, assets_dir=candidate, now=lambda: MODULE.NOW)
            before_read_only = current.state_path.read_bytes()
            self.assertEqual(current.status()["phase"], "HUMAN_GATE")
            self.assertEqual(current.state_path.read_bytes(), before_read_only)
            self.assertEqual(current.resume()["phase"], "HUMAN_GATE")
            stopped, message = current.request_stop()
            self.assertTrue(stopped, message)
            self.assertIn("quiescent", message)
            self.assertIsNone(current.load_state(read_only=True)["active_run"])
            self.assertEqual(current.git.head(), before_head)
            self.assertEqual(current._product_snapshot(), before_snapshot)

            os.environ.pop("DEV_SUPERVISOR_HOST_ID", None)
            with self.assertRaisesRegex(MODULE.SupervisorError, "missing file|writer ownership"):
                current.rollback_legacy_cutover()
            os.environ["DEV_SUPERVISOR_HOST_ID"] = "t12-host"

            with self.assertRaisesRegex(MODULE.SupervisorError, "already bound|already exists"):
                supervisor.apply_legacy_cutover(
                    candidate, source_checksum=dry_run["source_checksum"], go=True,
                )
            self.assertEqual(archive.read_bytes(), archive_bytes)

            quota = json.loads((current.runtime / "quota.json").read_text(encoding="utf-8"))
            self.assertTrue(all(
                authorization["status"] == "invalidated"
                for observation in quota["observations"]
                for authorization in observation["authorizations"]
            ))
            rolled_back = current.rollback_legacy_cutover()
            self.assertEqual(rolled_back["status"], "rolled_back")
            self.assertEqual(current.git.head(), before_head)
            self.assertEqual(current._product_snapshot(), before_snapshot)
            self.assertEqual(json.loads(current.state_path.read_text(encoding="utf-8"))["version"], 4)
            self.assertEqual(archive.read_bytes(), archive_bytes)
        finally:
            os.environ.pop("DEV_SUPERVISOR_HOST_ID", None)

    def test_runbook_links_every_authoritative_implementation_commit(self):
        runbook = (ROOT / "docs" / "personal-assistant-qualification.md").read_text(encoding="utf-8")
        expected = (
            "dc406b59e4afe7a65bdfe7ab1d36749e122deb99",
            "6e9c96ddbe9ca760960582b67f048f47059f239f",
            "6de5e6e7413156c5f2cb7ff17bb0a28366d4f592",
            "ad7f8c2f3ea50dc1da8fc09c9ca120999fc1cbab",
            "f0a8fb8d3879926529ea4b1a77b9d57b30ac0f2c",
            "bf25c4de8b5ac18bcac998f5ab50a262f2d30d73",
            "66e08ef8df0558965693fc9660defd4a184f04df",
            "42551c44caa64c0b76a91123391edcd43f3c1cff",
            "98efdd93f64d23181bb99a781013f06500fdcb94",
            "644f2d2c74df0e44702160c2bd877ee450608634",
            "e7b838b1eb334b6253c42395eb6650bf4fc7fabe",
            "29bddff9aabf3add7eb275c5b661dae7fbdc626e",
            "a494c6b2ffbf45ec011a8af8f0bf656aa8d69edf",
            "dd69fb89406016bf3bae81ef29c5bf9a0d6cc051",
            "67be443e18003555e7ed3b1064d31bb62a9f00d0",
        )
        for commit in expected:
            with self.subTest(commit=commit):
                self.assertIn(commit, runbook)
        self.assertIn("tests/test_t30_compatibility.py", runbook)
        self.assertIn("tests/test_t12_personal_assistant_qualification.py", runbook)


if __name__ == "__main__":
    unittest.main()
