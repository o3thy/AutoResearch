import json
import tempfile
import unittest
from pathlib import Path

from zotero.batch import merge_inputs, prepare_batch, select_candidate


class BatchTests(unittest.TestCase):
    paper = {"title": "Safe spacecraft control with reinforcement learning techniques", "doi": None,
             "year": 2025, "rr_author_label": "Zhou, 2025", "journal": "Aerospace"}

    def work(self, doi="10.1000/test", **changes):
        return {"DOI": doi, "title": [self.paper["title"]], "author": [{"family": "Zhou"}],
                "container-title": ["Aerospace"], "published": {"date-parts": [[2025]]}, **changes}

    def test_exact_title_with_corroboration(self):
        doi, audit = select_candidate(self.paper, [self.work()])
        self.assertEqual(doi, "10.1000/test")
        self.assertEqual(audit["status"], "verified")

    def test_fuzzy_title_is_not_accepted(self):
        doi, _ = select_candidate(self.paper, [self.work(title=[self.paper["title"] + " II"])])
        self.assertIsNone(doi)

    def test_two_exact_dois_are_ambiguous(self):
        doi, audit = select_candidate(self.paper, [self.work(), self.work("10.1000/other")])
        self.assertIsNone(doi)
        self.assertEqual(audit["status"], "ambiguous")

    def test_title_without_corroboration_is_rejected(self):
        doi, _ = select_candidate(self.paper, [self.work(author=[], **{"container-title": [], "published": {}})])
        self.assertIsNone(doi)

    def test_short_title_requires_author_and_journal(self):
        paper = {**self.paper, "title": "Safe spacecraft control"}
        work = self.work(title=[paper["title"]], author=[])
        self.assertIsNone(select_candidate(paper, [work])[0])

    def test_author_matching_does_not_use_arbitrary_suffixes(self):
        paper = {**self.paper, "title": "Safe spacecraft control", "rr_author_label": "Li, 2025"}
        work = self.work(title=[paper["title"]], author=[{"family": "Pauli"}])
        self.assertIsNone(select_candidate(paper, [work])[0])

    def test_input_order_limit_and_original_preserved(self):
        class HTTP:
            def json(inner, url):
                return {"message": {"items": [self.work()]}}
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "rr.json", Path(directory) / "batch.json"
            raw = json.dumps({"related_papers": [self.paper, self.paper, {"title": "Later", "doi": None}]})
            source.write_text(raw, encoding="utf-8")
            self.assertEqual(len(merge_inputs([source])), 2)
            batch = prepare_batch([source], output, limit=1, resolve_dois=True, http=HTTP())
            self.assertEqual(batch["counts"]["papers"], 1)
            self.assertEqual(batch["papers"][0]["doi"], "10.1000/test")
            self.assertEqual(source.read_text(encoding="utf-8"), raw)
            with self.assertRaises(ValueError):
                prepare_batch([source], output)

    def test_doi_conflicts_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rr.json"
            source.write_text(json.dumps([dict(self.paper, doi="10.1000/one"),
                                          dict(self.paper, doi="10.1000/two")]), encoding="utf-8")
            self.assertEqual(len(merge_inputs([source])), 2)
