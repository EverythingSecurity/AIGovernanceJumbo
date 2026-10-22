# Scoping and tracking your governance work

The dataset in `data/` is read-only reference material. The **scope layer** is where you
record your own decisions on top of it: which AI systems you have, which frameworks apply
to each, which controls apply (and why not, if they don't), who owns the work, and how far
along it is. It is a planning aid, not a compliance verdict.

A worked example is in [`examples/chatbot-scope.json`](../examples/chatbot-scope.json)
(a fictional retailer with a customer-support chatbot).

## Keep the file private

`aicontrols-scope.json` describes your real systems, owners and gaps. Keep it in a private
repository. It is in this repo's `.gitignore` so it is not committed here by accident.

## The workflow

```bash
# 1. create the file and describe one AI system
aicontrols scope init --org "Acme Retail"
aicontrols scope add-system support-chatbot \
  --name "Customer support chatbot" \
  --frameworks iso-42001,iso-27001,eu-ai-act,gdpr,owasp-llm

# 2. decide what does not apply (a justification is mandatory)
aicontrols scope set eu-ai-act:Art.53 --applicable no \
  --justification "We deploy a third-party model and do not provide one."

# 3. assign work by domain, not control by control
aicontrols scope set --domain incident --owner "Head of Security Operations" --due 2026-12-31

# 4. record progress and evidence
aicontrols scope set iso-27001:A.5.24 --status implemented --evidence "IR plan v3 (wiki)"

# 5. see where you stand
aicontrols scope plan        # workstreams (domains), most-shared first
aicontrols scope plan --top 5 --min-frameworks 3     # a first-meeting view
aicontrols scope plan --top 5 --format md -o plan.md # Markdown for a document
aicontrols scope status      # completion by framework (or --by domain)
aicontrols scope export -o soa.csv                   # CSV (add --format md for Markdown)
aicontrols scope validate
```

With more than one system, add `-s <system-id>` to each command. Use `--file` to point at a
scope file elsewhere.

## How it works

- **Baseline scope** is every real control of the frameworks you chose for that system.
  Choosing the frameworks is the scoping decision; deciding whether the law applies to you
  is yours and your counsel's.
- **Only decisions are stored.** Anything you have not touched is *applicable* and
  *not_started*. The file stays small and holds no dataset text.
- **Statuses:** `not_started`, `in_progress`, `implemented`, `verified`. *Completion* is
  implemented plus verified, as a share of applicable controls.
- **Workstreams are domains.** One owner per domain usually means one task satisfying
  several frameworks. `scope plan` lists the most-shared domains first, with each
  workstream's next due date and the number of open controls past due. Use `--top` and
  `--min-frameworks` to show only the few that matter for a first steering meeting.
- **No automatic inheritance.** When you mark a control done, the tool lists other in-scope
  controls in the same domain that are still open, so you can check whether the same work
  satisfies them. It never updates them for you, because the cross-framework link is a
  domain-level grouping and not a clause-for-clause equivalence.
- **Re-check after upgrades.** `scope validate` warns if the dataset version changed since
  the file was created.

## Statement of Applicability

`scope export` writes one row per in-scope control with the applicability decision,
justification, status, owner, due date and evidence. It is a starting point for the SoA that
ISO/IEC 27001 and 42001 expect; review and approve it before relying on it.
