# Contributing

Thanks for helping. The most useful contributions are corrections: a wrong mapping, a
control filed under the wrong domain, a paraphrase that is inaccurate, a framework that
has been updated.

## Ground rules

- **Do not paste text from standards.** ISO/IEC and similar texts are copyrighted. Write
  requirements in your own words. Contributions with copied clause text will be declined.
- **Cite the source** (clause or article number) in your issue or PR so it can be checked.
- By contributing you agree your work is licensed under Apache-2.0, as in `LICENSE`.

## Changing the data

`data/*.json` is generated from `AI_Governance_Master_Checklist.json`.

1. Edit the source JSON (or `tools/build_data.py` for structural changes).
2. `python tools/build_data.py`
3. `python tools/validate.py` and `pytest`

CI fails if the committed data differs from what the build produces.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
python -m http.server       # then open http://localhost:8000/site/
```

New source files carry `# SPDX-License-Identifier: Apache-2.0`.
