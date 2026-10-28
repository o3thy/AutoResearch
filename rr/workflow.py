"""Search, seed verification, citation expansion, and bounded evidence capture."""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .browser import BrowserError
from .extract import deduplicate, normalize_doi, page_info, parse_cards, parse_detail, title_key, tree

APP_URL = "https://app.researchrabbit.ai/"
RELATIONS = {"similar": "Similar", "references": "Refs", "citations": "Cited By"}


def now():
    return datetime.now(timezone.utc).isoformat()


def xpath_literal(value):
    if "'" not in value:
        return "'" + value + "'"
    if '"' not in value:
        return '"' + value + '"'
    return "concat(" + ', "\'", '.join("'" + part + "'" for part in value.split("'")) + ")"


def result(operation, query=None, source="live_browser"):
    return {"schema_version": "1.0", "platform": "ResearchRabbit", "source": source,
            "operation": operation, "query": query, "status": "partial", "captured_at": now(),
            "seed_papers": [], "related_papers": [], "authors_to_watch": [], "clusters": [],
            "next_searches": [], "pages": [], "duplicates": [], "gaps": [],
            "coverage": {"reported_total": None, "raw_count": 0, "unique_count": 0,
                         "complete": False}}


def collect(snapshots, operation, query=None, source="saved_html", seed=None):
    output = result(operation, query, source)
    if seed:
        output["seed_papers"] = [seed]
    raw = []
    ranges = set()
    for index, snapshot in enumerate(snapshots):
        html = snapshot["html"]
        info = page_info(html)
        page_id = str(snapshot.get("evidence_file") or f"inline-page:{index + 1}")
        cards = parse_cards(html, snapshot.get("url"))
        direct = parse_detail(html, snapshot.get("url")) if not cards and operation == "search" else None
        if direct and query and ((normalize_doi(query) and direct["doi"] == normalize_doi(query)) or
                                 title_key(query) == title_key(direct["title"])):
            cards = [direct]
            info["pagination"] = {"start": 1, "end": 1, "total": 1}
        for card in cards:
            card.update({"discovery_relation": operation, "provenance": [page_id],
                         "rr_url": snapshot.get("url")})
        raw.extend(cards)
        paging = info["pagination"]
        page_record = {"evidence_id": page_id, "evidence_file": snapshot.get("evidence_file"),
                       "url": snapshot.get("url"), "captured_at": snapshot.get("captured_at"),
                       "summary": snapshot.get("summary"),
                       "pagination": paging, "extracted_count": len(cards)}
        if not snapshot.get("evidence_file"):
            page_record["inline_html"] = html
        output["pages"].append(page_record)
        if info["login_required"] or info["blocked"]:
            output["status"] = "login_required" if info["login_required"] else "blocked"
            output["gaps"].append("ResearchRabbit access requires user intervention.")
            break
        if paging:
            total = output["coverage"]["reported_total"]
            if total is not None and total != paging["total"]:
                output["gaps"].append("Reported total changed during capture.")
            output["coverage"]["reported_total"] = paging["total"]
            # Only credit a page if every displayed row was extracted.
            if 1 <= paging["start"] <= paging["end"] <= paging["total"] and len(cards) == paging["end"] - paging["start"] + 1:
                ranges.update(range(paging["start"], paging["end"] + 1))
        if info["empty"] and not cards:
            output["status"] = "empty"
            output["coverage"]["reported_total"] = 0
    output["related_papers"], output["duplicates"] = deduplicate(raw)
    coverage = output["coverage"]
    coverage.update(raw_count=len(raw), unique_count=len(output["related_papers"]))
    total = coverage["reported_total"]
    coverage["complete"] = total is not None and len(ranges) == total and not output["gaps"]
    if total and coverage["complete"]:
        coverage["complete"] = min(ranges) == 1 and max(ranges) == total
    if output["status"] not in {"login_required", "blocked", "empty"}:
        output["status"] = "ok" if coverage["complete"] else "partial" if raw else "dom_changed"
    if not coverage["complete"] and output["status"] not in {"login_required", "blocked"}:
        output["gaps"].append("Result coverage is incomplete or the page range is unavailable.")
    if raw:
        output["gaps"].append("RR list metadata is unverified; initials/author labels are not full author lists.")
    return output


class ResearchRabbit:
    def __init__(self, browser, evidence_dir=None, max_pages=10, wait_seconds=25):
        self.browser = browser
        self.evidence_dir = Path(evidence_dir) if evidence_dir else None
        self.max_pages = max_pages
        self.wait_seconds = wait_seconds

    def check_access(self):
        html = self.browser.html()
        info = page_info(html)
        if info["login_required"]:
            raise BrowserError("login_required: log in manually in the ResearchRabbit browser, then retry.")
        if info["blocked"]:
            raise BrowserError("blocked: ResearchRabbit requires user intervention.")
        return html

    def wait(self, predicate):
        deadline = time.monotonic() + self.wait_seconds
        while True:
            html = self.check_access()
            if predicate(html):
                return html
            if time.monotonic() >= deadline:
                raise BrowserError("dom_changed: expected ResearchRabbit view did not appear before timeout.")
            time.sleep(0.5)

    def search_start(self, query):
        self.browser.run("navigate", APP_URL)
        self.wait(lambda html: any(n.tag == "input" and n.attrs.get("name") == "query" for n in tree(html).walk()))
        self.browser.input('input[name="query"]', query)
        self.browser.click('form button[type="submit"]')
        return self.wait(lambda html: bool(parse_cards(html)) or parse_detail(html) is not None or page_info(html)["empty"])

    def capture(self, operation, query=None, seed=None):
        snapshots = []
        failure = None
        try:
            self.capture_pages(operation, snapshots)
        except BrowserError as exc:
            if not snapshots:
                raise
            failure = str(exc)
        output = collect(snapshots, operation, query, "live_browser", seed)
        if failure:
            output["status"] = next((status for status in ("login_required", "blocked")
                                     if failure.startswith(status + ":")), "partial")
            output["coverage"]["complete"] = False
            output["gaps"].append(failure)
        return output

    def capture_pages(self, operation, snapshots):
        seen = set()
        for index in range(self.max_pages):
            self.check_access()
            snapshot = self.browser.snapshot()
            snapshot["captured_at"] = now()
            # Never associate unrelated pages with the selected RR session.
            if urlparse(snapshot["url"]).hostname != "app.researchrabbit.ai":
                raise BrowserError("Unexpected browser destination; capture stopped.")
            info = page_info(snapshot["html"])
            signature = json.dumps(info["pagination"]) + json.dumps([p["title"] for p in parse_cards(snapshot["html"])])
            if signature in seen:
                raise BrowserError("Pagination returned a previously captured page; capture stopped.")
            seen.add(signature)
            snapshot["view"] = operation
            if self.evidence_dir:
                self.evidence_dir.mkdir(parents=True, exist_ok=True)
                path = self.evidence_dir / f"page-{index + 1:03d}.json"
                with path.open("x", encoding="utf-8") as stream:
                    json.dump(snapshot, stream, ensure_ascii=False, indent=2)
                snapshot["evidence_file"] = str(path.resolve())
            snapshots.append(snapshot)
            paging = info["pagination"]
            if not paging or paging["end"] >= paging["total"]:
                break
            if index + 1 == self.max_pages:
                raise BrowserError(f"Page limit reached ({self.max_pages}); additional results were not captured.")
            selector = self.next_page_selector()
            if not selector:
                raise BrowserError("Next page control could not be identified from the current DOM.")
            self.browser.click(selector)
            self.wait(lambda html: (page_info(html)["pagination"] or {}).get("start", 0) > paging["start"])

    def next_page_selector(self):
        # Recognize a forward arrow by its own accessible label; never click an
        # arbitrary unlabeled toolbar button when the pagination DOM has changed.
        html = self.check_access()
        root = tree(html)
        candidates = [n for n in root.walk() if n.tag == "button" and "disabled" not in n.attrs
                      and any(re.fullmatch(r"next(?: page)?|forward", n.attrs.get(attr, "").strip(), re.I)
                              for attr in ("aria-label", "title"))]
        if len(candidates) == 1:
            node = candidates[0]
            for attr in ("aria-label", "title"):
                if node.attrs.get(attr):
                    return "xpath=//button[@" + attr + "=" + xpath_literal(node.attrs[attr]) + "]"
        arrows = [n for n in root.walk() if n.tag == "button" and "disabled" not in n.attrs
                  and n.has_class("Button__LightBackground-") and any(
                      c.tag == "path" and c.attrs.get("d", "").startswith("m14.03 8.97") for c in n.walk())]
        if len(arrows) == 1 and page_info(html)["pagination"]:
            return "xpath=//button[contains(@class,'Button__LightBackground-') and not(@disabled)][.//*[local-name()='path'][starts-with(@d,'m14.03 8.97')]]"
        return None

    def open_seed(self, query, title=None):
        html = self.search_start(query)
        direct = parse_detail(html)
        if direct:
            selected = direct
            if title and title_key(title) != title_key(direct["title"]):
                raise BrowserError("seed_mismatch: direct search result differs from --title.")
            if not title and not normalize_doi(query) and title_key(query) != title_key(direct["title"]):
                raise BrowserError("ambiguous_seed: supply an exact seed title or DOI.")
        else:
            selected = self.select_seed(html, query, title)
        snapshot = self.browser.snapshot()
        detail = parse_detail(snapshot["html"], snapshot["url"])
        if not detail or title_key(detail["title"]) != title_key(selected["title"]):
            raise BrowserError("seed_mismatch: opened article does not match the selected seed.")
        expected_doi = normalize_doi(query)
        if expected_doi and detail["doi"] != expected_doi:
            raise BrowserError("seed_mismatch: ResearchRabbit DOI does not match the supplied DOI.")
        detail["year"] = detail["year"] or selected["year"]
        detail["journal"] = detail["journal"] or selected["journal"]
        if self.evidence_dir:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            path = self.evidence_dir / "seed.json"
            with path.open("x", encoding="utf-8") as stream:
                json.dump({**snapshot, "captured_at": now(), "view": "detail"}, stream, ensure_ascii=False, indent=2)
            detail["provenance"] = [str(path.resolve())]
        return detail

    def select_seed(self, html, query, title):
        candidates = parse_cards(html)
        wanted = title or (None if normalize_doi(query) else query)
        if wanted:
            candidates = [p for p in candidates if title_key(p["title"]) == title_key(wanted)]
        if len(candidates) != 1:
            raise BrowserError("ambiguous_seed: provide an exact --title; no unique seed was identified on the first page.")
        selected = candidates[0]
        selector = "xpath=//button[contains(@class,'ListItemArticleDetails__Container-')][.//p[normalize-space(.)=" + xpath_literal(selected["title"]) + "]]"
        self.browser.click(selector)
        self.wait(lambda html: parse_detail(html) is not None)
        return selected

    def expand(self, query, relation, title=None):
        seed = self.open_seed(query, title)
        label = RELATIONS[relation]
        selector = "xpath=//button[contains(@class,'ExploreFurtherButton__StyledButton-')][starts-with(normalize-space(.)," + xpath_literal(label) + ")]"
        if relation != "similar":
            # Narrow windows replace the labels with the observed backward/forward icons.
            path_prefix = "m1.67 12" if relation == "references" else "m22.33 12"
            selector = "xpath=//button[contains(@class,'ExploreFurtherButton__StyledButton-')][starts-with(normalize-space(.)," + xpath_literal(label) + ") or .//*[local-name()='path'][starts-with(@d," + xpath_literal(path_prefix) + ")]]"
        self.browser.click(selector)
        headings = {"similar": "Similar articles", "references": "References", "citations": "Citations"}
        self.wait(lambda html: bool(parse_cards(html)) or page_info(html)["empty"])
        summary = self.browser.evaluate("document.querySelector('[class*=SearchSummary__Container-]')?.innerText")
        if not summary or headings[relation].casefold() not in summary.casefold():
            raise BrowserError("dom_changed: selected relationship view could not be verified.")
        return self.capture(relation, query, seed)
