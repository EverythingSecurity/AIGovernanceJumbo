#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Normalize AI_Governance_Master_Checklist.json into data/*.json.

The workbook export has one differently-shaped sheet per framework. This script
turns it into three flat, schema-validated files:

    data/frameworks.json  registry of the 18 frameworks
    data/domains.json     the cross-framework domain crosswalk
    data/controls.json    one record per control (557)

Run from the repository root:  python tools/build_data.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "AI_Governance_Master_Checklist.json"
OUT = ROOT / "data"

# id, name as used in the workbook's Master Control List, registry metadata
FRAMEWORKS = [
    ("iso-42001", "ISO/IEC 42001", "ISO/IEC 42001:2023", "standard", "ISO/IEC", None),
    ("iso-27001", "ISO/IEC 27001", "ISO/IEC 27001:2022", "standard", "ISO/IEC", None),
    ("iso-27701", "ISO/IEC 27701", "ISO/IEC 27701", "standard", "ISO/IEC", None),
    ("iso-42005", "ISO/IEC 42005", "ISO/IEC 42005", "standard", "ISO/IEC", None),
    ("iso-27090", "ISO/IEC 27090", "ISO/IEC 27090", "standard", "ISO/IEC", None),
    ("iso-5181", "ISO/IEC 5181", "ISO/IEC 5181", "standard", "ISO/IEC", None),
    ("iso-31700", "ISO/IEC 31700-1/-2", "ISO 31700-1/-2", "standard", "ISO/IEC", None),
    ("iso-17021-1", "ISO/IEC 17021-1", "ISO/IEC 17021-1", "standard", "ISO/IEC", None),
    ("eu-ai-act", "EU AI Act", "EU AI Act (Regulation (EU) 2024/1689)", "regulation",
     "European Union", "https://eur-lex.europa.eu/eli/reg/2024/1689/oj"),
    ("gdpr", "GDPR", "GDPR (Regulation (EU) 2016/679)", "regulation",
     "European Union", "https://eur-lex.europa.eu/eli/reg/2016/679/oj"),
    ("dora", "DORA", "DORA (Regulation (EU) 2022/2554)", "regulation",
     "European Union", "https://eur-lex.europa.eu/eli/reg/2022/2554/oj"),
    ("nist-ai-rmf", "NIST AI RMF", "NIST AI Risk Management Framework", "framework",
     "NIST", "https://www.nist.gov/itl/ai-risk-management-framework"),
    ("nist-aria", "NIST ARIA", "NIST ARIA (Assessing Risks and Impacts of AI)", "framework",
     "NIST", "https://ai-challenges.nist.gov/aria"),
    ("oecd-ai", "OECD AI Principles", "OECD AI Principles", "framework",
     "OECD", "https://oecd.ai/en/ai-principles"),
    ("mitre-atlas", "MITRE ATLAS", "MITRE ATLAS", "threat-catalogue",
     "The MITRE Corporation", "https://atlas.mitre.org"),
    ("owasp-llm", "OWASP LLM Top 10", "OWASP Top 10 for LLM Applications", "threat-catalogue",
     "OWASP Foundation", "https://genai.owasp.org/llm-top-10/"),
    ("fair", "FAIR Risk Methodology", "FAIR (Factor Analysis of Information Risk)", "methodology",
     "FAIR Institute / The Open Group", "https://www.fairinstitute.org"),
    ("pbd", "Privacy by Design (Cavoukian)", "Privacy by Design (Cavoukian)", "methodology",
     "A. Cavoukian", None),
]
FW_BY_NAME = {name: fid for fid, name, *_ in FRAMEWORKS}

# framework id -> [(workbook sheet, requirement col, security-note col, evidence col, {extras})]
TABS = {
    "iso-42001": [
        ("1 CIA-Security Controls", "Security requirement",
         "Why CIA is involved / what must be protected", "Evidence to verify",
         {"cross_reference": "ISO 27001:2022 cross-ref"}),
        ("2 Non-CIA (Other) Controls", "Requirement",
         "Security enabler link (indirect, if any)", "Evidence to verify",
         {"nature": "Nature of requirement"}),
    ],
    "eu-ai-act": [("3 EU AI Act", "Requirement", "Security note / why CIA is involved",
                   "Evidence to verify", {"roles": "Applicable Role(s) & Responsibilities"})],
    "oecd-ai": [("4 OECD AI Principles", "Requirement", "Security note / why CIA is involved",
                 "Evidence to verify", {})],
    "nist-ai-rmf": [("5 NIST AI RMF", "Suggested action", "Security note / why CIA is involved",
                     "Evidence to verify", {})],
    "iso-42005": [("6 ISO 42005 Impact Assessment", "Guidance point",
                   "Security note / why CIA is involved", "Evidence to verify", {})],
    "iso-27001": [("7 ISO 27001", "Security requirement", "Why CIA is involved",
                   "Evidence to verify", {})],
    "iso-17021-1": [("8 ISO 17021 Alignment", "Certification body (CB) requirement",
                     "Why CIA is involved", "Evidence to verify",
                     {"audit_alignment": "Audit-readiness alignment for the certified organization",
                      "cross_reference": "ISMS / AIMS cross-reference"})],
    "gdpr": [("9 GDPR", "Requirement", "Security note / why CIA is involved",
              "Evidence to verify", {})],
    "owasp-llm": [("10 OWASP LLM Top 10", "Description", "Why CIA is involved",
                   "Evidence to verify", {"mitigations": "Mitigations"})],
    "iso-27701": [("11 ISO 27701 PIMS", "Requirement / guidance", "Why CIA is involved",
                   "Evidence to verify", {})],
    "pbd": [("14 Privacy by Design", "Design practice", "Why CIA is involved",
             "Evidence to verify", {})],
    "iso-31700": [("15 ISO 31700 PbD (Consumer)", "Requirement", "Why CIA is involved",
                   "Evidence to verify", {})],
    "dora": [("16 DORA", "Requirement", "Why CIA is involved", "Evidence to verify", {})],
    "nist-aria": [("17 NIST ARIA", "Practice", "Why CIA is involved", "Evidence to verify", {})],
    "fair": [("18 FAIR Risk Methodology", "Requirement", "Why CIA is involved",
              "Evidence to verify", {})],
    "iso-5181": [("20 ISO 5181 Data Provenance", "Requirement / Guidance",
                  "Why CIA is involved", "Evidence to verify", {})],
    "iso-27090": [("21 ISO 27090 AI Threats", "Requirement / Threat Description",
                   "Why CIA is involved", "Evidence to verify", {})],
    "mitre-atlas": [("22 MITRE ATLAS", "Adversary objective / Description",
                     "Why CIA is involved", "Defensive evidence / test guidance", {})],
}


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def section_label(raw):
    """'A.5 - Organizational controls' -> 'A.5 - Organizational controls' (None stays None)."""
    return clean(raw)


def build():
    src = json.loads(SOURCE.read_text(encoding="utf-8"))
    meta = src["_meta"]
    master = src["12 Master Control List"]["items"]

    # (framework id, ref, title) -> enrichment taken from the framework's own sheet
    enrich, order = {}, {}
    for fid, tabs in TABS.items():
        pos = 0
        for sheet, req_col, note_col, ev_col, extra_cols in tabs:
            block = src[sheet]
            ref_col = block["headers"][0]
            title_col = block["headers"][1]
            for row in block["items"]:
                ref = clean(row.get(ref_col))
                if ref is None:
                    continue
                title = clean(row.get("Title") or row.get(title_col)) or ""
                if row.get("Source") == "Annex A" and not ref.startswith("A."):
                    ref = "A." + ref
                section = clean(row.get("_section"))
                if fid == "iso-27001" and section and section.startswith("A.") \
                        and not ref.startswith("A."):
                    ref = "A." + ref
                key = (fid, ref, title)
                enrich[key] = {
                    "section": section_label(section),
                    "security_note": clean(row.get(note_col)),
                    "evidence": clean(row.get(ev_col)),
                    "extras": {k: clean(row.get(col)) for k, col in extra_cols.items()
                               if clean(row.get(col))},
                }
                order[key] = pos
                pos += 1

    fw_rank = {fid: n for n, (fid, *_rest) in enumerate(FRAMEWORKS)}
    domain_names = []
    controls, seen = [], set()
    unmatched = []
    for idx, row in enumerate(master):
        fid = FW_BY_NAME[row["Framework"]]
        ref = clean(row["Ref"])
        title = clean(row["Title"]) or ""
        key = (fid, ref, title)
        info = enrich.get(key)
        if info is None and fid == "iso-27001":
            info = enrich.get((fid, "A." + ref, title))
            if info is not None:
                ref, key = "A." + ref, (fid, "A." + ref, title)
        if info is None:
            unmatched.append(key)
            info = {"section": None, "security_note": None, "evidence": None, "extras": {}}
        domain = clean(row["Domain"])
        if domain not in domain_names:
            domain_names.append(domain)
        cid = fid + ":" + re.sub(r"\s+", "-", ref)
        if cid in seen:
            raise SystemExit(f"duplicate control id {cid}")
        seen.add(cid)
        section = info["section"]
        is_info = bool(section and section.startswith("Status")) or (
            fid in ("iso-5181", "iso-27090", "mitre-atlas") and ref in ("ID", "Scope", "Use"))
        kind = "info" if is_info else "control"
        record = {
            "id": cid,
            "framework_id": fid,
            "ref": ref,
            "title": title,
            "kind": kind,
            "domain_id": slug(domain),
            "section": section,
            "requirement": clean(row["Requirement (condensed)"]),
            "cia": {"c": row["C"] == "●", "i": row["I"] == "●", "a": row["A"] == "●"},
            "security_note": info["security_note"],
            "evidence": info["evidence"],
        }
        if info["extras"]:
            record["extras"] = info["extras"]
        controls.append((fw_rank[fid], order.get(key, 10**6 + idx), record))

    controls.sort(key=lambda t: (t[0], t[1]))
    controls = [rec for *_k, rec in controls]

    cross = {x["domain"]: x for x in src["13 Domain Crosswalk"]["domains"]}
    domains = []
    for name in domain_names:
        x = cross.get(name, {})
        did = slug(name)
        domains.append({
            "id": did,
            "name": name,
            "description": clean(x.get("what_this_covers")),
            "consolidation_guidance": clean(x.get("consolidation_guidance")),
            "control_ids": [c["id"] for c in controls if c["domain_id"] == did],
        })
    domains.sort(key=lambda d: d["name"])

    counts = {}
    for c in controls:
        counts[c["framework_id"]] = counts.get(c["framework_id"], 0) + 1
    frameworks = [{
        "id": fid, "name": name, "full_name": full, "kind": kind, "publisher": pub,
        "source_url": url, "control_count": counts.get(fid, 0), "last_verified": None,
    } for fid, name, full, kind, pub, url in FRAMEWORKS]

    common = {
        "schema_version": "1.0",
        "dataset_version": meta["dataset_version"],
        "license": meta["license"],
        "copyright": meta["copyright"],
        "disclaimer": meta["disclaimer"],
    }
    OUT.mkdir(exist_ok=True)
    for name, key, payload in (("frameworks", "frameworks", frameworks),
                               ("domains", "domains", domains),
                               ("controls", "controls", controls)):
        doc = {**common, key: payload}
        (OUT / f"{name}.json").write_text(
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"controls={len(controls)} frameworks={len(frameworks)} domains={len(domains)}")
    if unmatched:
        print(f"WARNING: {len(unmatched)} master rows had no framework-sheet match:")
        for k in unmatched:
            print("  ", k)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(build())
