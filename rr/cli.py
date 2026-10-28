import argparse
import json
import sys
from pathlib import Path

from .browser import BrowserAct, BrowserError
from .workflow import APP_URL, ResearchRabbit, collect, now, result


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description="AutoResearch ResearchRabbit workflow")
    parser.add_argument("--session", default="rr-zotero-obsidian")
    parser.add_argument("--output", type=Path, help="New JSON file; existing files are never overwritten")
    parser.add_argument("--evidence-dir", type=Path, help="New capture directory")
    parser.add_argument("--max-pages", type=positive, default=10)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check BrowserAct and ResearchRabbit session")
    opened = sub.add_parser("open", help="Open an existing BrowserAct profile for manual login")
    opened.add_argument("--browser-id", required=True)
    search = sub.add_parser("search", help="Search by keywords, title, or DOI")
    search.add_argument("query")
    expanded = sub.add_parser("expand", help="Expand one verified seed")
    expanded.add_argument("query")
    expanded.add_argument("--relation", choices=["similar", "references", "citations"], required=True)
    expanded.add_argument("--title", help="Exact RR title to disambiguate the seed")
    sub.add_parser("capture", help="Capture the current result list")
    replay = sub.add_parser("replay", help="Parse saved HTML or BrowserAct JSON evidence offline")
    replay.add_argument("files", nargs="+", type=Path)
    replay.add_argument("--relation", choices=["search", "similar", "references", "citations"], default="search")
    replay.add_argument("--query")
    args = parser.parse_args(argv)
    if args.output and args.output.exists():
        parser.error("--output already exists; choose a new filename")
    if args.evidence_dir and args.evidence_dir.exists():
        parser.error("--evidence-dir already exists; choose a new directory")
    try:
        if args.command == "replay":
            snapshots = []
            for path in args.files:
                content = path.read_text(encoding="utf-8-sig")
                snapshot = json.loads(content) if path.suffix.lower() == ".json" else {"html": content}
                if isinstance(snapshot.get("result"), list) and all(isinstance(x, str) for x in snapshot["result"]):
                    snapshot["html"] = "".join(snapshot["result"])
                elif isinstance(snapshot.get("result"), dict):
                    snapshot = snapshot["result"]
                if snapshot.get("ok") is False or not isinstance(snapshot.get("html"), str):
                    raise ValueError(f"Not valid HTML evidence: {path}")
                if snapshot.get("view") and snapshot["view"] != args.relation:
                    raise ValueError(f"Evidence view differs from --relation: {path}")
                snapshot["evidence_file"] = str(path.resolve())
                snapshots.append(snapshot)
            output = collect(snapshots, args.relation, args.query)
        else:
            browser = BrowserAct(args.session)
            workflow = ResearchRabbit(browser, args.evidence_dir, args.max_pages)
            if args.command == "open":
                browser.run("browser", "open", args.browser_id, APP_URL, "--headed")
                output = result("open")
                workflow.check_access()
                output["status"] = "ok"
            elif args.command == "doctor":
                state = browser.run("state")
                if not str(state.get("url", "")).startswith(APP_URL):
                    raise BrowserError("Current tab is not ResearchRabbit; open the app in this session first.")
                workflow.check_access()
                output = result("doctor")
                output["status"] = "ok"
            elif args.command == "search":
                workflow.search_start(args.query)
                output = workflow.capture("search", args.query)
            elif args.command == "expand":
                output = workflow.expand(args.query, args.relation, args.title)
            else:
                output = workflow.capture("capture")
        output["completed_at"] = now()
    except (BrowserError, ValueError, OSError, KeyError) as exc:
        output = result(args.command, getattr(args, "query", None), "saved_html" if args.command == "replay" else "live_browser")
        message = str(exc)
        output["status"] = next((s for s in ("login_required", "blocked", "dom_changed", "ambiguous_seed", "seed_mismatch")
                                 if message.startswith(s + ":")), "error")
        output["gaps"] = [message]
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(output, stream, ensure_ascii=False, indent=2)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return_code = 0 if output["status"] in {"ok", "empty"} else 2 if output["status"] == "partial" else 1
    if return_code:
        raise SystemExit(return_code)
