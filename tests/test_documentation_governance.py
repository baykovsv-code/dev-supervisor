"""Focused deterministic checks for F10 documentation governance."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("documentation_check", ROOT / "scripts/check_documentation.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class DocumentationGovernanceTests(unittest.TestCase):
    def write_pair(self, root: Path, pairs: list[dict]) -> None:
        (root / "docs").mkdir()
        (root / "docs/en.md").write_text("# English\n", encoding="utf-8")
        (root / "docs/ru.md").write_text("# Russian\n", encoding="utf-8")
        (root / "docs/manifest.json").write_text(json.dumps({"normative_language": "en", "pairs": pairs}), encoding="utf-8")

    def pair(self) -> dict:
        return {"english": "docs/en.md", "russian": "docs/ru.md", "english_sha256": hashlib.sha256(b"# English\n").hexdigest()}

    def test_checked_manifest_passes(self):
        self.assertEqual(MODULE.check(ROOT, ROOT / "docs/translation-manifest.json"), [])

    def test_every_currently_pending_ticket_declares_documentation_impact(self):
        # F10's prerequisite makes these the pending authoritative-plan suffix.
        pending = (
            "f10-documentation-governance.md", "f11-protected-snapshot-recovery.md",
            "11-legacy-cutover.md", "12-personal-assistant-qualification.md",
            "99-cutover-sentinel.md",
        )
        tickets = ROOT / "docs/architecture/tickets"
        for name in pending:
            with self.subTest(ticket=name):
                self.assertIn("## Documentation impact", (tickets / name).read_text(encoding="utf-8"))

    def test_stale_source_and_duplicate_pair_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pair = self.pair()
            self.write_pair(root, [pair, pair.copy()])
            errors = MODULE.check(root, root / "docs/manifest.json")
            self.assertTrue(any("duplicates" in error for error in errors))
            (root / "docs/en.md").write_text("changed\n", encoding="utf-8")
            errors = MODULE.check(root, root / "docs/manifest.json")
            self.assertTrue(any("stale" in error for error in errors))

    def test_missing_pair_and_broken_link_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pair = self.pair()
            self.write_pair(root, [pair])
            (root / "docs/ru.md").write_text("[missing](gone.md)\n", encoding="utf-8")
            (root / "docs/en.md").unlink()
            errors = MODULE.check(root, root / "docs/manifest.json")
            self.assertTrue(any("missing declared path" in error for error in errors))
            self.assertTrue(any("broken local link" in error for error in errors))
