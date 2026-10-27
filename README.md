# AI Controls Framework

Cross-mapped AI governance and security controls as **data**, a **Python API / CLI**
and a **searchable web explorer**. 557 controls from 18 frameworks (ISO/IEC 42001, 27001,
27701, 42005, 27090, 5181, 31700, 17021-1; EU AI Act; GDPR; DORA; NIST AI RMF and ARIA;
OECD AI Principles; MITRE ATLAS; OWASP LLM Top 10; FAIR; Privacy by Design) grouped into 32
domains so one piece of work can be mapped to every framework it helps satisfy.

> Planning aid only, not legal or audit advice. Requirement text is a paraphrase; verify
> against the source. See [DISCLAIMER.md](DISCLAIMER.md).

Repository: <https://github.com/EverythingSecurity/AIGovernanceJumbo> · Explorer (after Pages is enabled): <https://everythingsecurity.github.io/AIGovernanceJumbo/>

## Quick start

```bash
git clone https://github.com/EverythingSecurity/AIGovernanceJumbo.git
cd AIGovernanceJumbo
python3 -m venv .venv && source .venv/bin/activate    # Python 3.9+
python -m pip install -e .                             # no runtime dependencies

aicontrols search "prompt injection"
aicontrols show gdpr:Art.33
aicontrols crosswalk gdpr:Art.33     # same-domain controls in other frameworks
aicontrols export -f eu-ai-act --format csv -o eu_ai_act.csv
```

`aicontrols` is only on your PATH while the virtual environment is active.

```python
import aicontrols
lib = aicontrols.load()
lib.search("data poisoning")[0].title
lib.related("gdpr:Art.33")
```

**Scope your own work:** `aicontrols scope wizard` suggests which frameworks fit an AI system from a few plain questions, and `aicontrols scope` records your AI systems, which controls apply, owners and status, and exports a Statement-of-Applicability style CSV. See [docs/SCOPING.md](docs/SCOPING.md).

**Run the governance lifecycle:** `aicontrols workflow` takes a scoped system through six stages (profile, harmonise into common controls, tailor, monitor, manage exceptions, analyse gaps) with stage gates, separation-of-duties checks and a hash-chained audit trail. See [docs/WORKFLOW.md](docs/WORKFLOW.md).

**Scope in the browser:** the **My scope** tab of the web explorer runs the wizard, plan and tracker locally (nothing is uploaded) and reads and writes the same scope file.

**Web explorer:** `python -m http.server` in the repo root, then open
<http://localhost:8000/site/>. It is deployed to GitHub Pages by
`.github/workflows/pages.yml`.

New here? Read [docs/START_HERE.md](docs/START_HERE.md).

## Layout

| Path | What |
|---|---|
| `data/` | `controls.json`, `frameworks.json`, `domains.json` (generated, schema-validated) |
| `schema/` | JSON Schemas for the data files |
| `src/aicontrols/` | Python package and CLI |
| `site/` | Static explorer (no build step, no external requests) |
| `tools/` | `build_data.py` (workbook export -> data), `validate.py` |
| `AI_Governance_Master_Checklist.{json,xlsx}` | Source workbook |
| `docs/` | Start-here guide, scoping guide, methodology and known limits |
| `examples/` | A worked scope file (fictional organisation) |

## License

[Apache-2.0](LICENSE). See [NOTICE](NOTICE) for third-party attributions. The standards
referenced remain the property of their publishers; this repository contains paraphrases
and mappings only.
