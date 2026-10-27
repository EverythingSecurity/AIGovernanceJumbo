# Changelog

## 0.7.0 - 2026-10-27

- **Spreadsheet template and import.** A fill-in CSV (one row per control; decision, justification, status, owner,
  due date, evidence, notes) that can be downloaded from the **My scope** welcome card, from **Export** (pre-filled),
  or with `aicontrols scope template`, and imported with **Import a scope file or spreadsheet** or
  `aicontrols scope import-csv`. Import is all-or-nothing and reports every problem by row; blank cells leave values
  unchanged; a system that does not exist yet is created from the file.
- The columns are those of the Statement of Applicability export, so an exported SoA can be edited and imported back.
  Semicolon-separated CSV and a UTF-8 BOM are understood; the apostrophe added against spreadsheet formulas is removed on import.
- `src/aicontrols/spreadsheet.py` and the matching code in `site/scope.js` are compared by `tests/test_spreadsheet.py`
  (template text byte for byte, the CSV parser on tricky inputs, and 17 import cases including broken files).

## 0.6.0 - 2026-10-27

- **Governance workflow in the browser:** a **Workflow** view in the My scope tab with a stage tracker, gate
  checklist (attest, advance, force with a reason) and a panel for each of the six stages: profile and
  targets, common controls, tailoring, monitoring (ingest, indicators, evaluate, escalations), exceptions
  (request, assess, sign off, reject, reopen, close), and assurance (gap analysis, POA&M, report, audit trail).
  Local only; the file is the same one the command line uses.
- The browser engine (`site/workflow.js`) is a port of the Python one, with a synchronous SHA-256 so the audit
  hash chain verifies identically in both. `tests/test_workflow_parity.py` runs one long scenario (successes and
  deliberate errors) through both engines and compares every result and the final file, hash chain included.
- Audit events carry no floating-point numbers, so hashes are identical across languages.
- Fixes: a rejected policy change (for example an invalid threshold) is now rolled back instead of staying stored;
  non-finite policy numbers are rejected; common-control ids must start with a letter; sub-second timestamps are
  normalised the same way in both engines; deleting a system in the browser also removes its workflow state.

## 0.5.0 - 2026-10-27

- **Governance workflow layer** (`aicontrols workflow`), implementing the six-stage Scoping and Control
  Management Layer specification v2.0.0 (stage model read from `src/aicontrols/workflow_spec.json`):
  framework scoping and profile, control harmonisation into common controls, tailoring and ownership,
  continuous monitoring, exception governance, and gap analysis. See `docs/WORKFLOW.md`.
- Stage gates: each stage has evidence-based actions (satisfied by data in the file) and attestations
  (confirmed by a person); `advance` is blocked until they pass, and `--force` needs a recorded reason.
- Common controls: `cc suggest/add/map/gaps/gap-accept` map many framework controls to one tested control.
- Tailoring: owner, reviewer, frequency, implementation statement, parameters, evidence and test rules.
- Monitoring: a file contract for ingesting test results and metrics, KCI/KRI thresholds with recorded
  escalations, and effectiveness scoring (effective / partially effective / ineffective / stale / not tested).
- Exceptions: request, risk assessment, rating-based executive sign-off, time-boxed approval, expiry and re-assessment.
- Gap analysis against a per-control target profile, a POA&M CSV, and a Markdown/JSON governance report.
- Hash-chained audit trail (`workflow audit verify`), checked by `scope validate`. Tamper-evident, not immutable.
- Separation of duties is checked by actor name (requester, assessor, approver; owner and reviewer).
- Scope file format `1.1` carries the workflow state; `1.0` files keep working. The browser's **My scope**
  tab accepts 1.1 files and preserves the workflow sections.

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
