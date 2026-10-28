import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from obsidian.handoff import prepare_handoff, save_new


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.vault = self.base / "vault"
        self.vault.mkdir()
        self.pdf = self.base / "stored.pdf"
        self.pdf.write_bytes(b"%PDF-stage-two-verified-fixture")
        self.record = {"id": "record-1", "title": "Test paper", "doi": "10.1000/test", "state": "attached",
                       "item_key": "PARENT01", "attachment_key": "PDFKEY01",
                       "verification": {"sha256": hashlib.sha256(self.pdf.read_bytes()).hexdigest()}}
        self.manifest = self.base / "manifest.json"
        self.data = {"target": {"server_id": "fixture-db", "collection_name": "Research", "collection_key": "COLL0001"},
                     "records": [self.record, {"id": "pending-1", "title": "No PDF", "state": "download_failed"}]}
        self.metadata = {"zotero_key": "PARENT01", "title": "Test paper", "doi": "10.1000/test",
                         "pdf_key": "OTHERPDF", "pdf_path": "not-the-selected-attachment.pdf",
                         "pdf_attachments": [{"pdf_key": "PDFKEY01", "pdf_path": str(self.pdf)}]}
        self.loader = Mock(side_effect=lambda key: self.metadata)

    def prepare(self, limit=None):
        self.manifest.write_text(json.dumps(self.data), encoding="utf-8")
        return prepare_handoff(self.manifest, self.vault, self.loader, limit)

    def test_exact_attachment_is_selected_and_pending_papers_do_not_enter_reading(self):
        before = set(self.vault.rglob("*"))
        result = self.prepare()
        self.assertEqual(result["counts"], {"ready": 1, "blocked": 0, "pending_zotero": 1, "deferred": 0})
        self.assertEqual(result["papers"][0]["pdf_key"], "PDFKEY01")
        self.assertEqual(result["papers"][0]["state"], "ready_for_agent")
        self.loader.assert_called_once_with("PARENT01")
        self.assertEqual(set(self.vault.rglob("*")), before)

    def test_changed_pdf_is_blocked(self):
        self.pdf.write_bytes(b"changed content")
        result = self.prepare()
        self.assertEqual(result["status"], "blocked")
        self.assertIn("hash", result["blocked"][0]["reason"])

    def test_wrong_parent_is_blocked(self):
        self.metadata["zotero_key"] = "OTHER001"
        self.assertEqual(self.prepare()["status"], "blocked")

    def test_changed_doi_is_blocked(self):
        self.metadata["doi"] = "10.1000/wrong"
        self.assertIn("DOI", self.prepare()["blocked"][0]["reason"])

    def test_wrong_attachment_is_blocked(self):
        self.metadata["pdf_attachments"][0]["pdf_key"] = "OTHERPDF"
        self.assertIn("attachment", self.prepare()["blocked"][0]["reason"])

    def test_unbound_manifest_is_rejected(self):
        self.data["target"] = None
        with self.assertRaisesRegex(ValueError, "not bound"):
            self.prepare()

    def test_existing_note_and_fulltext_paths_are_reused(self):
        note = self.vault / "02vault/earlier/custom-title.md"
        note.parent.mkdir(parents=True)
        note.write_text('---\nzotero_key: "PARENT01"\nfulltext_path: 03fulltext/earlier/PARENT01.md\n---\nKeep my analysis.\n', encoding="utf-8")
        original = note.read_bytes()
        paper = self.prepare()["papers"][0]
        self.assertEqual(paper["note_path"], "02vault/earlier/custom-title.md")
        self.assertEqual(paper["fulltext_path"], "03fulltext/earlier/PARENT01.md")
        self.assertTrue(paper["note_exists"])
        self.assertFalse(paper["fulltext_exists"])
        self.assertEqual(note.read_bytes(), original)

    def test_duplicate_note_identity_requires_review(self):
        for name in ("one", "two"):
            note = self.vault / f"02vault/{name}.md"
            note.parent.mkdir(exist_ok=True)
            note.write_text("---\nzotero_key: PARENT01\n---\n", encoding="utf-8")
        self.assertIn("Multiple", self.prepare()["blocked"][0]["reason"])

    def test_existing_note_cannot_redirect_outside_vault(self):
        note = self.vault / "02vault/paper.md"
        note.parent.mkdir()
        note.write_text("---\nzotero_key: PARENT01\nfulltext_path: ../../outside.md\n---\n", encoding="utf-8")
        self.assertIn("outside", self.prepare()["blocked"][0]["reason"])

    def test_limit_defers_remaining_attached_papers(self):
        self.data["records"].append(dict(self.record, id="record-2", item_key="PARENT02"))
        result = self.prepare(limit=1)
        self.assertEqual(result["counts"]["deferred"], 1)
        self.assertEqual(self.loader.call_count, 1)

    def test_missing_verified_hash_is_not_accepted(self):
        self.record["verification"] = {}
        self.assertEqual(self.prepare()["counts"]["blocked"], 1)

    def test_output_refuses_overwrite(self):
        output = self.base / "handoff.json"
        save_new(output, {"status": "ready"})
        original = output.read_bytes()
        with self.assertRaises(FileExistsError):
            save_new(output, {"status": "changed"})
        self.assertEqual(output.read_bytes(), original)
