---
name: rr-zotero-download
description: Download PDFs for DOI-bearing RR JSON lists into a specified Zotero collection, export unsuccessful papers to CSV, and ingest user-downloaded PDFs into their corresponding literature records. Use for the Zotero download and manual-completion stages of AutoResearch, not literature discovery or Obsidian note writing.
---

# RR Zotero Download

Run the project's `zotero/scripts/zotero_workflow.py` using `.venv/Scripts/python`.
Read [the workflow guide](../../docs/zotero-workflow.md) for commands, file locations,
authorization, and manual matching. The runtime dependency is `zotero/requirements.txt`.

## Download and archive

- The destination is a Zotero **collection**. Each paper has its own bibliographic
  item; its PDF is a child stored attachment. Resolve a unique collection key/name
  supplied by the user. Do not substitute the UI's currently selected collection.
- Read DOI-bearing `related_papers`/`papers` from the JSON. Missing or invalid DOIs
  go to the failure CSV; do not invent DOI matches. Seeds are included only with
  `--include-seed`. Default download/CSV directory is `zotero/download` in this project.
- For a batch with missing DOIs, `zotero/scripts/prepare_zotero_batch.py --resolve-dois`
  can create a separate audited input using exact Crossref title matches plus
  bibliographic corroboration. Ambiguous or fuzzy candidates remain unresolved.
  Preserve original RR evidence and apply the user's requested ordering/limit.
- Follow the DOI origin, publisher HTML PDF links and Crossref full-text links.
  Optional Unpaywall discovery requires the user's email; repository copies require
  `--allow-repositories`. Preserve the source URL and distinguish preprints.
- Validate actual PDF bytes and expected title/identity before creating a parent
  item. Write through Zotero's local API, then read back parent/file location and
  verify the stored content hash. Report attachment success only after verification.
- Zotero 10 write authorization belongs to the user. Never automate the permission
  dialog or the user's mouse. Use `authorize` or explicit `--prompt-writes` for
  manual prompts. Preserve the user's choice of one-use vs remembered authorization.

## Failure and manual completion

Report the exact failed CSV and manifest paths. The CSV includes title, DOI,
reason, state and suggested filename. Keep the manifest for retries and matching.
Name failure CSVs `YYYYMMDDHHmm下载失败列表.csv` using Beijing time (UTC+8).
Follow `zotero/download/download.md`; preserve names when updating an existing
list, and never overwrite a different batch's same-minute list.
Failures do not create placeholder Zotero items; a parent is created/reused when
a verified PDF is ready.

Wait for the user to report manual downloads are ready, then run `ingest` against
the same manifest and user-specified PDF directory (or its default download directory).
Match PDF content, suggested filename or explicit `doi/id,file` mapping. Ambiguous,
invalid or mismatching PDFs remain unimported with reasons. Do not guess by file order.
Scanned PDFs without extractable identity require explicit mapping by the user.

Copy attachments into Zotero's storage and preserve the user's source PDFs.
Reconcile existing item keys/DOIs and attachment hashes to avoid duplicate parents
and PDFs. The manifest is bound to a Zotero database and collection; do not redirect
an existing run to another destination.

## Report

Return attached count, unresolved count, collection name/key, failure CSV and
manifest paths. Distinguish real network/API verification from mocked unit tests
or a simulated manual-download test. Do not claim the user has manually downloaded
anything unless they have said so or their specified files were found and verified.
