#!/usr/bin/env python3
"""Deterministic checks for the deliberately maintained translation subset.

These checks establish pairing, local-link resolution, and English-source freshness.
They do not compare meaning and do not make a translation normative.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote


LINK = re.compile(r"(?<!!)\[[^]]*\]\(([^)]+)\)")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_target(value: str) -> str | None:
    value = value.strip().strip("<>")
    if not value or value.startswith(("#", "http://", "https://", "mailto:")):
        return None
    return unquote(value.split("#", 1)[0]) or None


def check_links(root: Path, paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        for target in LINK.findall(path.read_text(encoding="utf-8")):
            local = local_target(target)
            if local and not (path.parent / local).resolve().is_file():
                errors.append(f"broken local link in {path.relative_to(root)}: {target}")
    return errors


def check(root: Path, manifest_path: Path) -> list[str]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"invalid manifest: {error}"]
    if manifest.get("normative_language") != "en":
        return ["manifest must declare English (en) as normative_language"]
    pairs = manifest.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        return ["manifest must contain a non-empty pairs list"]
    errors: list[str] = []
    english: set[str] = set()
    russian: set[str] = set()
    linked_docs = [manifest_path]
    for number, pair in enumerate(pairs, start=1):
        if not isinstance(pair, dict):
            errors.append(f"pair {number} is not an object")
            continue
        en, ru, reviewed = pair.get("english"), pair.get("russian"), pair.get("english_sha256")
        if not all(isinstance(value, str) and value for value in (en, ru, reviewed)):
            errors.append(f"pair {number} must declare english, russian, and english_sha256")
            continue
        if en in english or ru in russian:
            errors.append(f"pair {number} duplicates a declared English or Russian path")
        english.add(en)
        russian.add(ru)
        en_path, ru_path = root / en, root / ru
        linked_docs.extend((en_path, ru_path))
        if not en_path.is_file() or not ru_path.is_file():
            errors.append(f"pair {number} has a missing declared path")
            continue
        if digest(en_path) != reviewed:
            errors.append(f"pair {number} is stale: refresh english_sha256 after translation review")
    errors.extend(check_links(root, linked_docs))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=Path("docs/translation-manifest.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    errors = check(root, (root / args.manifest).resolve())
    if errors:
        print("documentation governance check failed:", *errors, sep="\n- ", file=sys.stderr)
        return 1
    print("documentation governance check passed (pairing, links, freshness only; no semantic-equivalence claim)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
