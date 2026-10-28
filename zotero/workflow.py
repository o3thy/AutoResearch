import csv
import hashlib
import json
import os
import sys
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rr.extract import normalize_doi, title_key
from .client import AuthorizationRequired, ZoteroError, new_key
from .download import DownloadError, Downloader
from .pdf import PDFError, canonical, inspect_file

DEFAULT_DOWNLOAD = Path(__file__).resolve().parents[1] / "zotero/download"
DOWNLOAD_TIMEZONE = timezone(timedelta(hours=8), "Asia/Shanghai")
FAILURE_CSV_SUFFIX = "\u4e0b\u8f7d\u5931\u8d25\u5217\u8868.csv"


def failure_csv_path(directory, when=None):
    moment = when or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("CSV naming requires a timezone-aware timestamp")
    return Path(directory) / (moment.astimezone(DOWNLOAD_TIMEZONE).strftime("%Y%m%d%H%M") + FAILURE_CSV_SUFFIX)


def validate_failure_csv_path(path):
    path = Path(path)
    stamp = path.name.removesuffix(FAILURE_CSV_SUFFIX)
    if not path.name.endswith(FAILURE_CSV_SUFFIX) or len(stamp) != 12 or not stamp.isascii() or not stamp.isdigit():
        raise ValueError("Failure CSV filename must use YYYYMMDDHHMM + download-failure-list (Chinese) + .csv; see download.md")
    try:
        datetime.strptime(stamp, "%Y%m%d%H%M")
    except ValueError as exc:
        raise ValueError("Failure CSV filename contains an invalid date/time") from exc
    return path


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def load_records(path, include_seed=False):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(data, list):
        source = data
    elif isinstance(data, dict):
        source = data.get("related_papers", data.get("papers"))
        if not isinstance(source, list):
            raise ValueError("Input JSON must contain related_papers or papers")
        if include_seed:
            source = [*source, *data.get("seed_papers", [])]
    else:
        raise ValueError("Input JSON must be a paper list or RR result object")
    records = []
    seen = set()
    for entry in source:
        if not isinstance(entry, dict) or not isinstance(entry.get("title"), str) or not entry["title"].strip():
            raise ValueError("Each input paper requires a non-empty title")
        if entry.get("doi") is not None and not isinstance(entry["doi"], str):
            raise ValueError("DOI must be a string or null")
        doi = normalize_doi(entry.get("doi"))
        identity = "doi:" + doi if doi else "title:" + title_key(entry["title"])
        if identity in seen:
            continue
        seen.add(identity)
        identifier = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        records.append({"id": identifier, "title": entry["title"].strip(), "doi": doi,
                        "original_doi": entry.get("doi"), "year": entry.get("year"), "journal": entry.get("journal"),
                        "suggested_filename": f"rr-{identifier}.pdf", "state": "pending",
                        "item_key": None, "attachment_key": None, "pdf_path": None, "attempts": []})
    return records


def csv_value(value):
    value = str(value) if value is not None else ""
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def write_failures(manifest):
    fields = ["id", "title", "doi", "state", "reason", "suggested_filename", "zotero_item_key", "local_pdf"]
    path = Path(manifest["failed_csv"])
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record in manifest["records"]:
            if record["state"] in {"attached", "downloaded"}:
                continue
            writer.writerow({"id": record["id"], "title": csv_value(record["title"]), "doi": csv_value(record["doi"] or record.get("original_doi") or ""),
                             "state": record["state"], "reason": csv_value(record.get("reason")),
                             "suggested_filename": record["suggested_filename"],
                             "zotero_item_key": record.get("item_key") or "",
                             "local_pdf": record.get("pdf_path") or ""})
    os.replace(temporary, path)


def checkpoint(manifest, path):
    manifest["updated_at"] = now()
    manifest["counts"] = dict(Counter(record["state"] for record in manifest["records"]))
    atomic_json(path, manifest)
    write_failures(manifest)


def acquire_record(record, run_dir, downloader):
    downloaded = downloader.acquire(record)
    content = downloaded.pop("content", None)
    record.update(downloaded)
    if content is not None:
        pdf_path = (run_dir / record["suggested_filename"]).resolve()
        with pdf_path.open("xb") as stream:
            stream.write(content)
        record["pdf_path"] = str(pdf_path)
        record.pop("reason", None)


def prepare(input_file, download_dir=None, limit=None, include_seed=False, downloader=None):
    records = load_records(input_file, include_seed)
    if limit:
        records = records[:limit]
    directory = Path(download_dir or DEFAULT_DOWNLOAD).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = directory / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    path = run_dir / "manifest.json"
    failed_csv = failure_csv_path(directory, started)
    if failed_csv.exists():
        failed_csv = run_dir / failed_csv.name
    failed_csv.touch(exist_ok=False)
    manifest = {"schema_version": "1.0", "run_id": run_id, "created_at": now(),
                "input_file": str(Path(input_file).resolve()), "download_dir": str(directory),
                "manifest_path": str(path), "failed_csv": str(failed_csv),
                "target": None, "records": records}
    checkpoint(manifest, path)
    downloader = downloader or Downloader()
    for index, record in enumerate(records):
        print(f"[{index + 1}/{len(records)}] Download: {record['title']}", file=sys.stderr)
        try:
            acquire_record(record, run_dir, downloader)
        except (DownloadError, PDFError, OSError, ValueError, KeyError) as exc:
            record.update(state="download_failed", reason=str(exc))
        checkpoint(manifest, path)
    return manifest


def retry_downloads(manifest_path, downloader=None, limit=None, failed_csv=None, dois=None):
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if failed_csv:
        destination = validate_failure_csv_path(failed_csv).resolve()
        if destination.exists():
            raise ValueError("Retry CSV already exists; choose a new output filename")
        destination.parent.mkdir(parents=True, exist_ok=True)
        manifest["failed_csv"] = str(destination)
    downloader = downloader or Downloader()
    pending = [r for r in manifest["records"] if r["state"] in {"pending", "download_failed"} and r["doi"]]
    if dois:
        wanted = {normalize_doi(doi) for doi in dois}
        if None in wanted or not wanted.issubset({r["doi"] for r in manifest["records"]}):
            raise ValueError("Retry DOI must be valid and present in the manifest")
        pending = [r for r in pending if r["doi"] in wanted]
    checkpoint(manifest, path)
    if limit:
        pending = pending[:limit]
    for record in pending:
        print(f"Retry download: {record['title']}", file=sys.stderr)
        record.setdefault("attempt_history", []).append({"at": now(), "state": record["state"],
                                                         "reason": record.get("reason"),
                                                         "attempts": record.get("attempts", [])})
        existing = path.parent / record["suggested_filename"]
        try:
            if existing.exists():
                verification = inspect_file(existing, record["title"], record["doi"])
                record.update(state="downloaded", pdf_path=str(existing.resolve()), verification=verification)
                record.pop("reason", None)
            else:
                acquire_record(record, path.parent, downloader)
        except (DownloadError, PDFError, OSError, ValueError, KeyError) as exc:
            record.update(state="download_failed", reason=str(exc))
        checkpoint(manifest, path)
    return manifest


def bind_target(manifest, client, collection):
    target = client.collection(collection)
    binding = {"server_id": client.server_id, "collection_key": target["key"], "collection_name": target["data"]["name"]}
    if manifest.get("target") and any(manifest["target"].get(key) != binding[key] for key in ("server_id", "collection_key")):
        raise ZoteroError("Run is already bound to another Zotero database/collection; do not redirect its attachments")
    manifest["target"] = binding
    return target["key"]


def archive(manifest_path, client, collection=None):
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not collection:
        collection = (manifest.get("target") or {}).get("collection_key")
    if not collection:
        raise ZoteroError("Specify the destination collection for this run")
    collection_key = bind_target(manifest, client, collection)
    checkpoint(manifest, path)
    for record in manifest["records"]:
        if not record.get("pdf_path"):
            continue
        # Persist generated keys before writes so an interrupted request can be reconciled.
        if not record.get("item_key"):
            record["item_key"] = new_key()
            checkpoint(manifest, path)
        try:
            verification = inspect_file(record["pdf_path"],
                                        ((record.get("metadata") or {}).get("title") or [record["title"]])[0], record["doi"],
                                        record.get("manual_mapping", False))
            record["pdf_path"] = str(Path(record["pdf_path"]).resolve())
            record["item_key"] = client.ensure_paper(record, collection_key)
            checkpoint(manifest, path)
            if record.get("pdf_path"):
                attachment = client.attach_pdf(record["item_key"], record["pdf_path"], record,
                                               lambda: checkpoint(manifest, path))
                record.update(state="attached", attachment_key=attachment["key"],
                              zotero_pdf_path=attachment["path"], verification=verification)
                record.pop("reason", None)
            checkpoint(manifest, path)
        except AuthorizationRequired:
            checkpoint(manifest, path)
            raise
        except (ZoteroError, PDFError, OSError) as exc:
            record.update(reason=str(exc))
            if record.get("pdf_path"):
                record["state"] = "attachment_failed"
            checkpoint(manifest, path)
    return manifest


def manual_import(manifest_path, client, pdf_dir=None, mapping_file=None, collection=None):
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    directory = Path(pdf_dir or manifest.get("download_dir") or DEFAULT_DOWNLOAD).resolve()
    if not directory.is_dir():
        raise ValueError("Manual PDF directory does not exist")
    mappings = {}
    if mapping_file:
        with Path(mapping_file).open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                identity = row.get("id") or normalize_doi(row.get("doi"))
                if not identity or not row.get("file"):
                    raise ValueError("Mapping CSV needs doi (or id) and file columns")
                if identity in mappings:
                    raise ValueError("Duplicate identity in mapping CSV")
                mapped_path = (directory / row["file"]).resolve()
                if not mapped_path.is_relative_to(directory):
                    raise ValueError("Mapping PDF must stay within the selected manual directory")
                mappings[identity] = mapped_path
    files = sorted(p for p in directory.glob("*.pdf") if p.is_file())
    used = {Path(record["pdf_path"]).resolve() for record in manifest["records"]
            if record["state"] == "attached" and record.get("pdf_path")}
    report = {"directory": str(directory), "matched": [], "unmatched": [], "rejected": []}
    for record in manifest["records"]:
        if record["state"] == "attached":
            continue
        explicit = mappings.get(record["id"]) or mappings.get(record["doi"])
        candidates = [explicit] if explicit else [p for p in files if p.name == record["suggested_filename"] or
                                                  canonical(p.stem) == canonical(record["title"])]
        if not candidates:
            # Extract identity from the PDF itself if filenames carry no useful identity.
            for candidate in files:
                try:
                    inspect_file(candidate, record["title"], record["doi"])
                    candidates.append(candidate)
                except (PDFError, OSError):
                    pass
        if len(candidates) != 1:
            if candidates:
                report["rejected"].append({"title": record["title"], "reason": "Multiple PDFs match; provide an explicit mapping CSV"})
            continue
        candidate = candidates[0]
        if candidate in used:
            report["rejected"].append({"title": record["title"], "reason": "The same PDF was matched to multiple records"})
            continue
        try:
            verification = inspect_file(candidate, record["title"], record["doi"], bool(explicit))
        except (PDFError, OSError) as exc:
            report["rejected"].append({"file": str(candidate), "title": record["title"], "reason": str(exc)})
            continue
        used.add(candidate)
        record.update(pdf_path=str(candidate), state="downloaded", verification=verification,
                      manual_mapping=bool(explicit), source_kind="manual")
        record.pop("reason", None)
        report["matched"].append({"title": record["title"], "doi": record["doi"], "file": str(candidate)})
    report["unmatched"] = [str(p) for p in files if p not in used]
    manifest["manual_import"] = report
    checkpoint(manifest, path)
    return archive(path, client, collection)
