# Client engagement layer (phase 2: scoping and applicability)

For a consulting team (the "principal") that onboards client companies and needs to work out which frameworks apply to each. It runs as `aicontrols engagement` and as the **Client engagement** screen in the browser (My scope tab, "Start a client engagement", or the **Engagement** view of a scope workspace). Command line and browser give identical results; tests compare them step by step.

**One scope file per client.** The engagement is stored in the client's scope file, so it travels with the rest of that client's work. Nothing is uploaded.

## What it is, and is not

This is an *offline* layer. The principal and the client pass the file back and forth. There are **no accounts, no logins, no tenant isolation, no file uploads, no notifications**. Names and roles are labels you type; nothing authenticates them, so "the assessor who scores is not the one who signs off" can only be checked by name. The audit trail is tamper-evident, not immutable. If you need real multi-user access control, that needs a server and is not built here. See `docs/ENGAGEMENT_LAYER_PLAN.md` for the reasoning.

## The flow

1. **Client**: record the profile (name, sector, country, size, contributor), then mark the client onboarded.
2. **Scoping questionnaire**: 25 questions in eight domains (jurisdiction, sector, regulated status, data, AI use, technology and third parties, certifications, size and maturity). Questions can be delegated to a department or person with a due date. The contributor submits the final set, which **locks** it. Reopening needs a reason and clears everything downstream.
3. **Recommendations**: a rules engine turns the answers into framework recommendations. Each one carries a confidence, the rules that fired, the answers that triggered it and a plain-language rationale. The same answers and rules always give the same result.
4. **Review and assignment**: a reviewer accepts or removes each recommendation and can add others. **Removing or adding needs a written justification.** Every recommendation must be reviewed before the set is finalised. Finalising records the approver and the rules version.

Every step is recorded in the hash-chained audit trail (as the "(organisation)" system, role `ENGAGEMENT_OFFICE`).

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
```

## Not built yet

This release is phase 2 of `CLIENT_COMPLIANCE_LAYER.md`. Still to come, one phase at a time: assessment packages and evidence references (phase 3), scoring, ratings, findings (phase 4), reports and remediation (phase 5). Tenancy, authentication, uploads, notifications and AI assist need a server and are out of scope for this repository.
