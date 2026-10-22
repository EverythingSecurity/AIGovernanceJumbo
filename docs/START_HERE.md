# Start here

This guide is for a small team that builds or deploys an AI system and wants to know
**which controls to look at first**, without reading six standards. It is a planning
aid, not legal advice: confirm which laws apply to you with qualified counsel.

## 1. Pick the frameworks that are plausibly relevant

Short on time? `aicontrols scope wizard` asks a few questions and suggests frameworks, showing the reason for each. The table below is the manual version.

| If you... | Look at | Why |
|---|---|---|
| Sell to or operate in the EU, or your AI affects people in the EU | `eu-ai-act`, `gdpr` | Binding law. The AI Act's obligations depend on your role and the system's risk class. |
| Process personal data | `gdpr`, `iso-27701`, `pbd`, `iso-31700` | Privacy obligations and good practice. |
| Are a financial entity (or serve one) in the EU | `dora` | ICT risk and third-party rules. |
| Want a certifiable management system for AI | `iso-42001` (+ `iso-27001`) | Certification is voluntary but common in procurement. |
| Need a risk vocabulary or a self-assessment structure | `nist-ai-rmf`, `oecd-ai` | Voluntary guidance. |
| Ship an LLM-based feature | `owasp-llm`, `iso-27090`, `mitre-atlas` | Threat catalogues for engineers and red teams. |

List what is available:

```bash
aicontrols frameworks
```

## 2. Work by domain, not by framework

The same underlying work (an incident process, a supplier review, staff training)
satisfies items in many frameworks. The **domain** is the unit that lets you do it once.

```bash
aicontrols domains                          # 32 domains with control counts
aicontrols crosswalk incident               # one incident plan covers these controls
aicontrols crosswalk "human oversight"
```

Each domain includes consolidation guidance, for example "one incident response plan
covers ISO 27001 A.5.24-A.5.27, GDPR Art. 33/34, EU AI Act Art. 73 and DORA's timelines".

In the web explorer, the **Coverage map** tab shows the same thing as a grid: the
darker the row, the more frameworks one programme can satisfy at once.

## 3. A worked example: a chatbot that uses customer data

1. **Find the threats.** `aicontrols list -f owasp-llm` (the ten LLM risks) and
   `aicontrols search "prompt injection"`.
2. **Find the legal asks.** `aicontrols search "transparency" -f eu-ai-act`,
   `aicontrols search "breach" -f gdpr`.
3. **Pick domains** your team will own: for example `secure-ai-development`,
   `incident`, `supply chain`, `data subject`.
4. **Export a working list** and track it however you like:

   ```bash
   aicontrols export -d "supply chain" --format csv -o supply_chain.csv
   ```
5. **Collect evidence.** Every control carries an *Evidence to verify* field. That field
   is your audit request list: what an auditor or customer will ask to see.
6. **Re-check against the source.** Requirement text here is paraphrased. Before you
   claim compliance with a clause, read the clause.

Ready to turn this into a plan with owners and status? See [SCOPING.md](SCOPING.md).

## 4. Using it from Python

```python
import aicontrols

lib = aicontrols.load()
hits = lib.search("data poisoning", limit=5)
for c in hits:
    print(c.id, c.cia, c.title)

# everything in other frameworks that one programme could also satisfy
for other in lib.related("gdpr:Art.33"):
    print(other.framework_id, other.ref, other.title)
```

## What the data does not do

- It does **not** tell you whether you are compliant, or whether a law applies to you.
- Cross-framework links are **domain-level** ("these controls can share one programme"),
  not clause-for-clause equivalences.
- C/I/A tags are a judgement about what a control primarily protects, not part of any
  standard. See [METHODOLOGY.md](METHODOLOGY.md).
