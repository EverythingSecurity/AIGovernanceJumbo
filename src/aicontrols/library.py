# SPDX-License-Identifier: Apache-2.0
"""Load the dataset and query it.

    >>> import aicontrols
    >>> lib = aicontrols.load()
    >>> lib.get("iso-27001:A.5.1").title
    'Policies for information security'
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional


def _data_dir() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here / "data", here.parent.parent / "data"):  # wheel, then source checkout
        if (candidate / "controls.json").is_file():
            return candidate
    raise FileNotFoundError("aicontrols data files not found")


@dataclass(frozen=True)
class Framework:
    id: str
    name: str
    full_name: str
    kind: str
    publisher: str
    source_url: Optional[str]
    control_count: int
    last_verified: Optional[str]


@dataclass(frozen=True)
class Domain:
    id: str
    name: str
    description: Optional[str]
    consolidation_guidance: Optional[str]
    control_ids: tuple


@dataclass(frozen=True)
class Control:
    id: str
    framework_id: str
    ref: str
    title: str
    kind: str
    domain_id: str
    section: Optional[str]
    requirement: str
    c: bool
    i: bool
    a: bool
    security_note: Optional[str]
    evidence: Optional[str]
    extras: Dict[str, str] = field(default_factory=dict)

    @property
    def cia(self) -> str:
        """Compact CIA marker, e.g. 'CI-' or '---'."""
        return ("C" if self.c else "-") + ("I" if self.i else "-") + ("A" if self.a else "-")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "framework_id": self.framework_id, "ref": self.ref,
            "title": self.title, "kind": self.kind, "domain_id": self.domain_id,
            "section": self.section, "requirement": self.requirement,
            "cia": {"c": self.c, "i": self.i, "a": self.a},
            "security_note": self.security_note, "evidence": self.evidence,
            "extras": dict(self.extras),
        }


def _stem(word: str) -> str:
    """Crude plural folding so 'incidents' finds 'incident'."""
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _tokens(text: str) -> List[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())]


class Library:
    """In-memory view of the dataset."""

    def __init__(self, controls: Iterable[Control], frameworks: Iterable[Framework],
                 domains: Iterable[Domain], dataset_version: str, disclaimer: str):
        self.controls = list(controls)
        self.frameworks = {f.id: f for f in frameworks}
        self.domains = {d.id: d for d in domains}
        self.dataset_version = dataset_version
        self.disclaimer = disclaimer
        self._by_id = {c.id: c for c in self.controls}

    def get(self, control_id: str) -> Control:
        try:
            return self._by_id[control_id]
        except KeyError:
            raise KeyError(f"unknown control id {control_id!r}") from None

    def framework(self, key: str) -> Framework:
        """Look up a framework by id or (case-insensitive) name."""
        k = key.strip().lower()
        for f in self.frameworks.values():
            if k in (f.id, f.name.lower(), f.full_name.lower()):
                return f
        raise KeyError(f"unknown framework {key!r}; known ids: {', '.join(self.frameworks)}")

    def domain(self, key: str) -> Domain:
        k = key.strip().lower()
        for d in self.domains.values():
            if k in (d.id, d.name.lower()):
                return d
        hits = [d for d in self.domains.values() if k in d.name.lower() or k in d.id]
        if len(hits) == 1:
            return hits[0]
        raise KeyError(f"unknown or ambiguous domain {key!r}")

    def filter(self, framework: Optional[str] = None, domain: Optional[str] = None,
               cia: str = "", include_info: bool = False) -> List[Control]:
        """Controls matching all given criteria. `cia` is any of 'c', 'i', 'a'."""
        fid = self.framework(framework).id if framework else None
        did = self.domain(domain).id if domain else None
        want = cia.lower()
        out = []
        for c in self.controls:
            if fid and c.framework_id != fid:
                continue
            if did and c.domain_id != did:
                continue
            if (("c" in want and not c.c) or ("i" in want and not c.i)
                    or ("a" in want and not c.a)):
                continue
            if c.kind == "info" and not include_info:
                continue
            out.append(c)
        return out

    def search(self, query: str, framework: Optional[str] = None, limit: int = 20) -> List[Control]:
        """Rank controls by how well they match the query words (title weighs most)."""
        words = _tokens(query)
        if not words:
            return []
        pool = self.filter(framework=framework)
        scored = []
        for c in pool:
            title = set(_tokens(c.title + " " + c.ref))
            body = set(_tokens(" ".join(filter(None, (
                c.requirement, c.security_note, c.evidence, *c.extras.values())))))
            score = 0
            for w in words:
                if w in title:
                    score += 3
                elif w in body:
                    score += 1
                elif any(t.startswith(w) for t in title):
                    score += 2
                elif any(t.startswith(w) for t in body):
                    score += 0.5
            if score:
                scored.append((-score, c.framework_id, c.id, c))
        scored.sort(key=lambda t: t[:3])
        return [t[3] for t in scored[:limit]]

    def related(self, control_id: str) -> List[Control]:
        """Controls in *other* frameworks that share this control's domain.

        This is the dataset's crosswalk: domain-level equivalence, not clause-for-clause
        mapping. Treat it as "these controls can be satisfied by one programme".
        """
        c = self.get(control_id)
        dom = self.domains[c.domain_id]
        return [self._by_id[i] for i in dom.control_ids
                if self._by_id[i].framework_id != c.framework_id]

    def stats(self) -> dict:
        per_fw = {fid: 0 for fid in self.frameworks}
        cia = {"c": 0, "i": 0, "a": 0}
        for c in self.controls:
            per_fw[c.framework_id] += 1
            for k in cia:
                cia[k] += getattr(c, k)
        return {"controls": len(self.controls), "frameworks": per_fw,
                "domains": len(self.domains), "cia": cia,
                "dataset_version": self.dataset_version}


def load(data_dir: Optional[Path] = None) -> Library:
    root = Path(data_dir) if data_dir else _data_dir()
    read = lambda n: json.loads((root / f"{n}.json").read_text(encoding="utf-8"))  # noqa: E731
    controls_doc, fw_doc, dom_doc = read("controls"), read("frameworks"), read("domains")
    controls = [
        Control(id=c["id"], framework_id=c["framework_id"], ref=c["ref"], title=c["title"],
                kind=c["kind"], domain_id=c["domain_id"], section=c.get("section"),
                requirement=c["requirement"], c=c["cia"]["c"], i=c["cia"]["i"],
                a=c["cia"]["a"], security_note=c.get("security_note"),
                evidence=c.get("evidence"), extras=c.get("extras", {}))
        for c in controls_doc["controls"]
    ]
    frameworks = [Framework(**f) for f in fw_doc["frameworks"]]
    domains = [Domain(id=d["id"], name=d["name"], description=d["description"],
                      consolidation_guidance=d["consolidation_guidance"],
                      control_ids=tuple(d["control_ids"])) for d in dom_doc["domains"]]
    return Library(controls, frameworks, domains, controls_doc["dataset_version"],
                   controls_doc["disclaimer"])
