import argparse
import json
import sys
from pathlib import Path

from .client import AuthorizationRequired, ZoteroClient, ZoteroError
from .download import Downloader, HTTP
from .workflow import DEFAULT_DOWNLOAD, archive, manual_import, prepare, retry_downloads


def positive(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return value


def summary(manifest):
    counts = manifest["counts"]
    complete = counts.get("attached", 0) == len(manifest["records"])
    return {"status": "complete" if complete else "pending", "counts": counts,
            "target": manifest.get("target"), "manifest": manifest["manifest_path"],
            "failed_csv": manifest["failed_csv"], "download_dir": manifest["download_dir"],
            "manual_import": manifest.get("manual_import")}


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Publisher PDF acquisition and Zotero Desktop archiving")
    parser.add_argument("--base-url", default="http://127.0.0.1:23119")
    parser.add_argument("--auth-file", type=Path)
    parser.add_argument("--prompt-writes", action="store_true", help="Request manual Zotero authorization whenever a one-use key is consumed")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("collections")
    auth = sub.add_parser("authorize", help="Request local write permission; approve the dialog manually in Zotero")
    auth.add_argument("--timeout", type=positive, default=180)
    create = sub.add_parser("create-collection")
    create.add_argument("name")
    download = sub.add_parser("download")
    download.add_argument("input", type=Path)
    download.add_argument("--collection", help="Exact collection key or unique name")
    download.add_argument("--download-dir", type=Path, default=DEFAULT_DOWNLOAD)
    download.add_argument("--download-only", action="store_true")
    download.add_argument("--limit", type=positive)
    download.add_argument("--include-seed", action="store_true")
    download.add_argument("--email", help="Your email, required only for optional Unpaywall discovery")
    download.add_argument("--allow-repositories", action="store_true")
    download.add_argument("--timeout", type=positive, default=20)
    retry = sub.add_parser("retry", help="Retry failed downloads without changing Zotero")
    retry.add_argument("manifest", type=Path)
    retry.add_argument("--limit", type=positive)
    retry.add_argument("--email")
    retry.add_argument("--allow-repositories", action="store_true")
    retry.add_argument("--timeout", type=positive, default=20)
    retry.add_argument("--failed-csv", type=Path, help="New timestamp-named CSV when the old CSV is open/locked; see download.md")
    retry.add_argument("--doi", action="append", help="Retry only this DOI; may be repeated")
    attach = sub.add_parser("attach", help="Archive previously downloaded files; resumable")
    attach.add_argument("manifest", type=Path)
    attach.add_argument("--collection")
    ingest = sub.add_parser("ingest", help="Import user-downloaded PDFs for a pending manifest")
    ingest.add_argument("manifest", type=Path)
    ingest.add_argument("--pdf-dir", type=Path)
    ingest.add_argument("--mapping", type=Path, help="Optional CSV with doi (or id),file columns")
    ingest.add_argument("--collection")
    args = parser.parse_args(argv)
    if args.command == "download" and not args.collection and not args.download_only:
        parser.error("download requires --collection, or --download-only for preparation without Zotero writes")
    manifest = None
    exit_code = 0
    try:
        if args.command == "retry":
            manifest = retry_downloads(args.manifest, Downloader(HTTP(args.timeout), args.email, args.allow_repositories), args.limit, args.failed_csv, args.doi)
            output = summary(manifest)
            exit_code = 0 if all(r["state"] in {"downloaded", "attached"} for r in manifest["records"]) else 2
        elif args.command == "download":
            if not args.download_only:
                client = ZoteroClient(args.base_url, args.auth_file, prompt_writes=args.prompt_writes)
                client.collection(args.collection)
            manifest = prepare(args.input, args.download_dir, args.limit, args.include_seed,
                               Downloader(HTTP(args.timeout), args.email, args.allow_repositories))
            if not args.download_only:
                manifest = archive(manifest["manifest_path"], client, args.collection)
            output = summary(manifest)
            if args.download_only:
                output["status"] = "prepared"
            exit_code = 0 if output["status"] == "complete" or (args.download_only and
                         all(r["state"] == "downloaded" for r in manifest["records"])) else 2
        else:
            client = ZoteroClient(args.base_url, args.auth_file, prompt_writes=args.prompt_writes)
            if args.command == "doctor":
                output = {"status": "ok", **client.probe(), "write_key_loaded": bool(client.key)}
            elif args.command == "collections":
                output = [{"key": x["key"], "name": x["data"]["name"]} for x in client.collections()]
            elif args.command == "authorize":
                print("Zotero will show a write permission dialog. Please approve it manually; no mouse automation is used.", file=sys.stderr)
                output = client.authorize(args.timeout)
            elif args.command == "create-collection":
                output = client.create_collection(args.name)
            else:
                manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
                if args.command == "attach":
                    manifest = archive(args.manifest, client, args.collection)
                else:
                    manifest = manual_import(args.manifest, client, args.pdf_dir, args.mapping, args.collection)
                output = summary(manifest)
                exit_code = 0 if output["status"] == "complete" else 2
    except (ZoteroError, OSError, ValueError, KeyError) as exc:
        output = {"status": "authorization_required" if isinstance(exc, AuthorizationRequired) else "error", "reason": str(exc)}
        if manifest:
            output.update(manifest=manifest["manifest_path"], failed_csv=manifest["failed_csv"])
        exit_code = 3 if isinstance(exc, AuthorizationRequired) else 1
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if exit_code:
        raise SystemExit(exit_code)
