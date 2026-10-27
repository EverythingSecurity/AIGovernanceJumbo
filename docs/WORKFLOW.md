# Governance workflow: scoping and control management lifecycle

`aicontrols workflow` runs a six-stage lifecycle on top of your scope file, following the
"Scoping and Control Management Layer" specification (v2.0.0). The stage definitions, roles and
actions are read from
[`src/aicontrols/workflow_spec.json`](../src/aicontrols/workflow_spec.json), which is that
specification's configuration JSON unchanged.

It is a planning and evidence-tracking aid for a team. It is **not** an attestation of
compliance and it is not a replacement for a GRC platform. Read [What it is not](#what-it-is-not)
before relying on it.

```
FRAMEWORK_SCOPING -> CONTROL_HARMONIZATION -> CONTROL_TAILORING ->
CONTINUOUS_MONITORING -> EXCEPTION_GOVERNANCE -> TARGET_GAP_ANALYSIS  (then a new cycle)
```

State lives in the same private scope file as your scoping decisions (see
[SCOPING.md](SCOPING.md)), under `workflow` and `audit`. Keep that file private.

## Quick start

```bash
aicontrols scope init --org "Acme"
aicontrols scope wizard --answers answers.json --create support-chatbot --name "Support chatbot"

aicontrols workflow init --by alice            # enable the workflow for the system
aicontrols workflow status                     # where you are, what is open
```

Every command that changes something records **who** did it (`--by`, or `$AICONTROLS_ACTOR`,
or your login name) in the audit trail. `--role` and `-s <system>` work as in `scope`.

## The six stages

| # | Stage | Role | What you do | Commands |
|---|---|---|---|---|
| 1 | Framework scoping and profile | Scoping/compliance lead | Define the boundary, rationalise non-applicable obligations, set risk appetite and the target profile | `workflow profile`, `workflow target`, `scope set --applicable no`, `workflow attest` |
| 2 | Control harmonisation | Compliance architect | Map framework controls onto **common controls** ("test once, satisfy many"); find unmapped controls | `workflow cc suggest/add/map/gaps/gap-accept`, `workflow attest` |
| 3 | Tailoring and ownership | First-line control owner | Write implementation statements and parameters; assign owner, reviewer, frequency, evidence and test rule | `workflow cc set`, `workflow tailor` |
| 4 | Continuous monitoring | CCM engine | Ingest test results; score effectiveness; check KCI/KRI thresholds | `workflow indicator add`, `workflow ingest`, `workflow ccm evaluate` |
| 5 | Exception governance | Second-line risk manager | Request, assess, approve (time-boxed) and re-assess exceptions | `workflow exception request/assess/approve/reject/reopen/review` |
| 6 | Assurance and gap analysis | Third-line auditor | Compare with the target profile, produce a POA&M, verify the audit trail, report | `workflow gap`, `workflow poam`, `workflow audit verify`, `workflow report` |

Each stage has **actions**. Two kinds:

- **Evidence actions** are satisfied by what is in the file (for example, "every common control
  has an owner, a different reviewer and a frequency"). They cannot be ticked by hand.
- **Attestations** are things only a person can confirm (for example, "I reviewed the
  not-applicable decisions"). Use `workflow attest <ACTION>`.

`workflow advance` moves to the next stage only when every action of the current stage is
satisfied. `--force --reason "..."` overrides this; the reason and the open actions are written
to the audit trail. After stage 6, `advance` completes the cycle and `workflow restart` starts
the next one. Mappings, tailoring, results and exceptions carry over; the checklist resets.

## Common controls (the harmonisation layer)

A common control is one internal control you test once. Many framework controls map to it.

```bash
aicontrols workflow cc suggest              # propose one per domain, from the dataset's crosswalk
aicontrols workflow cc suggest --apply      # create them and map the controls
aicontrols workflow cc add "Incident response" --domain incident
aicontrols workflow cc map CC-001 gdpr:Art.33 iso-27001:A.5.26
aicontrols workflow cc gaps                 # applicable controls with no common control
aicontrols workflow cc gap-accept gdpr:Art.4 --reason "Definitions only; no action"
```

The suggestions mirror the dataset's domains. They are a starting point for the architect, not a
finding that the controls are equivalent. Marking a common control effective **never** changes the
status of the controls mapped to it; it is shown beside them, and the gap analysis flags controls
marked done whose common control is not demonstrably effective.

## Tailoring

```bash
aicontrols workflow cc set CC-001 --owner Dana --reviewer Eli --frequency monthly \
  --implementation "Runbook v2 with a 72-hour notification step" \
  --evidence "Notification log extract" --test-type automated \
  --test-description "Nightly query for incidents without a notification record" \
  --param window=72h
aicontrols workflow tailor gdpr:Art.33 --implementation "Notify via the DPO mailbox"
```

Frequencies: daily, weekly, monthly, quarterly, annual. Test types: manual, automated, rcsa
(self-assessment questionnaire). The owner and reviewer must be different people.

## Continuous monitoring

There are no connectors to cloud, IAM or CI systems. Instead the layer defines a **file contract**
that your own scripts can produce, one JSON object per result (a JSON array or JSON lines file):

```json
{"control": "CC-001", "at": "2026-10-26T10:00:00Z", "result": "pass",
 "metrics": {"failed_logins": 3}, "source": "iam-export", "evidence": "s3://bucket/run-123"}
```

`result` is `pass`, `fail` or `error` (errors count as failures). Duplicates (same control,
time and source) are ignored.

```bash
aicontrols workflow indicator add CC-001 --kind KRI --name "Failed logins" \
  --metric failed_logins --op ">" --value 5        # breach when the metric is > 5
aicontrols workflow ingest results.jsonl
aicontrols workflow ccm evaluate
aicontrols workflow ccm escalations
aicontrols workflow ccm ack <key> --note "Investigating"
```

**Effectiveness** of a common control is the pass rate over its last 5 results (policy
`effectiveness_window`): *effective* at 90% or more, *partially effective* at 60% or more,
otherwise *ineffective*; *stale* if the latest result is older than 1.5 times its frequency;
*not tested* if there are none. A breached indicator is recorded once as an **escalation** (and in
the audit trail) until you acknowledge it. Nothing is emailed or paged: the layer records and
reports.

## Exceptions

```bash
aicontrols workflow exception request --control gdpr:Art.33 --reason "Legacy system" \
  --compensating "Weekly manual review" --by alice
aicontrols workflow exception assess EX-001 --likelihood 3 --impact 3 --by bob
aicontrols workflow exception approve EX-001 --role EXECUTIVE_APPROVER --days 90 --by carol
aicontrols workflow exception review            # expired, expiring soon, or waiting
aicontrols workflow exception reopen EX-001 --reason "Still needed" --by alice
```

Likelihood times impact gives a rating: low (1-4), medium (5-9), high (10-16), critical (17-25).
From **medium** upward an executive must sign off; the second line can approve **low**. Approvals
are time-boxed by rating (defaults: 365, 180, 90 and 30 days) and cannot exceed the cap. An
approved exception shows as *active*, then *expiring* (within 14 days), then *expired*, at which
point the gap re-appears flagged and the stage gate blocks until it is reopened and re-assessed.

Policy is changeable (and every change is audited): `aicontrols workflow policy
exception_max_days.high=60`, `executive_approval_from=high`, `reassess_warning_days=30`,
`separation_of_duties=false`.

## Gap analysis, POA&M and reporting

```bash
aicontrols workflow target --status verified --domain incident --by-date 2026-12-31
aicontrols workflow gap              # at target vs not; open / overdue / excepted
aicontrols workflow poam -o poam.csv
aicontrols workflow report -o report.md
aicontrols workflow report --format json
```

Each control's **current profile** is its status; its **target profile** is `implemented` unless
you set `verified` or a date. Gaps are *open*, *overdue* (past the target date) or *excepted*
(covered by an active exception).

## Audit trail

Every change is appended to a hash-chained log (each event includes the previous event's hash).

```bash
aicontrols workflow audit show -n 20
aicontrols workflow audit verify      # recompute the chain; non-zero exit if it was edited
aicontrols workflow audit export -o audit.jsonl
```

`scope validate` also verifies the chain. After `audit verify`, record the printed **head hash**
somewhere outside the file (a ticket, a signed commit); that is what makes later rewriting of the
whole history detectable.

## In the browser

The **My scope** tab of the web explorer has a **Workflow** view with the same six stages: a stage
tracker, the gate checklist with *Attest* and *Advance* (and *Force* with a reason), and a panel per
stage for the profile and targets, common controls, tailoring, monitoring (paste or choose a results
file, indicators, *Evaluate now*, escalations), exceptions (request, assess, sign off, reject,
reopen, close), and assurance (gap analysis, POA&M, report, audit trail with *Verify chain*).

- It runs entirely in your browser and nothing is uploaded. The scope is stored in this browser's
  local storage; download your scope file to keep or share it.
- It reads and writes the same file as the command line. The browser engine
  ([`site/workflow.js`](../site/workflow.js)) is checked against the Python one by running the same
  long scenario through both and comparing the results and the resulting file, **hash chain
  included**, so an audit trail written in one verifies in the other.
- Enter who is acting in **Acting as**. It is recorded with every change and stored in this browser.

## What it is not

Honesty about the limits matters more here than in the other layers.

- **Roles are labels.** Nothing authenticates `--by` or `--role`. Separation of duties (requester
  versus assessor versus approver, owner versus reviewer) is checked by name, so it catches honest
  mistakes and not a determined person using two names. A platform with real identity is needed to
  enforce it.
- **The audit trail is tamper-evident, not immutable.** Anyone who can write the file can rewrite
  the whole chain. Version control and an externally recorded head hash raise the cost of that;
  they do not remove it.
- **No live integrations.** There are no connectors to ERP, cloud, IAM or CI/CD systems, and no
  process-mining verification of event logs. Results arrive through the file contract above.
- **No notifications.** Escalations and expiries are recorded and reported, not delivered.
- **Dashboards are generated reports** (Markdown or JSON), not a live role-based web view.
- **The browser is not a multi-user system.** The **Workflow** view runs entirely in your browser
  on a local copy of the file. Two people cannot work in it at once; share the downloaded file
  instead, and treat its audit trail as the record.
- **Planning aid, not compliance advice.** Effectiveness scores and gaps are only as good as the
  results and decisions entered.
