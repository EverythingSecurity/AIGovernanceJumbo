# Client engagement layer (scoping, roles and framework questionnaires)

For a consulting team (the "principal") that onboards client companies and needs to work out which frameworks apply to each. It runs as `aicontrols engagement` and as the **Client engagement** screen in the browser (My scope tab, "Start a client engagement", or the **Engagement** view of a scope workspace). Command line and browser give identical results; tests compare them step by step.

**One scope file per client.** The engagement is stored in the client's scope file, so it travels with the rest of that client's work. Nothing is uploaded.

## What it is, and is not

This is an *offline* layer. The principal and the client pass the file back and forth. There are **no accounts, no logins, no tenant isolation, no file uploads, no notifications**. Names and roles are labels you type; nothing authenticates them, so "the assessor who scores is not the one who signs off" can only be checked by name. The audit trail is tamper-evident, not immutable. If you need real multi-user access control, that needs a server and is not built here. See `docs/ENGAGEMENT_LAYER_PLAN.md` for the reasoning.

## The flow

1. **Client**: record the profile (name, sector, country, size, contributor), then mark the client onboarded.
2. **Scoping questionnaire**: 25 questions in eight domains (jurisdiction, sector, regulated status, data, AI use, technology and third parties, certifications, size and maturity). Questions can be delegated to a department or person with a due date. The contributor submits the final set, which **locks** it. Reopening needs a reason and clears everything downstream.
3. **Recommendations**: a rules engine turns the answers into framework recommendations. Each one carries a confidence, the rules that fired, the answers that triggered it and a plain-language rationale. The same answers and rules always give the same result.
4. **Review and assignment**: a reviewer accepts or removes each recommendation and can add others. **Removing or adding needs a written justification.** Every recommendation must be reviewed before the set is finalised. Finalising records the approver and the rules version.

5. **Framework questionnaires**: finalising creates one questionnaire per applicable framework, with **one question per control** from the library, grouped by domain. Hand a whole questionnaire, or one domain, to a client collaborator with a due date. They answer (implemented, partially implemented, not implemented, not applicable, with a justification for the last), attach evidence references (document titles or links), and submit the domain for review. A reviewer approves or returns it with a note. When every answer is approved the client contributor submits the questionnaire, which **locks** it; only an assessor or admin can return it. "Also apply to the same domain in other frameworks" copies an answer to related questions in the other questionnaires, where the answerer is allowed to answer.

Every step is recorded in the hash-chained audit trail (as the "(organisation)" system, role `ENGAGEMENT_OFFICE`).

## Roles

| Role | What they can do |
|---|---|
| **Engagement admin** | Everything, including the client profile, rules and roles. |
| **Scoping lead** | The scoping questionnaire, recommending, reviewing and finalising frameworks, assigning each framework's questionnaire to client collaborators, reopening scoping or the framework set. Cannot change rules, the client profile or roles, and cannot answer framework questions. |
| **Assessor** | Reviews recommendations and submitted answers; can return a submitted questionnaire. Cannot assign frameworks. |
| **Client contributor** | Completes scoping, delegates, assigns and answers questionnaires, reviews and submits. The name on the client profile counts as a contributor. |
| **Client collaborator** | Answers only the scoping questions and framework domains assigned to them. |

The permission table is data (`roles` and `actions` in `engagement_spec.json`).

**How it is enforced.** Roles are checked by name. Until someone is given a role, anyone can do anything (so existing files keep working). The first role you set must be `admin`; from then on an action is refused unless the name in "Acting as" holds a role that allows it, and only an admin can change roles. Names match regardless of case. **This guards against mistakes, not against deliberate misuse: there are no logins, so anyone can type another person's name.** A refused action is not written to the audit trail, because nothing is saved when an action fails.

## Rules are data

The questionnaire and the seed rules live in `src/aicontrols/engagement_spec.json` (the browser copy is generated: `python tools/build_site_spec.py`). A client file can also carry its own rules:

```json
{"id": "R-OUTSOURCE", "framework": "iso-27001", "confidence": "low", "weight": 10,
 "rationale": "Outsources ICT.",
 "when": {"all": [{"q": "t_outsourcing", "op": "is", "value": "yes"},
                  {"not": {"q": "o_size", "op": "in", "value": ["micro"]}}]}}
```

Conditions use `all`, `any`, `not` and `{q, op, value}` where `op` is `is` (single answer equals), `has` (multi-choice contains) or `in` (answer is one of a list). An unanswered question never matches. A custom rule with an existing id replaces it; any rule can be switched off. Each change raises the rules version stored with the recommendation.

When several rules point at one framework, the highest confidence wins and the weights add up (weights only order the list).

Seed rules cover DORA, GDPR, ISO 42001, NIST AI RMF, the EU AI Act, ISO 27001, any standard a contract names, and two that the library cannot satisfy today: **Qatar PDPPL** and a **data governance framework** are not in the library, so those rules are reported as *skipped* rather than dropped silently.

## Commands

```
aicontrols scope init --org "Acme Bank" --file acme.json
aicontrols engagement client set --file acme.json --by pam --name "Acme Bank" --sector banking --country Qatar --size large --contributor Dina
aicontrols engagement client onboard --file acme.json --by pam
aicontrols engagement questions --file acme.json [--unanswered]
aicontrols engagement answer d_personal yes --file acme.json --by dina      # several values for multi-choice
aicontrols engagement delegate d_volume --to "Data office" --due 2026-12-01 --file acme.json --by dina
aicontrols engagement submit --file acme.json --by dina
aicontrols engagement recommend --file acme.json --by pam [--json]
aicontrols engagement review gdpr accept --file acme.json --by assessor
aicontrols engagement review nist-ai-rmf remove --reason "Client uses ISO 42001" --file acme.json --by assessor
aicontrols engagement finalise --file acme.json --by admin --reason "Agreed with client"
aicontrols engagement status | rules list | rules set rule.json | rules disable R-27001 | reopen --reason ... | reopen-assignment --reason ...

aicontrols engagement roles set admin Ada --file acme.json --by pam        # the first role set must be admin
aicontrols engagement roles set scoping_lead Sam --file acme.json --by Ada
aicontrols engagement roles set collaborator Cleo Carl --file acme.json --by Ada
aicontrols engagement roles list --file acme.json

aicontrols engagement packages --file acme.json [owasp-llm]                # progress, by domain
aicontrols engagement package assign owasp-llm --to Cleo --due 2026-12-01 [--domain DOMAIN] --file acme.json --by Sam
aicontrols engagement package questions owasp-llm [--domain D] [--unanswered] --file acme.json
aicontrols engagement package answer owasp-llm owasp-llm:LLM01:2025 implemented --evidence "Scan report" [--comment ...] [--shared] --file acme.json --by Cleo
aicontrols engagement package submit-items owasp-llm --domain D --file acme.json --by Cleo
aicontrols engagement package review owasp-llm --domain D approve|return [--note ...] --file acme.json --by Sam
aicontrols engagement package submit owasp-llm --file acme.json --by Dina
aicontrols engagement package return owasp-llm --reason "Evidence is out of date" --file acme.json --by Ann
aicontrols engagement tasks Cleo --file acme.json
```

## Limits and not built yet

- Evidence is a **reference** (a title or link) entered by the collaborator. Nothing is uploaded, scanned or checked, and the tool cannot tell whether the document exists or is current.
- Questionnaires are not de-duplicated by an official cross-framework mapping. The library groups controls by domain, so "apply to the same domain in other frameworks" copies an answer across a domain; whether that is right for each control is the reviewer's call.
- A finalised framework set cannot be reopened once framework answers exist.
- No reminders, escalation or notifications (nothing runs in the background). Overdue items are flagged when you open the page or run `engagement packages`.
- Still to come, one phase at a time: scoring, control ratings, assessor findings (phase 4); reports and remediation (phase 5). Tenancy, logins, uploads, notifications and AI assist need a server and are out of scope for this repository.
