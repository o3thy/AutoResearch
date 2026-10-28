# AutoResearch

For ResearchRabbit tasks, read `rr/skills/rr-researchrabbit/SKILL.md` and use
`rr/scripts/researchrabbit.py` from this project root. Keep discovery evidence and
verified bibliographic metadata distinct. Do not mark an incomplete capture as
successful, and preserve existing evidence rather than overwriting it.

For PDF downloads and Zotero attachment tasks, read
`zotero/skills/rr-zotero-download/SKILL.md` and use `.venv/Scripts/python` with
`zotero/scripts/zotero_workflow.py`. Never automate the user's mouse or Zotero's
authorization dialog. Use the explicitly chosen collection and preserve pending
manifests for manual PDF completion.

For third-stage reading, archiving, Knowledge updates or Vault retrieval, use
the integrated Skills under `obsidian/skills/`. Read
`obsidian/skills/research-vault-ingest-orchestrator/SKILL.md` for specified paper
ingestion, `obsidian/skills/zotero-collection-manager/SKILL.md` for an explicitly
requested batch, or the relevant specialist Skill. Treat `obsidian/` as the
upstream repository root when resolving its `tools/`, `templates/` and Skill
references. Use `obsidian/scripts/obsidian_workflow.py` from this project root
for environment checks, stage-two handoff, read-only fetches and validation.
Use the explicit Vault or the module's local config; do not fall back to a
different global checkout's private configuration. A ready handoff is not a
completed analysis. Preserve Note-first retrieval, source evidence and reading
states. Do not process unrelated papers or rewrite an existing Vault merely
because the project has been integrated.

Keep stage-specific code, scripts, skills, schemas, tests, docs, and artifacts
under `rr/`, `zotero/`, or `obsidian/`. Run documented
commands from this project root. The root `schemas/paper.schema.json`,
`scripts/validate_results.py`, development dependencies, and `.venv/` are shared.
Zotero authorization is stored in `zotero/.local/`. Preserve existing evidence;
test artifacts explicitly removed by the user are not expected to remain available.

Run `.venv/Scripts/python -m unittest discover -s . -v` after workflow/code
changes. Browser commands mutate the current search view; do not run concurrent
browser tests against the same session. Use a new output/evidence path per run.
