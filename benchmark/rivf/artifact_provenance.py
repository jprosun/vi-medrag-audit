"""Verify public-file integrity while retaining the original input fingerprints.

The public bundle rewrites/redacts some inputs. Its manifest records both hashes.
A source hash is returned only after verifying the actual public bytes against
their manifest entry; a REDACTED marker alone never disables an integrity check.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

def source_sha256(path: Path) -> str:
    path = Path(path).resolve()
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if not (REPO / "REDACTED").exists():
        return actual
    rel = path.relative_to(REPO).as_posix()
    manifest = json.loads((REPO / "MANIFEST.json").read_text(encoding="utf-8"))
    entries = [r for r in manifest["files"] if r["path"] == rel]
    if len(entries) != 1:
        raise ValueError(f"Expected one manifest entry for {rel}")
    row = entries[0]
    if actual != row["sha256"]:
        raise ValueError(f"Public artifact hash mismatch: {rel}")
    return row["source_sha256"]
