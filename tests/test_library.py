# SPDX-License-Identifier: Apache-2.0
import pytest

import aicontrols


@pytest.fixture(scope="module")
def lib():
    return aicontrols.load()


def test_counts(lib):
    assert len(lib.controls) == 557
    assert len(lib.frameworks) == 18
    assert sum(f.control_count for f in lib.frameworks.values()) == 557


def test_iso27001_annex_a_is_disambiguated_from_clauses(lib):
    # The workbook lists clause 5.1 and Annex A control 5.1 under the same bare ref.
    assert lib.get("iso-27001:5.1").title == "Leadership and commitment"
    assert lib.get("iso-27001:A.5.1").title == "Policies for information security"


def test_ids_with_colons_in_ref(lib):
    c = lib.get("owasp-llm:LLM01:2025")
    assert c.ref == "LLM01:2025" and c.framework_id == "owasp-llm"


def test_unknown_id_raises(lib):
    with pytest.raises(KeyError):
        lib.get("nope:1")


def test_framework_lookup_by_name_or_id(lib):
    assert lib.framework("EU AI Act").id == "eu-ai-act"
    assert lib.framework("gdpr").id == "gdpr"
    with pytest.raises(KeyError):
        lib.framework("not-a-framework")


def test_filter_by_framework_and_cia(lib):
    rows = lib.filter(framework="owasp-llm", cia="c")
    assert rows and all(c.framework_id == "owasp-llm" and c.c for c in rows)


def test_info_rows_hidden_by_default(lib):
    assert all(c.kind == "control" for c in lib.filter(framework="mitre-atlas"))
    assert any(c.kind == "info" for c in lib.filter(framework="mitre-atlas", include_info=True))


def test_search_finds_prompt_injection(lib):
    ids = [c.id for c in lib.search("prompt injection", limit=5)]
    assert "owasp-llm:LLM01:2025" in ids


def test_search_can_be_scoped_to_a_framework(lib):
    assert {c.framework_id for c in lib.search("breach", framework="gdpr")} == {"gdpr"}


def test_search_empty_query(lib):
    assert lib.search("   ") == []


def test_related_excludes_own_framework_and_shares_domain(lib):
    c = lib.get("gdpr:Art.33")
    rel = lib.related(c.id)
    assert rel
    assert all(r.framework_id != "gdpr" and r.domain_id == c.domain_id for r in rel)


def test_every_domain_control_exists(lib):
    for d in lib.domains.values():
        for cid in d.control_ids:
            assert lib.get(cid).domain_id == d.id


def test_to_dict_round_trips_core_fields(lib):
    d = lib.get("eu-ai-act:Art.5").to_dict()
    assert d["id"] == "eu-ai-act:Art.5" and set(d["cia"]) == {"c", "i", "a"}


def test_search_folds_plurals(lib):
    assert {c.id for c in lib.search("incident", limit=50)} == {c.id for c in lib.search("incidents", limit=50)}


def test_domain_corrections_are_applied(lib):
    # Regressions for assignments the original workbook got wrong.
    assert lib.get("iso-42001:6.1.2").domain_id == "risk-assessment-treatment"
    assert lib.get("iso-42001:6.1.3").domain_id == "risk-assessment-treatment"
    assert lib.get("eu-ai-act:Art.99").domain_id == "legal-regulatory-compliance-obligations"
    assert lib.get("eu-ai-act:Art.3").domain_id.startswith("framework-specific")
    assert lib.get("mitre-atlas:TA-06").domain_id == "mitre-atlas-tactics-adversary-attack-lifecycle"
    assert lib.get("fair:S1.1").domain_id == "risk-quantification-fair"
    incident = {lib.get(i).framework_id for i in lib.domains["incident-management-breach-notification"].control_ids}
    assert "iso-17021-1" not in incident


def test_override_file_is_consistent_with_the_dataset(lib):
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "tools" / "domain_overrides.json"
    seen = set()
    for group in json.loads(path.read_text(encoding="utf-8"))["corrections"]:
        assert group["reason"].strip()
        assert group["domain"] in lib.domains
        for cid in group["controls"]:
            assert cid not in seen, f"{cid} listed twice"
            seen.add(cid)
            assert lib.get(cid).domain_id == group["domain"]
