# Changelog

## 0.4.0 - 2026-10-22

- **Scoping in the browser:** a **My scope** tab on the web explorer with the wizard, a plan by workstream, an editable controls table (applicability with justification, status, owner, due date, evidence, notes), bulk edits, and downloads of the scope file, a Statement of Applicability (CSV/Markdown) and the plan. Runs entirely client-side; state is kept in local storage and the downloaded file is compatible with the CLI.
- The browser logic (`site/wizard.js`, `site/scope.js`) is checked against the Python implementation by `tests/test_site_parity.py`.
- CSV exports (CLI and browser) neutralise cells that start with `=`, `+`, `-` or `@` so spreadsheets do not run them as formulas.
- Scope schema: `include_level` also accepts `custom`.

## 0.3.0 - 2026-10-22

- **Scoping wizard:** `aicontrols scope wizard` asks 12 plain questions about an AI system and suggests frameworks in four tiers (your answers point to these / worth considering / background / no trigger indicated), with the reason for every suggestion. Interactive, or scripted with `--answers FILE` / `--answer q=v`; `--create` adds the system to your scope file and records the answers that led to it. Regulations are only ever described as indicated by your answers, with a reminder to confirm with counsel.
- `examples/wizard-answers.json`; the worked example now shows the recorded scoping basis.

## 0.2.1 - 2026-10-22

- `scope plan --top N` and `--min-frameworks N` to focus on the few workstreams that matter first.
- `scope plan` now shows each workstream's next due date and how many open controls are overdue.
- Markdown output: `scope plan --format md` and `scope export --format md` for pasting into documents.

## 0.2.0 - 2026-10-22

- **Domain corrections:** 137 of 557 controls moved to a more appropriate domain via `tools/domain_overrides.json` (applied at build time, with a reason per group). Fixes, for example, ISO 42001 6.1.2 and 6.1.3 (risk), ISO 27090 and MITRE ATLAS items filed under HR, and GDPR/EU AI Act definitions and penalties filed under incident management.

- Scope layer: `aicontrols scope` records your own systems, per-system framework choices, applicability decisions (with justification), owners, status and evidence in a private `aicontrols-scope.json`; reports completion by framework, plans workstreams by domain, and exports a Statement-of-Applicability style CSV.
- `schema/scope.schema.json` and a worked example in `examples/`.

## 0.1.0 - 2026-10-21

- First public release: 557 controls across 18 frameworks and 32 cross-framework domains.
- Normalized dataset (`data/`) with JSON Schemas (`schema/`) and a validator.
- `aicontrols` Python package and CLI.
- Static web explorer with search, filters and a framework-by-domain coverage map.
