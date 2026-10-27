# SPDX-License-Identifier: Apache-2.0
"""Spreadsheet round trip for scoping decisions: a fill-in CSV template and a validating import.

The columns are those of the Statement of Applicability export, so an exported SoA can be edited
and imported back. Import is all-or-nothing: if any row has a problem, nothing is applied and every
problem is reported with its row number.

The browser twin is `site/scope.js` (parseCsv, templateCsv, applyDecisionsCsv); tests keep the two
identical. The parser is written out here, not taken from the `csv` module, so both behave the same.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Dict, Iterable, List, Optional, Tuple

from .library import Library
from .scope import SOA_COLUMNS, STATUSES, Scope, ScopeError, csv_safe

TEMPLATE_VERSION = "1"
ALIASES = {
    "control_id": ("control_id", "control", "id", "control_id"),
    "system": ("system", "system_id"),
    "applicable": ("applicable", "applies", "applicable_(soa)"),
    "justification": ("justification", "reason"),
    "status": ("status",),
    "owner": ("owner",),
    "due": ("due", "due_date"),
    "reviewed": ("reviewed", "last_reviewed"),
    "evidence": ("evidence",),
    "notes": ("notes", "note", "notes_/_gap"),
}
YES = ("yes", "y", "true", "1")
NO = ("no", "n", "false", "0")


# ---- CSV parsing and writing ------------------------------------------------------------
def _first_data_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#") and not s.startswith('"#'):
            return line
    return ""


def detect_delimiter(text: str) -> str:
    """',' or ';' (some spreadsheet locales save semicolon-separated CSV), from the header line."""
    commas = semis = 0
    quoted = False
    for ch in _first_data_line(text):
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch == ",":
            commas += 1
        elif not quoted and ch == ";":
            semis += 1
    return ";" if semis > commas else ","


def parse_csv(text: str, delimiter: Optional[str] = None) -> List[List[str]]:
    """Parse CSV into records. Handles a BOM, quoted fields with embedded newlines and "" escapes."""
    if text.startswith("﻿"):
        text = text[1:]
    delim = delimiter or detect_delimiter(text)
    rows: List[List[str]] = []
    row: List[str] = []
    field: List[str] = []
    quoted = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if quoted:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 1
                else:
                    quoted = False
            else:
                field.append(ch)
        elif ch == '"' and not field:
            quoted = True
        elif ch == delim:
            row.append("".join(field))
            field = []
        elif ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append("".join(field))
            rows.append(row)
            row, field = [], []
        else:
            field.append(ch)
        i += 1
    if field or row:
        row.append("".join(field))
        rows.append(row)
    return [r for r in rows if any(c.strip() for c in r)]


def csv_cell(value) -> str:
    text = csv_safe(value)
    return '"' + text.replace('"', '""') + '"' if any(c in text for c in ',"\r\n') else text


def csv_line(cells: Iterable) -> str:
    return ",".join(csv_cell(c) for c in cells)


def unsafe(cell: str) -> str:
    """Undo csv_safe: a leading apostrophe added before = + - @ is removed on import."""
    return cell[1:] if len(cell) > 1 and cell[0] == "'" and cell[1] in "=+-@" else cell


# ---- template ----------------------------------------------------------------------------------
def template_comments(organisation: str, system_name: str) -> List[str]:
    return [
        "# aicontrols decisions template v%s. Fill in the decision columns, save as CSV (UTF-8) and import it "
        "on the My scope tab, or run: aicontrols scope import-csv" % TEMPLATE_VERSION,
        f"# organisation: {organisation}",
        f"# system-name: {system_name}",
        "# applicable: yes or no (a no needs a justification). status: not_started, in_progress, implemented or "
        "verified. due and reviewed: YYYY-MM-DD (format those columns as text so Excel keeps the format).",
        "# evidence: separate several references with a semicolon. A blank cell leaves that value unchanged. "
        "Do not edit the first columns (system to domain, c, i, a).",
    ]


def template_csv(lib: Library, frameworks: Iterable[str], organisation: str, system_id: str, system_name: str,
                 scope: Optional[Scope] = None) -> str:
    """A fill-in spreadsheet for the chosen frameworks. With a scope, current decisions are pre-filled."""
    fw_ids: List[str] = []
    for key in frameworks:
        try:
            fid = lib.framework(key).id
        except KeyError as e:
            raise ScopeError(e.args[0]) from None
        if fid not in fw_ids:
            fw_ids.append(fid)
    if not fw_ids:
        raise ScopeError("choose at least one framework for the template")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", system_id or ""):
        raise ScopeError("system id may contain only letters, digits, '-' and '_'")
    lines = ["\r\n".join(csv_line([c]) for c in template_comments(organisation, system_name)), csv_line(SOA_COLUMNS)]
    sid_known = bool(scope) and any(s["id"] == system_id for s in scope.data["systems"])
    for c in lib.controls:
        if c.framework_id not in fw_ids or c.kind != "control":
            continue
        d = scope.decision(system_id, c.id) if sid_known else {
            "applicable": True, "justification": "", "owner": None, "status": "not_started", "due": None,
            "reviewed": None, "updated": None, "evidence": [], "notes": ""}
        row = {"system": system_id, "control_id": c.id, "framework_id": c.framework_id, "ref": c.ref, "title": c.title,
               "domain": lib.domains[c.domain_id].name, "c": int(c.c), "i": int(c.i), "a": int(c.a),
               "applicable": "yes" if d["applicable"] else "no", "justification": d["justification"],
               "status": d["status"], "owner": d["owner"] or "", "due": d["due"] or "", "reviewed": d["reviewed"] or "",
               "updated": d["updated"] or "", "evidence": "; ".join(d["evidence"]), "notes": d["notes"]}
        lines.append(csv_line(row[k] for k in SOA_COLUMNS))
    return "\r\n".join(lines) + "\r\n"


# ---- import ----------------------------------------------------------------------------------------
def _norm_header(cell: str) -> str:
    return re.sub(r"\s+", "_", cell.strip().lower())


def _valid_date(value: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        _dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _meta(rows: List[List[str]]) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    for r in rows:
        m = re.match(r"^#\s*([a-z][a-z-]*)\s*:\s*(.*)$", r[0].strip())
        if m:
            meta.setdefault(m.group(1), m.group(2).strip())
    return meta


def import_decisions(scope: Scope, text: str, system_id: Optional[str] = None, organisation: Optional[str] = None,
                     create_system: bool = True) -> dict:
    """Apply a decisions spreadsheet to `scope`. All-or-nothing: nothing changes if `errors` is non-empty."""
    lib = scope.lib
    records = parse_csv(text)
    meta = _meta(records)
    data_rows = [r for r in records if not r[0].lstrip().startswith("#")]
    result = {"applied": 0, "skipped": 0, "errors": [], "warnings": [], "system": None, "created_system": False}
    err = result["errors"]
    if not data_rows:
        err.append({"row": 0, "message": "the file has no header row"})
        return result
    header = [_norm_header(c) for c in data_rows[0]]
    col: Dict[str, int] = {}
    for name, aliases in ALIASES.items():
        for a in aliases:
            if a in header:
                col[name] = header.index(a)
                break
    if "control_id" not in col:
        err.append({"row": 1, "message": "no control_id column (found: " + ", ".join(c for c in header if c) + ")"})
        return result

    def cell(r: List[str], name: str) -> str:
        i = col.get(name)
        return unsafe(r[i].strip()) if i is not None and i < len(r) else ""

    # which system?
    systems_in_file = sorted({cell(r, "system") for r in data_rows[1:] if cell(r, "system")})
    if len(systems_in_file) > 1:
        err.append({"row": 0, "message": "the file mixes several systems: " + ", ".join(systems_in_file)})
        return result
    sid = system_id or (systems_in_file[0] if systems_in_file else None)
    if not sid and len(scope.data["systems"]) == 1:
        sid = scope.data["systems"][0]["id"]
    if not sid:
        err.append({"row": 0, "message": "cannot tell which system to import into: fill the system column or name one"})
        return result
    if not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        err.append({"row": 0, "message": "system id may contain only letters, digits, '-' and '_'"})
        return result
    result["system"] = sid
    existing = next((s for s in scope.data["systems"] if s["id"] == sid), None)
    if existing is None and not create_system:
        err.append({"row": 0, "message": f"unknown system {sid!r}"})
        return result
    allowed = set(existing["frameworks"]) if existing else None

    changes_by_control: Dict[str, dict] = {}
    seen_rows: Dict[str, int] = {}
    ctl = {c.id: c for c in lib.controls}
    stored = scope.data["decisions"].get(sid, {})
    for n, r in enumerate(data_rows[1:], start=2):
        cid = cell(r, "control_id")
        if not cid:
            continue
        c = ctl.get(cid)
        if c is None:
            err.append({"row": n, "message": f"unknown control id {cid!r}"})
            continue
        if c.kind != "control":
            err.append({"row": n, "message": f"{cid} is not a control"})
            continue
        if allowed is not None and c.framework_id not in allowed:
            err.append({"row": n, "message": f"{cid}: its framework is not selected for system {sid!r}"})
            continue
        changes: dict = {}
        raw_app = cell(r, "applicable").lower()
        if raw_app:
            if raw_app in YES:
                changes["applicable"] = True
            elif raw_app in NO:
                changes["applicable"] = False
            else:
                err.append({"row": n, "message": f"{cid}: applicable must be yes or no, got {cell(r, 'applicable')!r}"})
        raw_status = re.sub(r"\s+", "_", cell(r, "status").lower())
        if raw_status:
            if raw_status in STATUSES:
                changes["status"] = raw_status
            else:
                err.append({"row": n, "message": f"{cid}: status must be one of {', '.join(STATUSES)}, got {cell(r, 'status')!r}"})
        for name in ("due", "reviewed"):
            v = cell(r, name)
            if v:
                if _valid_date(v):
                    changes[name] = v
                else:
                    err.append({"row": n, "message": f"{cid}: {name} must be a date like 2026-12-31, got {v!r} "
                                                    "(format the column as text so the spreadsheet keeps it)"})
        for name in ("justification", "owner", "notes"):
            v = cell(r, name)
            if v:
                changes[name] = v
        ev = cell(r, "evidence")
        if ev:
            changes["evidence"] = [x.strip() for x in ev.split(";") if x.strip()]
        justification = changes.get("justification") or str(stored.get(cid, {}).get("justification", "")).strip()
        if changes.get("applicable") is False and not justification:
            err.append({"row": n, "message": f"{cid}: not applicable needs a justification"})
        if cid in changes_by_control:
            result["warnings"].append(f"row {n}: {cid} appears more than once; the last row wins (first seen in row {seen_rows[cid]})")
        changes_by_control[cid] = changes
        seen_rows[cid] = n
    if err:
        return result

    if existing is None:
        fws: List[str] = []
        for cid in changes_by_control:
            f = ctl[cid].framework_id
            if f not in fws:
                fws.append(f)
        if not fws:
            err.append({"row": 0, "message": "no control rows to import"})
            return result
        if not scope.data["systems"]:
            scope.data["organization"] = (organisation or scope.data.get("organization")
                                          or meta.get("organisation") or "My organisation")
        scope.add_system(sid, meta.get("system-name") or sid, fws, "")
        result["created_system"] = True
        stored = scope.data["decisions"].get(sid, {})

    defaults = {"applicable": True, "status": "not_started"}
    for cid, changes in changes_by_control.items():
        plain = {k: v for k, v in changes.items() if k != "evidence"}
        if cid not in stored and all(defaults.get(k) == v for k, v in plain.items()) and "evidence" not in changes:
            result["skipped"] += 1
            continue
        if not plain and "evidence" not in changes:
            result["skipped"] += 1
            continue
        scope.set(sid, scope.select(sid, [cid]), **plain)  # with no fields this still records the update date
        if "evidence" in changes:
            scope.data["decisions"][sid][cid]["evidence"] = changes["evidence"]
        result["applied"] += 1
    return result
