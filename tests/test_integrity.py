"""Integrity regression tests: redaction must never silently disable checks."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("artifact_provenance", ROOT/"benchmark/rivf/artifact_provenance.py")
provenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provenance)

class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.file = self.root/"input.txt"
        self.file.write_bytes(b"public redacted input")
        self.actual = hashlib.sha256(self.file.read_bytes()).hexdigest()
        self.original = hashlib.sha256(b"original private text").hexdigest()
        self.patch = patch.object(provenance, "REPO", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def manifest(self, rows):
        (self.root/"REDACTED").write_text("redacted",encoding="utf-8")
        (self.root/"MANIFEST.json").write_text(json.dumps({"files":rows}),encoding="utf-8")

    def row(self):
        return {"path":"input.txt","sha256":self.actual,"source_sha256":self.original}

    def test_private_file_uses_actual_bytes(self):
        self.assertEqual(provenance.source_sha256(self.file),self.actual)

    def test_verified_public_file_preserves_source_hash(self):
        self.manifest([self.row()])
        self.assertEqual(provenance.source_sha256(self.file),self.original)

    def test_modified_public_file_is_rejected(self):
        self.manifest([self.row()])
        self.file.write_bytes(b"tampered input")
        with self.assertRaisesRegex(ValueError,"hash mismatch"):
            provenance.source_sha256(self.file)

    def test_marker_without_manifest_does_not_bypass_check(self):
        (self.root/"REDACTED").touch()
        with self.assertRaises(FileNotFoundError):
            provenance.source_sha256(self.file)

    def test_missing_or_duplicate_entry_is_rejected(self):
        for rows in ([],[self.row(),self.row()]):
            with self.subTest(rows=len(rows)):
                self.manifest(rows)
                with self.assertRaisesRegex(ValueError,"one manifest entry"):
                    provenance.source_sha256(self.file)

if __name__=="__main__":
    unittest.main()
