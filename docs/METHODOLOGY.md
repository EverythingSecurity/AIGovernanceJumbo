# Methodology and known limits

## Where the data comes from

`AI_Governance_Master_Checklist.json` is an export of the authors' workbook: one sheet
per framework plus a Master Control List and a Domain Crosswalk. `tools/build_data.py`
normalizes it into `data/controls.json`, `data/frameworks.json` and `data/domains.json`;
`tools/validate.py` checks them against `schema/`. The data files are generated: change
the source and rebuild, rather than editing them by hand.

## What each field means

- **requirement**: a condensed paraphrase written for this project. It is not the text of
  any standard, and it is not a substitute for reading one.
- **cia**: whether an item primarily protects Confidentiality, Integrity or Availability.
  An item is marked only if failing the requirement would directly expose AI assets to
  disclosure (C), unauthorized alteration (I) or loss of access (A). Privacy lawfulness
  and governance items are deliberately *not* marked. This is expert judgement for audit
  planning; adjust it to your own risk assessment.
- **domain**: the cross-framework theme a control belongs to (32 in total). Controls in
  the same domain can usually be satisfied by one programme. This is the crosswalk.
- **evidence**: what you would show to demonstrate the control is in place.
- **kind**: `control`, or `info` for rows that only identify a framework (ID, scope).
  `info` rows are excluded from lists and counts shown in the tools.

## Identifiers

A control id is `<framework_id>:<ref>`, split at the **first** colon (OWASP refs such
as `LLM01:2025` contain colons). The workbook lists ISO 27001 Annex A controls without
the `A.` prefix, which collides with clause numbers (clause 5.1 vs Annex A 5.1); the
build restores the prefix, so Annex A is `iso-27001:A.5.1` and the clause is `iso-27001:5.1`.

## Known limits

- **Domain assignment is judgement and may contain mistakes.** For example, ISO 42001
  6.1.2 (AI risk assessment) is filed under *Documentation, Records & Configuration
  Control* rather than *Risk Assessment & Treatment*, and 6.1.3 (AI risk treatment) under
  *Legal, Regulatory & Compliance Obligations*. Please open an issue when you find others.
- **Draft or evolving standards.** Some referenced standards were still in development
  when the workbook was written. `last_verified` in `data/frameworks.json` is `null`
  until a maintainer has checked a framework against its current published text.
- **No tracking state.** Applicability, status and owner are intentionally not part of the
  dataset. They belong to your organization; export a list and track it yourself.
