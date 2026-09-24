"""Rolling, no-model compatibility check for the redacted T30 HUMAN_GATE fixture."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ENGINE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "t30-compatibility"


def fixture_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=root, text=True, capture_output=True, check=True,
    )
    return result.stdout.strip()


def runtime_snapshot(runtime: Path) -> dict[str, bytes]:
    return {
        path.relative_to(runtime).as_posix(): path.read_bytes()
        for path in sorted(runtime.rglob("*")) if path.is_file()
    }


class T30CompatibilityTests(unittest.TestCase):
    def test_legacy_t30_human_gate_is_read_only_without_model_or_network_processes(self):
        """Exercise the unmodified project-facing launcher against isolated copies only."""
        checksums = json.loads((FIXTURE_ROOT / "checksums.json").read_text(encoding="utf-8"))
        self.assertEqual(checksums["algorithm"], "sha256")
        for relative, expected in checksums["files"].items():
            self.assertEqual(fixture_digest(FIXTURE_ROOT / relative), expected, relative)

        with tempfile.TemporaryDirectory() as raw:
            sandbox = Path(raw)
            product = sandbox / "personal-assistant"
            shutil.copytree(FIXTURE_ROOT / "product", product)
            plan_dir = product / "docs" / "architecture"
            plan_dir.mkdir(parents=True)
            shutil.copy2(FIXTURE_ROOT / "docs" / "implementation-plan.md", plan_dir / "implementation-plan.md")
            shutil.copy2(FIXTURE_ROOT / "docs" / "t30-ticket.md", plan_dir / "t30-ticket.md")
            self._initialize_dirty_product(product)
            runtime = product / ".dev-supervisor"
            runtime.mkdir()
            shutil.copy2(FIXTURE_ROOT / "policy.json", product / "dev-supervisor.json")
            shutil.copy2(ENGINE_ROOT / "dev", product / "dev")
            (product / "dev").chmod(0o755)
            shutil.copy2(FIXTURE_ROOT / "quota.json", runtime / "quota.json")
            (runtime / "supervisor.lock").touch()
            (runtime / "runs" / "redacted-t30-run").mkdir(parents=True)
            (runtime / "runs" / "redacted-t30-run" / "invocation.json").write_text(
                '{"completed": true, "redacted": true}\n', encoding="utf-8",
            )
            state = (FIXTURE_ROOT / "state.json").read_text(encoding="utf-8")
            state = state.replace("__PRODUCT_HEAD__", git(product, "rev-parse", "HEAD"))
            state = state.replace("__PRODUCT_FINGERPRINT__", self._fingerprint(product))
            (runtime / "state.json").write_text(state, encoding="utf-8")
            binding = (FIXTURE_ROOT / "engine.json").read_text(encoding="utf-8")
            (runtime / "engine.json").write_text(
                binding.replace("__CANDIDATE_ENGINE_ROOT__", str(ENGINE_ROOT)), encoding="utf-8",
            )

            before_runtime = runtime_snapshot(runtime)
            before_head = git(product, "rev-parse", "HEAD")
            before_fingerprint = self._fingerprint(product)
            before_status = self._status_bytes(product)
            environment, process_log = self._guarded_environment(sandbox)

            status = self._invoke(product, "status", environment)
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("State: HUMAN_GATE", status.stdout)
            self.assertIn("Ticket: T30", status.stdout)

            resume = self._invoke(product, "resume", environment)
            self.assertEqual(resume.returncode, 0, resume.stderr)
            self.assertEqual(json.loads(resume.stdout)["phase"], "HUMAN_GATE")

            self.assertEqual(runtime_snapshot(runtime), before_runtime)
            self.assertEqual(git(product, "rev-parse", "HEAD"), before_head)
            self.assertEqual(self._fingerprint(product), before_fingerprint)
            self.assertEqual(self._status_bytes(product), before_status)
            self._assert_no_model_or_network_process(process_log)

    @staticmethod
    def _initialize_dirty_product(product: Path) -> None:
        git(product, "init", "-b", "main")
        git(product, "config", "user.name", "Compatibility Fixture")
        git(product, "config", "user.email", "fixture@example.invalid")
        git(product, "add", "README.md", "product/notes.txt", "docs")
        git(product, "commit", "-m", "Redacted T30 baseline")
        notes = product / "product" / "notes.txt"
        notes.write_text(notes.read_text(encoding="utf-8") + "redacted dirty T30 work\n", encoding="utf-8")

    @staticmethod
    def _fingerprint(product: Path) -> str:
        digest = hashlib.sha256()
        raw = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all", "-z"],
            cwd=product, check=True, capture_output=True,
        ).stdout
        entries = []
        pieces = raw.split(b"\0")
        index = 0
        while index < len(pieces) and pieces[index]:
            item = pieces[index]
            status, relative = item[:2], item[3:].decode("utf-8")
            if status[:1] in b"RC" or status[1:2] in b"RC":
                index += 1
            entries.append(relative)
            index += 1
        for relative in sorted(set(entries)):
            digest.update(relative.encode())
            digest.update(b"\0")
            path = product / relative
            if path.is_file() and not path.is_symlink():
                digest.update(path.read_bytes())
            elif path.is_symlink():
                digest.update(os.readlink(path).encode())
        return digest.hexdigest()

    @staticmethod
    def _status_bytes(product: Path) -> bytes:
        return subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all", "-z"],
            cwd=product, check=True, capture_output=True,
        ).stdout

    @staticmethod
    def _guarded_environment(sandbox: Path) -> tuple[dict[str, str], Path]:
        bin_dir = sandbox / "process-guard"
        bin_dir.mkdir()
        log = sandbox / "process-guard.log"
        real_git = shutil.which("git")
        assert real_git is not None
        script = (
            "#!/bin/sh\n"
            "printf '%s %s\\n' \"$(basename \"$0\")\" \"$*\" >> \"$T30_PROCESS_LOG\"\n"
            "if [ \"$(basename \"$0\")\" = git ]; then exec \"$T30_REAL_GIT\" \"$@\"; fi\n"
            "exit 97\n"
        )
        for command in ("git", "codex", "curl", "wget", "nc", "ncat", "ssh", "scp", "rsync"):
            path = bin_dir / command
            path.write_text(script, encoding="utf-8")
            path.chmod(0o755)
        environment = dict(os.environ)
        environment.pop("DEV_SUPERVISOR_HOME", None)
        environment["PATH"] = str(bin_dir) + os.pathsep + environment.get("PATH", "")
        environment["T30_PROCESS_LOG"] = str(log)
        environment["T30_REAL_GIT"] = real_git
        return environment, log

    @staticmethod
    def _invoke(product: Path, command: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(product / "dev"), command], cwd=product, env=environment,
            text=True, capture_output=True, timeout=30,
        )

    def _assert_no_model_or_network_process(self, log: Path) -> None:
        records = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        forbidden = [record for record in records if not record.startswith("git ")]
        forbidden.extend(
            record for record in records
            if record.startswith("git ") and any(
                operation in record.split() for operation in ("push", "fetch", "pull", "clone", "ls-remote")
            )
        )
        self.assertEqual(forbidden, [], "model or network process was started: " + repr(forbidden))


if __name__ == "__main__":
    unittest.main()
