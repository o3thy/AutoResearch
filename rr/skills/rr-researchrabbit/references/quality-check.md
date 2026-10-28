# Quality check

Adapted from ResearchPilot-Skills ResearchRabbit quality checks.

- The selected seed is `keep` or `maybe`, and its exact DOI/title was inspected.
- Distinguish the observed link (`similar`, `references`, `citations`) from a
  scholarly relationship classification. Similar does not imply direct continuation.
- Do not invent full author lists, abstract text, DOI, citation-context judgments,
  or author clusters. List labels such as `Cai, 2025` are not full author metadata.
- Preserve ResearchRabbit's displayed year. Publisher issue dates may differ;
  record later metadata corrections separately with their source.
- Report total, raw captured rows, unique papers, pagination coverage, and any
  limit or transport failure. A complete RR list is not proof that RR indexes the
  complete publisher bibliography or every citing paper.
- Preserve raw evidence and duplicate records. Same-title papers with conflicting
  DOIs are kept separately. No fuzzy title merging is performed automatically.
- Account mutations require authorization for the intended action. Search and
  citation exploration should not toggle collection saves or auto-save.
- Saved-HTML regression results and current live results have different sources.
- The output is a discovery handoff, not a validated bibliography or PDF archive.
