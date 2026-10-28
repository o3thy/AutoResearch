"""Prepare an auditable RR batch; never accept a fuzzy title as DOI evidence."""

import argparse
import copy
import json
import sys
import unicodedata
import urllib.parse
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

from rr.extract import normalize_doi, title_key
from .download import DownloadError, HTTP
from .workflow import atomic_json, now


class PlainText(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.feed(value)

    def handle_data(self, data):
        self.parts.append(data)


def match_key(value):
    text = "".join(PlainText(value or "").parts)
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def candidate_evidence(paper, work):
    titles = work.get("title") or []
    if not any(match_key(title) == match_key(paper["title"]) for title in titles):
        return {"title": False, "accepted": False}
    surname = (paper.get("rr_author_label") or "").split(",", 1)[0].strip()
    families = [a.get("family", "").strip() for a in work.get("author", []) if a.get("family")]
    author = bool(surname and any(match_key(surname) in {match_key(a), match_key(a.split()[-1])}
                                 for a in families))
    journal = bool(paper.get("journal") and any(match_key(j) == match_key(paper["journal"])
                                               for j in work.get("container-title", [])))
    years = set()
    for field in ("published", "published-online", "published-print", "issued"):
        for date in work.get(field, {}).get("date-parts", []):
            if date:
                years.add(date[0])
    year = bool(paper.get("year") and any(abs(y - paper["year"]) <= 1 for y in years))
    long_title = len(paper["title"].split()) >= 6
    accepted = bool(normalize_doi(work.get("DOI")) and
                    ((long_title and (author or journal or year)) or (author and journal)))
    return {"title": True, "author": author, "journal": journal, "year": year,
            "crossref_years": sorted(years), "accepted": accepted}


def select_candidate(paper, works):
    candidates = []
    accepted = {}
    for work in works:
        evidence = candidate_evidence(paper, work)
        doi = normalize_doi(work.get("DOI"))
        candidates.append({"doi": doi, "titles": work.get("title", []),
                           "evidence": evidence})
        if evidence["accepted"]:
            accepted[doi] = work
    if len(accepted) != 1:
        return None, {"status": "ambiguous" if accepted else "unresolved", "candidates": candidates}
    doi, work = next(iter(accepted.items()))
    return doi, {"status": "verified", "method": "exact_title_with_corroboration",
                 "candidates": candidates, "metadata": work}


def merge_inputs(paths, include_seed=False):
    papers = {}
    for path in paths:
        path = Path(path).resolve()
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        rows = data if isinstance(data, list) else data.get("related_papers", data.get("papers"))
        if not isinstance(rows, list):
            raise ValueError(f"No paper list in {path}")
        if include_seed and isinstance(data, dict):
            rows = [*rows, *data.get("seed_papers", [])]
        for row in rows:
            if not isinstance(row.get("title"), str) or not row["title"].strip():
                raise ValueError("Each paper needs a title")
            identity = title_key(row["title"])
            doi = normalize_doi(row.get("doi"))
            # Keep conflicting DOI records separate instead of hiding a conflict.
            existing = papers.get(identity)
            if existing and existing.get("doi") and doi and existing["doi"] != doi:
                identity += " doi:" + doi
            if identity not in papers:
                papers[identity] = copy.deepcopy(row)
                papers[identity]["doi"] = doi
                papers[identity]["batch_sources"] = []
            paper = papers[identity]
            if not paper.get("doi") and doi:
                paper["doi"] = doi
            if str(path) not in paper["batch_sources"]:
                paper["batch_sources"].append(str(path))
    return list(papers.values())


def prepare_batch(paths, output, limit=None, include_seed=False, resolve_dois=False, http=None):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Batch output already exists; choose a new path")
    papers = merge_inputs(paths, include_seed)
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be positive")
        papers = papers[:limit]
    report = {"schema_version": "1.0", "created_at": now(),
              "input_files": [str(Path(p).resolve()) for p in paths],
              "limit": limit, "papers": papers}
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        report["updated_at"] = now()
        report["counts"] = {"papers": len(papers), "with_doi": sum(bool(p.get("doi")) for p in papers),
                            "resolution": dict(Counter(p.get("doi_resolution", {}).get("status", "pending")
                                                        for p in papers))}
        atomic_json(output, report)

    save()
    http = http or HTTP()
    for index, paper in enumerate(papers):
        if paper.get("doi"):
            paper["doi_resolution"] = {"status": "from_input"}
        elif resolve_dois:
            print(f"[{index + 1}/{len(papers)}] Resolve DOI: {paper['title']}", file=sys.stderr, flush=True)
            url = "https://api.crossref.org/works?" + urllib.parse.urlencode(
                {"query.title": paper["title"], "rows": 10})
            try:
                works = http.json(url)["message"]["items"]
                doi, audit = select_candidate(paper, works)
                audit.update(query_url=url, checked_at=now())
                paper["doi_resolution"] = audit
                if doi:
                    paper["doi"] = doi
                    paper["doi_original_rr"] = None
            except (DownloadError, KeyError, TypeError, ValueError) as exc:
                paper["doi_resolution"] = {"status": "lookup_failed", "reason": str(exc), "query_url": url}
        else:
            paper["doi_resolution"] = {"status": "not_requested"}
        save()
    return report


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Merge RR lists and optionally verify missing DOI metadata")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--include-seed", action="store_true")
    parser.add_argument("--resolve-dois", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = prepare_batch(args.inputs, args.output, args.limit, args.include_seed, args.resolve_dois)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps({"output": str(args.output.resolve()), "counts": report["counts"]}, ensure_ascii=False, indent=2))
