# Browser workflow

The project CLI requires Python 3.10+ and an available `browser-act` executable.
It uses the current CLI's selectors and JSON output; no Python package is required.
Run `browser-act --help` if your installed CLI differs. BrowserAct transport must
be connected to a working browser. Session names and browser IDs are separate.

```powershell
browser-act --format json browser list
python rr/scripts/researchrabbit.py open --browser-id <existing-browser-id>
# Complete login manually if prompted, then:
python rr/scripts/researchrabbit.py doctor
python rr/scripts/researchrabbit.py --output rr/artifacts/search.json --evidence-dir rr/artifacts/search search "spacecraft pose control"
python rr/scripts/researchrabbit.py --output rr/artifacts/similar.json --evidence-dir rr/artifacts/similar expand "10.1016/j.ast.2025.111515" --relation similar
python rr/scripts/researchrabbit.py --output rr/artifacts/refs.json --evidence-dir rr/artifacts/refs expand "10.1016/j.ast.2025.111515" --relation references
python rr/scripts/researchrabbit.py --output rr/artifacts/citations.json --evidence-dir rr/artifacts/citations expand "10.1016/j.ast.2025.111515" --relation citations
```

Global options precede the command. Use `--session NAME` consistently when reusing
an existing session. Give each run a new output filename and evidence directory;
the CLI does not overwrite existing evidence. `--max-pages N` bounds pagination.
Exit codes: 0 successful/confirmed empty, 2 partial coverage, 1 access or execution
failure. Errors also produce JSON. `doctor` checks the current page and session;
it does not prove searches or graph expansion work.

## Observed controls

- Home search: `input[name="query"]`, its enclosing form's submit button.
- A DOI hit can open the article inspector directly, without a results list.
- Result title: `ListItemArticleDetails__Title-` class prefix; click the associated
  details button. Selection ticks are different buttons and may affect auto-save.
- Inspector: `InspectorStyles__Content-`; title `ArticleTitle__Title-`, nickname
  `ArticleDetailsDisplay__Nickname-`, DOI in the abstract region or DOI link.
- Related controls: `ExploreFurtherButton__StyledButton-`. `Similar` is textual;
  narrow windows show backward/forward arrows for Refs/Cited By. The CLI recognizes
  observed arrow paths and validates the resulting view before capture.
- Lists may contain repeated titles. Preserve raw count separately from unique
  count; DOI conflicts must not be silently merged.
- The footer reports `1 - 20 of 47` (possibly on separate lines). Pager controls
  should be identified from current DOM, not hard-coded accessibility indexes.

Generated class suffixes and accessibility indexes change. The parser recognizes
component-name prefixes, not generated hashes. If selectors change, inspect the
current DOM and revise the adapter; record the failure as `dom_changed`.

## Offline replay

Replay accepts HTML files and BrowserAct JSON (`html`, string-array `result`, or
snapshot-object `result`). Saved evidence is labeled `saved_html` and is not a
new live ResearchRabbit consultation. Without a saved footer, coverage is unknown.

```powershell
python rr/scripts/researchrabbit.py --output rr/artifacts/replay.json replay rr/artifacts/similar/page-001.json rr/artifacts/similar/page-002.json --relation similar
```

## Browser-tool alternative

When the environment exposes browser tools instead of BrowserAct, open the app,
inspect fresh page state, search, verify the seed, open the requested relationship,
and inspect every requested page. Save only the relevant result-list/inspector DOM,
page URL, view, and capture time. Pass these snapshots to `replay`. Keep login,
CAPTCHA, and browser transport failures distinct from empty searches.
