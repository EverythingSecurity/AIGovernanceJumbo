# Engagement layer: plan and conflicts

Status: decided. Offline engagement file, phases 2 to 5, built one phase at a time. Phase 2 (scoping, rules, recommendations, review and assignment), roles, and the first half of phase 3 (framework questionnaires, assignment to collaborators, answers with evidence references, review, submit and lock) are done; see ENGAGEMENT.md. The engagement is stored inside the client's scope file (one scope file per client), which reuses the audit chain, validation, import and browser storage.

## What the repository is today

- **Stack:** Python 3.9+ standard library only (no runtime dependencies), a command-line tool, and a static browser app (plain JavaScript, no build step, no server) published on GitHub Pages.
- **No database, no backend, no login, no API.** All state is one private JSON "scope file" (schema 1.2). The browser keeps it in local storage and never uploads it. This is a stated design promise ("Private by design").
- **Pattern used so far:** each layer is a data spec (JSON) plus a Python engine and CLI, a JavaScript port for the browser, and tests that run both engines on the same scenario and require identical results, including the audit hash chain.
- **Framework content (reused as is):** 18 frameworks, 551 controls, 32 domains, with cross-framework grouping through domains. Includes DORA, ISO 42001, ISO 27001, EU AI Act, GDPR, NIST AI RMF. No Qatar PDPPL.
- **Existing layers:** scoping and framework wizard, workflow (common controls, effectiveness, exceptions, audit trail), GRC (mapping matrix, registers, coverage, KPIs).

## What the spec asks for

A multi-user, multi-tenant consulting platform: principal and client organisations, six roles, invitations and MFA, tenant isolation, file uploads with virus scanning, notifications and background jobs, PDF reports, an immutable audit log, data residency.

## Conflicts with the current repository

| Spec requirement | Current repository |
|---|---|
| Tenancy, authentication, MFA, RBAC, invitations | None. Names and roles are typed labels; nothing authenticates them. |
| Tenant isolation tested at data and API layers | No server and no API, so no isolation to test. |
| Database, ORM, migrations | None. A JSON file. |
| Evidence upload, virus scan, encryption at rest | Nothing is uploaded or stored on a server. |
| Notifications, reminders, escalation jobs | No background process. |
| Immutable audit log | Hash-chained and tamper-evident, not immutable. |
| Segregation of duties | Enforced by name only. |
| "Do not introduce a new stack" | Meeting the above needs a server, a database and an identity provider. |

Most of the multi-user requirements cannot be met honestly by a static site. Faking them would be worse than leaving them out: a tenant check that only runs in the user's own browser protects nothing.

## What can be built in this architecture

An **engagement file**: a separate private JSON file (alongside the scope file) that records one consulting engagement end to end, with no accounts and no server. The principal and the client pass files back and forth.

| Spec stage | In the engagement file |
|---|---|
| 1 Client onboarding | Client profile, contributor name, status. Roles are labels. |
| 2 Scoping questionnaire | Versioned questionnaire as data (the eight domains in the spec), responses, per-question delegation labels. |
| 3 Recommendation | Applicability rules as versioned data (condition, framework id, rationale, weight). Deterministic engine returns recommendations with confidence, triggering answers and rationale. Only frameworks that exist in the library are recommended. |
| 4 Review and assignment | Override with mandatory justification, final applicable set, one assessment package per framework, cross-framework de-duplication through the existing control grouping. |
| 5 Fulfilment | Tasks, assignees (labels), due dates, responses, evidence as references (title, hash, dates, link), submit and lock, return for correction. |
| 6 Assessment | Completeness and evidence checks, control ratings, assessor review, clarification queries, findings. |
| 7 Reporting | Scoring with a versioned config, readiness bands, gating controls, per-framework and overlap-benefit report, remediation tracking, reassessment history. Markdown and CSV export (PDF is not planned). |

Every state change goes in the same hash-chained audit trail. Segregation of duties (the scoring assessor is not the sign-off) is checked by name only, and documented as such. Command line and browser would get identical results, tested the same way as the other layers.

## Not covered by that option

Real accounts and MFA, tenant isolation, evidence file storage and scanning, email notifications and escalation, background jobs, data residency, immutable logs, a portfolio dashboard across clients. These need a real service.

## Decision

Offline engagement file; phases 2 to 5; no tenancy, auth, uploads, notifications or AI assist.
