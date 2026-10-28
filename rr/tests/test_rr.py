import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rr.browser import BrowserAct, BrowserError
from rr.extract import deduplicate, normalize_doi, page_info, paper, parse_cards, parse_detail
from rr.workflow import ResearchRabbit, collect, xpath_literal


def card(title="Example paper", year=2025, abstract="(No abstract)"):
    return f'''<div class="ListItemContainer-sc-old-hash">
      <button class="ListItemArticleDetails__Container-sc-new-hash">
        <h4 class="ListItemArticleDetails__Nickname-sc-new">Cai, {year}</h4>
        <p class="ListItemArticleDetails__Title-sc-new">{title}</p>
        <p class="ListItemArticleDetails__Journal-sc-new">Example Journal</p>
      </button><button class="ListSelectionButton-sc-new"></button>
      <p class="ListItemArticleVerbose__Abstract-sc-new">{abstract}</p></div>'''


DETAIL = '''<div class="InspectorStyles__Content-sc-new">
<h3 class="ArticleDetailsDisplay__Nickname-sc-new">Cai, 2025</h3>
<h5 class="ArticleTitle__Title-sc-new"><a href="https://doi.org/10.1016/j.ast.2025.111515">Seed title</a></h5>
<p class="ArticleDetailsDisplay__Journal-sc-new">AST</p>
<button class="ArticleAuthors__AuthorButton-sc-new">Yingkai Cai</button>
<button class="ArticleAuthors__MoreButton-sc-new">... +1</button>
<p class="ArticleDetailsDisplay__AbstractParagraph-sc-new">10.1016/J.AST.2025.111515</p>
<p class="ArticleDetailsDisplay__AbstractParagraph-sc-new">No abstract</p></div>'''


class ExtractionTests(unittest.TestCase):
    def test_card_does_not_guess_authors_or_year_from_title(self):
        data = parse_cards(card("A 2020 review &amp; new evidence", 2025))[0]
        self.assertEqual(data["title"], "A 2020 review & new evidence")
        self.assertEqual(data["year"], 2025)
        self.assertEqual(data["authors"], [])
        self.assertIsNone(data["abstract"])

    def test_inspector_doi_not_taken_from_other_cards(self):
        data = parse_detail('<p>10.1000/wrong</p>' + DETAIL)
        self.assertEqual(data["doi"], "10.1016/j.ast.2025.111515")
        self.assertEqual(data["year"], 2025)
        self.assertEqual(data["authors"], ["Yingkai Cai"])
        self.assertFalse(data["authors_complete"])
        self.assertIsNone(data["abstract"])

    def test_doi_url_normalization(self):
        self.assertEqual(normalize_doi("https://doi.org/10.1016/J.AST.2025.111515"), "10.1016/j.ast.2025.111515")
        self.assertIsNone(normalize_doi("https://example.org/10.1000/test"))

    def test_duplicates_merge_evidence_but_keep_conflicting_dois(self):
        first = paper("Same title", doi="10.1000/a")
        first["provenance"] = ["page1"]
        second = {**first, "provenance": ["page2"]}
        different = paper("Same title", doi="10.1000/b")
        rows, audit = deduplicate([first, second, different])
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(audit), 1)
        self.assertEqual(rows[0]["provenance"], ["page1", "page2"])

    def test_login_and_captcha_are_not_empty_results(self):
        self.assertTrue(page_info('<input type="password">Sign in')["login_required"])
        self.assertTrue(page_info('<p>Verify you are human</p>')["blocked"])
        self.assertEqual(collect([{"html": '<input type="password">'}], "search")["status"], "login_required")

    def test_multiline_pagination(self):
        self.assertEqual(page_info('<p>1\n-\n20\nof\n47</p>')["pagination"], {"start": 1, "end": 20, "total": 47})


class CoverageTests(unittest.TestCase):
    def test_duplicate_rows_do_not_reduce_capture_completeness(self):
        pages = [{"html": card() + card() + '<p>1 - 2 of 3</p>'},
                 {"html": card("Other") + '<p>3 - 3 of 3</p>'}]
        data = collect(pages, "similar")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["coverage"], {"reported_total": 3, "raw_count": 3, "unique_count": 2, "complete": True})

    def test_footer_with_missing_rows_is_partial(self):
        data = collect([{"html": card() + '<p>1 - 20 of 20</p>'}], "similar")
        self.assertEqual(data["status"], "partial")
        self.assertFalse(data["coverage"]["complete"])

    def test_unknown_footer_is_partial(self):
        self.assertEqual(collect([{"html": card()}], "references")["status"], "partial")

    def test_confirmed_empty_is_distinct_from_changed_dom(self):
        empty = collect([{"html": '<p>No results found</p>'}], "search")
        changed = collect([{"html": '<p>Unexpected new layout</p>'}], "search")
        self.assertEqual(empty["status"], "empty")
        self.assertTrue(empty["coverage"]["complete"])
        self.assertEqual(changed["status"], "dom_changed")

    def test_exact_doi_direct_hit(self):
        data = collect([{"html": DETAIL}], "search", "10.1016/j.ast.2025.111515")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["coverage"]["unique_count"], 1)
        self.assertEqual(collect([{"html": DETAIL}], "search", "10.1000/wrong")["status"], "dom_changed")

    def test_changed_total_prevents_success(self):
        data = collect([{"html": card() + '<p>1 - 1 of 2</p>'},
                        {"html": card("Other") + '<p>2 - 2 of 3</p>'}], "similar")
        self.assertEqual(data["status"], "partial")

    def test_invalid_pagination_cannot_claim_complete(self):
        data = collect([{"html": card() + card("Other") + '<p>0 - 1 of 2</p>'}], "similar")
        self.assertFalse(data["coverage"]["complete"])

    def test_inline_evidence_does_not_reference_a_missing_file(self):
        html = card() + '<p>1 - 1 of 1</p>'
        data = collect([{"html": html}], "similar")
        self.assertIsNone(data["pages"][0]["evidence_file"])
        self.assertEqual(data["pages"][0]["inline_html"], html)
        self.assertEqual(data["related_papers"][0]["provenance"], [data["pages"][0]["evidence_id"]])


class BrowserTests(unittest.TestCase):
    @patch("rr.browser.shutil.which", return_value="browser-act.exe")
    @patch("rr.browser.subprocess.run")
    def test_json_error_on_stderr_is_preserved(self, run, which):
        run.return_value = subprocess.CompletedProcess([], 1, "", '{"ok":false,"error":"No active session"}')
        with self.assertRaisesRegex(BrowserError, "No active session"):
            BrowserAct().run("state")
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(run.call_args.kwargs["env"]["PYTHONUTF8"], "1")

    @patch("rr.browser.shutil.which", return_value="browser-act.exe")
    @patch("rr.browser.subprocess.run", side_effect=subprocess.TimeoutExpired("browser-act", 45))
    def test_timeout_is_explicit(self, run, which):
        with self.assertRaisesRegex(BrowserError, "timed out"):
            BrowserAct().run("state")

    def test_forward_pager_selected_from_observed_icon(self):
        html = card() + '<p>1 - 20 of 47</p><button class="Button__LightBackground-sc-new"><svg><path d="m14.03 8.97-example"></path></svg></button>'
        class Browser:
            def html(self):
                return html
        self.assertIn("m14.03 8.97", ResearchRabbit(Browser()).next_page_selector())

    def test_xpath_literal_handles_both_quote_types(self):
        self.assertEqual(xpath_literal("Plain title"), "'Plain title'")
        self.assertTrue(xpath_literal('Author\'s "study"').startswith("concat("))

    def test_connection_failure_preserves_captured_rows(self):
        html = card() + '<p>1 - 1 of 2</p><button aria-label="Next page"></button>'
        class Browser:
            def html(self):
                return html
            def snapshot(self):
                return {"url": "https://app.researchrabbit.ai/search/test/0", "html": html}
            def click(self, selector):
                raise BrowserError("Connection failed")
        data = ResearchRabbit(Browser()).capture("similar")
        self.assertEqual(data["status"], "partial")
        self.assertEqual(data["coverage"]["raw_count"], 1)
        self.assertIn("Connection failed", data["gaps"])

    def test_partial_when_page_limit_reached(self):
        html = card() + '<p>1 - 1 of 2</p>'
        class Browser:
            def html(self):
                return html
            def snapshot(self):
                return {"url": "https://app.researchrabbit.ai/search/test/0", "html": html}
            def click(self, selector):
                raise AssertionError("Should not navigate beyond the page limit")
        data = ResearchRabbit(Browser(), max_pages=1).capture("similar")
        self.assertEqual(data["status"], "partial")
        self.assertFalse(data["coverage"]["complete"])
        self.assertTrue(any("Page limit reached" in gap for gap in data["gaps"]))

    def test_missing_exact_title_refuses_to_pick_a_different_paper(self):
        class Browser:
            def click(self, selector):
                raise AssertionError("An unrelated seed must not be opened")
        with self.assertRaisesRegex(BrowserError, "ambiguous_seed"):
            ResearchRabbit(Browser()).select_seed(card("Different paper"), "Seed title", "Seed title")

    def test_direct_seed_with_wrong_doi_is_rejected(self):
        class Browser:
            def snapshot(self):
                return {"html": DETAIL, "url": "https://app.researchrabbit.ai/"}
        workflow = ResearchRabbit(Browser())
        with patch.object(workflow, "search_start", return_value=DETAIL):
            with self.assertRaisesRegex(BrowserError, "seed_mismatch"):
                workflow.open_seed("10.1000/wrong")


class CliTests(unittest.TestCase):
    def test_replay_original_browseract_array_and_refuse_overwrite(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "page.json"
            saved.write_text(json.dumps({"ok": True, "result": [card(), '<p>1 - 1 of 1</p>']}), encoding="utf-8")
            output = Path(directory) / "result.json"
            command = ["python", str(root / "rr/scripts/researchrabbit.py"), "--output", str(output),
                       "replay", str(saved), "--relation", "similar"]
            first = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["source"], "saved_html")
            self.assertEqual(data["related_papers"][0]["discovery_relation"], "similar")
            before = output.read_bytes()
            second = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(before, output.read_bytes())


if __name__ == "__main__":
    unittest.main()
