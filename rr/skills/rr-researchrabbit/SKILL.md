---
name: rr-researchrabbit
description: Search ResearchRabbit by keywords, title, or DOI and expand verified seed papers through Similar, Refs, and Cited By. Capture traceable discovery results for AutoResearch. Use for ResearchRabbit literature searches and citation snowballing, not PDF reading or Zotero library writes.
---

# RR ResearchRabbit

Operate the ResearchRabbit stage of AutoResearch. Adapted from
ResearchPilot-Skills `thesis-researchrabbit-expand` (MIT); see the project
`THIRD_PARTY_NOTICES.md`. Run commands from the project root.

## Search and expand

1. Read [references/browser-workflow.md](references/browser-workflow.md) for session
   setup, current page controls, and command examples. Prefer an existing logged-in
   ResearchRabbit session. Reuse the user's browser choice where specified.
2. Search keywords to discover candidates; search an exact title or DOI to locate
   a seed. An accepted seed has decision `keep` or `maybe`; do not expand a rejected
   seed. Verify the DOI/title in the inspector before expansion. If ambiguous,
   present the candidates or use an exact title supplied by the user.
3. Expand through `similar`, `references` (backward), or `citations` (forward).
   Use the project CLI for deterministic capture when BrowserAct is available.
   Otherwise perform the same sequence using the available browser tool and save
   DOM evidence for `replay`. Do not replace ResearchRabbit evidence with results
   from another platform under the same platform label.
4. Capture all requested pages within `--max-pages`. Read `coverage` and `status`;
   an incomplete view is `partial`, never a completed empty bibliography. Preserve
   missing values, RR year, displayed author labels, and duplicate audit records.
5. Read [references/quality-check.md](references/quality-check.md) before reporting
   results. Classify scholarly relevance separately from the observed graph link.
   Base author groups or clusters on displayed evidence; otherwise leave empty.

## Access and account state

Manual login remains necessary when the browser session is unauthenticated.
Report `login_required`, `blocked`, or browser errors accurately and keep already
captured evidence. Ask the user to complete login/CAPTCHA when needed; do not store
passwords or tokens in project files. Search forms and graph navigation are part
of the requested search. Add papers, change collections, enable auto-save, upload
private files, or change account settings only when that action is authorized by
the user's request. Reuse existing authorization instead of asking repeatedly.

## Handoff

Return the JSON result and evidence location, together with the query, seed,
relationship, raw/unique counts, and coverage. The canonical fields are defined
in `rr/schemas/rr-result.schema.json`. `decision` uses `keep`, `maybe`, or `reject`;
`relationship_type` uses `direct_continuation`, `adjacent_method`, `background`,
`out_of_scope`, or null pending assessment.

The RR stage discovers metadata and links. PDF retrieval, Zotero import, and
Obsidian analytical notes belong to later workflow stages. Do not report those
stages completed because an RR result file exists.
