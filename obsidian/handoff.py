"""Verify stage-two attachments and prepare a read-only ResearchVault handoff."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from rr.extract import normalize_doi


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def segment(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")[:100]
    if not value:
        raise ValueError("Collection name cannot produce an empty path segment")
    if value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        value = "_" + value
    return value


def existing_notes(vault: Path) -> dict[str, list[str]]:
    """Read Note identities only; do not scan the Fulltext corpus."""
    result: dict[str, list[str]] = {}
    for path in sorted((vault / "02vault").rglob("*.md")):
        with path.open(encoding="utf-8-sig") as stream:
            header = stream.read(32768)
        front = re.match(r"\A---\s*\n(.*?)\n---(?:\s|$)", header, re.S)
        if not front:
            continue
        match = re.search(r"(?m)^zotero_key:\s*[\"']?([A-Z0-9]{8})[\"']?\s*$", front[1])
        if match:
            result.setdefault(match[1], []).append(path.relative_to(vault).as_posix())
    return result


def prepare_handoff(manifest_path: Path, vault_root: Path, fetch_metadata, limit: int | None = None) -> dict:
    """No Zotero/Vault writes: an 'attached' checkpoint is rechecked against storage."""
    manifest_path = manifest_path.expanduser().resolve()
    vault = vault_root.expanduser().resolve()
    if not vault.is_dir():
        raise ValueError("Vault does not exist; initialize a chosen Vault explicitly first")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    target = manifest.get("target")
    if not isinstance(target, dict) or not target.get("collection_name") or not target.get("server_id"):
        raise ValueError("Manifest is not bound to a Zotero database and collection")
    collection = segment(target["collection_name"])
    notes = existing_notes(vault)
    ready, blocked, pending, deferred = [], [], [], []
    seen: dict[str, str] = {}
    selected = 0
    for record in manifest.get("records", []):
        if record.get("state") != "attached":
            pending.append({"id": record.get("id"), "title": record.get("title"), "state": record.get("state")})
            continue
        if limit is not None and selected >= limit:
            deferred.append({"id": record.get("id"), "title": record.get("title"), "reason": "outside requested limit"})
            continue
        selected += 1
        key, pdf_key = record.get("item_key"), record.get("attachment_key")
        try:
            if not re.fullmatch(r"[A-Z0-9]{8}", key or "") or not re.fullmatch(r"[A-Z0-9]{8}", pdf_key or ""):
                raise ValueError("Missing or invalid Zotero parent/attachment key")
            if key in seen:
                raise ValueError("Repeated parent item in manifest; review duplicate attachment selection")
            seen[key] = pdf_key
            metadata = fetch_metadata(key)
            if metadata.get("zotero_key") != key:
                raise ValueError("Fetched parent identity differs from the manifest")
            expected_doi = normalize_doi(record.get("doi"))
            if expected_doi and normalize_doi(metadata.get("doi")) != expected_doi:
                raise ValueError("Current parent DOI differs from the verified checkpoint")
            attachments = [pdf for pdf in metadata.get("pdf_attachments", []) if pdf.get("pdf_key") == pdf_key]
            if len(attachments) != 1 or not attachments[0].get("pdf_path"):
                raise ValueError("Selected PDF attachment is missing or ambiguous")
            pdf = Path(attachments[0]["pdf_path"]).resolve()
            if not pdf.is_file():
                raise ValueError("Selected stored PDF does not exist")
            expected_hash = record.get("verification", {}).get("sha256")
            if not expected_hash or digest(pdf) != expected_hash:
                raise ValueError("Stored PDF hash differs from the verified checkpoint")
            matches = notes.get(key, [])
            if len(matches) > 1:
                raise ValueError("Multiple existing Analytical Notes share this Zotero identity")
            note = matches[0] if matches else f"02vault/{collection}/{key}.md"
            fulltext = f"03fulltext/{collection}/{key}.md"
            if matches:
                with (vault / note).open(encoding="utf-8-sig") as stream:
                    text = stream.read(32768)
                front = re.match(r"\A---\s*\n(.*?)\n---(?:\s|$)", text, re.S)
                match = re.search(r"(?m)^fulltext_path:\s*(.+?)\s*$", front[1]) if front else None
                if match:
                    fulltext = match[1].strip("\"'")
                    resolved = (vault / fulltext).resolve()
                    if not resolved.is_relative_to(vault):
                        raise ValueError("Existing Note points outside the chosen Vault")
                    fulltext = resolved.relative_to(vault).as_posix()
            ready.append({"zotero_key": key, "pdf_key": pdf_key, "title": metadata.get("title") or record.get("title"),
                          "doi": expected_doi, "collection": target["collection_name"], "pdf_path": str(pdf),
                          "source_sha256": expected_hash, "zotero_item": f"zotero://select/library/items/{key}",
                          "zotero_pdf": f"zotero://open-pdf/library/items/{pdf_key}",
                          "note_path": note, "fulltext_path": fulltext,
                          "note_exists": (vault / note).is_file(), "fulltext_exists": (vault / fulltext).is_file(),
                          "workflow_mode": "NORMAL_INGEST", "state": "ready_for_agent",
                          "next_skill": "research-vault-ingest-orchestrator"})
        except (OSError, ValueError, RuntimeError) as exc:
            blocked.append({"id": record.get("id"), "zotero_key": key, "pdf_key": pdf_key,
                            "title": record.get("title"), "reason": str(exc)})
    return {"schema_version": "1.0", "stage": "obsidian", "prepared_at": datetime.now(timezone.utc).isoformat(),
            "status": "partial" if ready and blocked else "blocked" if blocked else "ready" if ready else "empty",
            "source_manifest": str(manifest_path), "source_manifest_sha256": digest(manifest_path),
            "source_target": target, "vault_root": str(vault), "papers": ready, "blocked": blocked,
            "pending_zotero": pending, "deferred": deferred,
            "counts": {"ready": len(ready), "blocked": len(blocked), "pending_zotero": len(pending), "deferred": len(deferred)},
            "scope": "Identity-verified handoff only; no PDF conversion, analytical reading, Note or Knowledge writes performed."}


def save_new(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
