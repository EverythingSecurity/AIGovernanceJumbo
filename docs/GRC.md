# GRC management layer

This layer connects what a regulation or standard **requires** to the **control** that meets it, the **policy, guideline and SOP** behind that control, and the **evidence** that shows it works. It sits on top of scoping and the governance workflow and uses the same private scope file (schema 1.2). It is available as `aicontrols grc` and as the **GRC** view of the **My scope** tab. The two give identical results; tests compare them step by step.

## The chain

requirement (a control in the dataset) → clause → **policy / guideline / SOP** → **control** (a common control from the Workflow) → **evidence source** → audit finding.

- A *requirement* is a dataset control, for example `gdpr:Art.33`.
- A *control* is a workflow common control (CC). Several requirements from different frameworks can map to one CC.
- Documents and evidence sources are linked to the CC, not to each requirement.

## Quick start

```
aicontrols workflow init --file scope.json --by alice
aicontrols workflow cc suggest --file scope.json --apply --by alice
aicontrols grc init --file scope.json --by alice               # adds the standard evidence sources
aicontrols grc documents add --file scope.json --by alice --type policy --title "AI Policy" --owner CISO --status approved --approved 2026-06-01
aicontrols grc link CC-001 --file scope.json --by alice --policy DOC-001 --evidence-source EVS-001
aicontrols grc mapping-review CC-001 --file scope.json --by alice --owner "Head of SecOps"
aicontrols grc matrix --file scope.json --format csv -o matrix.csv
aicontrols grc coverage | kpis | streams | lifecycle | artifacts | report
```

## Mapping matrix

One row per applicable requirement. Status:

| Status | Meaning |
|---|---|
| Unmapped | no control and not recorded as a gap |
| Gap | recorded as an accepted gap with a reason |
| Not started | mapped, requirement not started |
| Partial | in progress, or done but the control has no current evidence |
| Implemented | done **and** the control has current evidence |

Issues listed per row: unmapped, no policy, no SOP, no evidence source, no mapping owner, no review date, review overdue.

## Coverage

Covered = implemented and evidenced. Coverage per framework is covered ÷ applicable requirements. When an anchor framework is set (default ISO 42001), each other framework also shows how many requirements are covered through a control that also serves the anchor, so you see what the anchor work already gave you.

## KPIs and KRIs

Requirements mapped (target 100%), controls with current evidence (95%), critical findings past due (0), policy review currency (100%), risks above appetite without a treatment plan (0), cross-framework coverage (information). A measure with nothing recorded shows **no data**, never a pass.

## ISO 42001 streams

Every ISO 42001 requirement is assigned to one of five streams (leadership, technology, policy, requirements, data quality) by clause pattern, most specific pattern wins. The assignment is a documented judgement, not part of the standard.

## Registers

`documents` (policy/guideline/SOP with owner, approval and review date), `risks` (by business unit and department), `findings`, `audits`, `scope_items` (an exclusion needs a justification), `evidence_sources`. Every change is recorded in the hash-chained audit trail under the system name "(organisation)".

## Lifecycle and artifacts

The ten lifecycle steps and ten artifacts are computed from your data. Nothing is ticked by hand; each unfinished step says what to do next.

## Limits

- Roles and names are labels you type; nothing authenticates them.
- The audit trail is tamper-evident, not immutable.
- "Current evidence" means the control's effectiveness is not Not tested or Stale. It does not prove the evidence is true.
- Coverage and KPIs are planning aids, not an audit opinion.
- `aicontrols grc open-items` lists six points in the source note that were unclear and how this tool treats each.
