import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

from zotero.client import AuthorizationRequired, ZoteroClient, ZoteroError
from zotero.download import DownloadError, Downloader, PDFLinks
from zotero.pdf import PDFError, inspect_pdf
from zotero.workflow import (FAILURE_CSV_SUFFIX, archive, bind_target, failure_csv_path, load_records,
                             manual_import, prepare, retry_downloads, validate_failure_csv_path)


def pdf_bytes(title="Test research paper"):
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    writer.add_metadata({"/Title": title})
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class FakeDownloader:
    def acquire(self, record):
        if record["doi"] == "10.1000/success":
            content = pdf_bytes(record["title"])
            return {"state": "downloaded", "content": content,
                    "verification": inspect_pdf(content, record["title"], record["doi"])}
        return {"state": "missing_doi" if not record["doi"] else "download_failed", "reason": "Unavailable", "attempts": []}


class FakeClient:
    server_id = "test-db"
    def __init__(self):
        self.parents = {}
        self.attachments = {}
    def collection(self, identifier):
        return {"key": identifier, "data": {"name": "test"}}
    def ensure_paper(self, record, key):
        self.parents.setdefault(record["id"], record["item_key"])
        return self.parents[record["id"]]
    def attach_pdf(self, parent, path, record, checkpoint):
        content = Path(path).read_bytes()
        self.attachments.setdefault(parent, content)
        return {"key": "PDFKEYAA", "path": str(path)}


class PDFTests(unittest.TestCase):
    def test_valid_pdf_requires_identity(self):
        self.assertEqual(inspect_pdf(pdf_bytes(), "Test research paper")["pages"], 1)
        with self.assertRaises(PDFError):
            inspect_pdf(pdf_bytes("Wrong paper"), "Expected paper")

    def test_short_title_can_match_exact_pdf_metadata(self):
        self.assertEqual(inspect_pdf(pdf_bytes("Adam"), "Adam")["identity"], "title")
    def test_html_and_truncated_files_are_rejected(self):
        with self.assertRaises(PDFError):
            inspect_pdf(b"<html>Sign in</html>", "Test research paper")
        with self.assertRaises(PDFError):
            inspect_pdf(pdf_bytes()[:-100], "Test research paper")
    def test_scanned_pdf_needs_explicit_mapping(self):
        with self.assertRaises(PDFError):
            inspect_pdf(pdf_bytes(""), "Test research paper")
        self.assertEqual(inspect_pdf(pdf_bytes(""), "Test research paper", explicit_mapping=True)["identity"], "user_mapping_scanned_pdf")
    def test_a_reference_doi_alone_does_not_prove_identity(self):
        with patch("zotero.pdf.PdfReader") as reader:
            reader.return_value.is_encrypted = False
            reader.return_value.pages = [type("Page", (), {"extract_text": lambda self: "Unrelated title. References: 10.1000/expected"})()]
            reader.return_value.metadata = {}
            with self.assertRaises(PDFError):
                inspect_pdf(pdf_bytes(), "Expected title", "10.1000/expected")


class DownloadTests(unittest.TestCase):
    def test_crossref_unspecified_pdf_link_is_attempted_first(self):
        observed = []
        class HTTP:
            def json(self, url):
                return {"message": {"DOI": "10.1000/test", "title": ["Test research paper"],
                                    "link": [{"URL": "https://publisher.example/123/pdf", "content-type": "unspecified"}]}}
            def get(self, url, *args):
                observed.append(url)
                return {"url": url, "content": pdf_bytes(), "content_type": "application/pdf"}
        result = Downloader(HTTP()).acquire({"title": "Test research paper", "doi": "10.1000/test"})
        self.assertEqual(result["state"], "downloaded")
        self.assertEqual(observed, ["https://publisher.example/123/pdf"])

    def test_browser_challenge_is_reported_without_following_it(self):
        class HTTP:
            def json(self, url):
                return {"message": {"DOI": "10.1000/test"}}
            def get(self, url, *args):
                return {"url": url, "content": b'<html><iframe src="/akamai/interstitial.html"></iframe></html>',
                        "content_type": "text/html", "charset": "utf-8"}
        result = Downloader(HTTP()).acquire({"title": "Test research paper", "doi": "10.1000/test"})
        self.assertEqual(result["state"], "download_failed")
        self.assertIn("Browser verification required", result["reason"])
        self.assertEqual(len(result["attempts"]), 1)

    def test_explicit_publisher_pdf_requires_evidence(self):
        class HTTP:
            def json(self, url):
                return {"message": {"DOI": "10.1000/test"}}
            def get(self, url, *args):
                return {"url": url, "content": pdf_bytes(), "content_type": "application/pdf"}
        record = {"title": "Test research paper", "doi": "10.1000/test", "publisher_pdf_links": [
            {"url": "https://publisher.example/paper/pdf", "evidence_url": "https://publisher.example/paper"}]}
        self.assertEqual(Downloader(HTTP()).acquire(record)["source_url"], "https://publisher.example/paper/pdf")

    def test_relative_pdf_and_viewer_links(self):
        parser = PDFLinks("https://publisher.example/article/123")
        parser.feed('<meta name="citation_pdf_url" content="/pdf/123"><a href="/viewer/123">PDF</a>')
        self.assertEqual(parser.links, ["https://publisher.example/pdf/123", "https://publisher.example/viewer/123"])
    def test_download_follows_publisher_html_and_validates_pdf(self):
        class HTTP:
            def json(self, url):
                return {"message": {"DOI": "10.1000/success", "title": ["Test research paper"]}}
            def get(self, url, accept="", referer=None):
                if url.startswith("https://doi.org"):
                    return {"url": "https://publisher.example/article", "content": b'<meta name="citation_pdf_url" content="/paper.pdf">', "content_type": "text/html", "charset": "utf-8"}
                return {"url": url, "content": pdf_bytes(), "content_type": "application/pdf"}
        result = Downloader(HTTP()).acquire({"title": "Test research paper", "doi": "10.1000/success"})
        self.assertEqual(result["state"], "downloaded")
        self.assertEqual(result["source_url"], "https://publisher.example/paper.pdf")
    def test_wrong_pdf_is_not_accepted(self):
        class HTTP:
            def json(self, url):
                raise DownloadError("Metadata unavailable")
            def get(self, *args):
                return {"url": "https://publisher.example/wrong.pdf", "content": pdf_bytes("Wrong paper"), "content_type": "application/pdf"}
        result = Downloader(HTTP()).acquire({"title": "Expected paper", "doi": "10.1000/success"})
        self.assertEqual(result["state"], "download_failed")
        self.assertNotIn("content", result)
    def test_missing_doi_never_guessed(self):
        self.assertEqual(Downloader().acquire({"title": "Test paper", "doi": None})["state"], "missing_doi")


class WorkflowTests(unittest.TestCase):
    def test_failure_csv_uses_beijing_time_and_exact_name(self):
        stamp = datetime(2026, 10, 15, 3, 15, tzinfo=timezone.utc)
        name = failure_csv_path(Path("download"), stamp).name
        self.assertEqual(name, "202610151115" + FAILURE_CSV_SUFFIX)
        self.assertEqual(failure_csv_path(Path("download"), datetime(2026, 12, 31, 20, 5, tzinfo=timezone.utc)).name,
                         "202701010405" + FAILURE_CSV_SUFFIX)

    def test_invalid_or_legacy_failure_csv_names_are_rejected(self):
        for name in ("failed-old.csv", "202602301115" + FAILURE_CSV_SUFFIX,
                     "202610152415" + FAILURE_CSV_SUFFIX, "20261015111" + FAILURE_CSV_SUFFIX):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_failure_csv_path(Path(name))

    def test_same_minute_batches_do_not_overwrite_failure_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_input(directory)
            destination = Path(directory) / "download"
            expected = failure_csv_path(destination)
            destination.mkdir()
            expected.write_bytes(b"existing list")
            with patch("zotero.workflow.failure_csv_path", return_value=expected):
                manifest = prepare(source, destination, downloader=FakeDownloader())
            self.assertEqual(expected.read_bytes(), b"existing list")
            self.assertEqual(Path(manifest["failed_csv"]).name, expected.name)
            self.assertEqual(Path(manifest["failed_csv"]).parent, Path(manifest["manifest_path"]).parent)

    def make_input(self, directory):
        path = Path(directory) / "input.json"
        path.write_text(json.dumps({"related_papers": [
            {"title": "Test research paper", "doi": "https://doi.org/10.1000/success"},
            {"title": "Manual research paper", "doi": "10.1000/manual"},
            {"title": "No DOI paper", "doi": None}]}), encoding="utf-8")
        return path
    def test_prepare_persists_failed_csv_and_source_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = prepare(self.make_input(directory), Path(directory) / "download", downloader=FakeDownloader())
            self.assertTrue(Path(manifest["manifest_path"]).exists())
            validate_failure_csv_path(manifest["failed_csv"])
            self.assertTrue(Path(manifest["records"][0]["pdf_path"]).exists())
            content = Path(manifest["failed_csv"]).read_bytes()
            self.assertTrue(content.startswith(b"\xef\xbb\xbf"))
            with Path(manifest["failed_csv"]).open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([r["title"] for r in rows], ["Manual research paper", "No DOI paper"])
            self.assertEqual(rows[1]["doi"], "")
    def test_manual_import_and_repeat_do_not_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "download"
            manifest = prepare(self.make_input(directory), destination, downloader=FakeDownloader())
            client = FakeClient()
            archive(manifest["manifest_path"], client, "TESTKEYA")
            record = manifest["records"][1]
            (destination / record["suggested_filename"]).write_bytes(pdf_bytes("Manual research paper"))
            imported = manual_import(manifest["manifest_path"], client)
            self.assertEqual(imported["counts"].get("attached"), 2)
            self.assertEqual(len(client.parents), 2)
            self.assertEqual(len(client.attachments), 2)
            manual_import(manifest["manifest_path"], client)
            self.assertEqual(len(client.attachments), 2)
    def test_wrong_named_pdf_is_not_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "download"
            manifest = prepare(self.make_input(directory), destination, downloader=FakeDownloader())
            (destination / manifest["records"][1]["suggested_filename"]).write_bytes(pdf_bytes("Wrong title"))
            imported = manual_import(manifest["manifest_path"], FakeClient(), collection="TESTKEYA")
            self.assertEqual(imported["counts"].get("attached"), 1)
            self.assertTrue(imported["manual_import"]["rejected"])
    def test_collection_and_database_binding_cannot_change(self):
        client = FakeClient()
        manifest = {"target": None}
        bind_target(manifest, client, "TESTKEYA")
        with self.assertRaises(ZoteroError):
            bind_target(manifest, client, "OTHERKEY")
        client.server_id = "another-db"
        with self.assertRaises(ZoteroError):
            bind_target(manifest, client, "TESTKEYA")
    def test_mapping_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "download"
            manifest = prepare(self.make_input(directory), destination, downloader=FakeDownloader())
            mapping = Path(directory) / "mapping.csv"
            mapping.write_text("doi,file\n10.1000/manual,../outside.pdf\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                manual_import(manifest["manifest_path"], FakeClient(), mapping_file=mapping, collection="TESTKEYA")
    def test_duplicate_dois_are_processed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            source.write_text(json.dumps([{"title": "First", "doi": "10.1000/same"}, {"title": "Duplicate", "doi": "DOI:10.1000/SAME"}]))
            self.assertEqual(len(load_records(source)), 1)
    def test_write_gate_does_not_discard_downloaded_files(self):
        class Client(FakeClient):
            def ensure_paper(self, record, key):
                raise AuthorizationRequired("Permission required")
        with tempfile.TemporaryDirectory() as directory:
            manifest = prepare(self.make_input(directory), Path(directory) / "download", downloader=FakeDownloader())
            with self.assertRaises(AuthorizationRequired):
                archive(manifest["manifest_path"], Client(), "TESTKEYA")
            saved = json.loads(Path(manifest["manifest_path"]).read_text())
            self.assertEqual(saved["records"][0]["state"], "downloaded")
            self.assertTrue(Path(saved["records"][0]["pdf_path"]).is_file())

    def test_failed_download_can_be_retried_without_new_run(self):
        class Unavailable:
            def acquire(self, record):
                return {"state": "download_failed", "reason": "Temporary network failure"}
        with tempfile.TemporaryDirectory() as directory:
            manifest = prepare(self.make_input(directory), Path(directory) / "download", limit=1, downloader=Unavailable())
            retried = retry_downloads(manifest["manifest_path"], FakeDownloader())
            self.assertEqual(retried["manifest_path"], manifest["manifest_path"])
            self.assertEqual(retried["records"][0]["state"], "downloaded")
            self.assertTrue(Path(retried["records"][0]["pdf_path"]).is_absolute())

    def test_retry_new_csv_preserves_previous_file_and_attempt_history(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = prepare(self.make_input(directory), Path(directory) / "download", downloader=FakeDownloader())
            old_csv = Path(manifest["failed_csv"])
            original = old_csv.read_bytes()
            updated = retry_downloads(manifest["manifest_path"], FakeDownloader(), failed_csv=failure_csv_path(directory))
            self.assertEqual(old_csv.read_bytes(), original)
            self.assertTrue(Path(updated["failed_csv"]).exists())
            self.assertEqual(len(updated["records"][1]["attempt_history"]), 1)
            with self.assertRaises(ValueError):
                retry_downloads(manifest["manifest_path"], failed_csv=Path(updated["failed_csv"]))

    def test_retry_can_target_a_doi_without_touching_other_papers(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = prepare(self.make_input(directory), Path(directory) / "download", downloader=FakeDownloader())
            updated = retry_downloads(manifest["manifest_path"], FakeDownloader(), dois=["10.1000/manual"])
            self.assertEqual(len(updated["records"][1]["attempt_history"]), 1)
            self.assertNotIn("attempt_history", updated["records"][0])
            with self.assertRaises(ValueError):
                retry_downloads(manifest["manifest_path"], dois=["10.1000/not-in-list"])


class ClientTests(unittest.TestCase):
    def test_crossref_proceedings_are_conference_papers(self):
        client = object.__new__(ZoteroClient)
        client.find_paper = lambda *args: None
        observed = []
        client.create = lambda suffix, fields: observed.append(fields) or fields["key"]
        client.ensure_paper({"title": "Conference research paper", "doi": "10.1000/conference",
                             "metadata": {"type": "proceedings-article", "container-title": ["Conference proceedings"]}}, "TESTKEYA")
        self.assertEqual(observed[0]["itemType"], "conferencePaper")
        self.assertEqual(observed[0]["proceedingsTitle"], "Conference proceedings")
        self.assertNotIn("publicationTitle", observed[0])

    def test_api_base_must_stay_local(self):
        with self.assertRaises(ZoteroError):
            ZoteroClient("https://example.org")

    def test_doi_lookup_requests_everything_query_mode(self):
        client = object.__new__(ZoteroClient)
        observed = []
        def get(path):
            observed.append(path)
            return [{"key": "PARENTAA", "data": {"itemType": "journalArticle", "DOI": "10.1000/expected", "collections": ["TESTKEYA"]}}]
        client.get = get
        self.assertEqual(client.find_paper({"title": "Test research paper", "doi": "10.1000/expected"}, "TESTKEYA")["key"], "PARENTAA")
        self.assertIn("qmode=everything", observed[0])

    def test_checkpoint_parent_is_reused_without_creating_an_item(self):
        client = object.__new__(ZoteroClient)
        client.item = lambda key: {"key": key, "data": {"DOI": "10.1000/expected", "itemType": "journalArticle", "collections": ["TESTKEYA"]}}
        client.create = lambda *args: self.fail("Must not create a duplicate parent")
        client.find_paper = lambda *args: self.fail("Known key should be reconciled directly")
        self.assertEqual(client.ensure_paper({"title": "Test research paper", "doi": "10.1000/expected", "item_key": "PARENTAA"}, "TESTKEYA"), "PARENTAA")

    def test_generated_key_creation_includes_initial_version(self):
        client = object.__new__(ZoteroClient)
        client.prefix = "/api/users/0"
        observed = []
        def request(method, path, data, **kwargs):
            observed.append(data)
            return {"successful": {"0": {"key": "PARENTAA"}}, "failed": {}}
        client.request = request
        client.create("/items", {"key": "PARENTAA", "itemType": "journalArticle", "title": "Test research paper"})
        self.assertEqual(observed[0][0]["version"], 0)


if __name__ == "__main__":
    unittest.main()
