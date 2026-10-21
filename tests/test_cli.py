# SPDX-License-Identifier: Apache-2.0
import csv
import io
import json

import pytest

from aicontrols.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_frameworks(capsys):
    code, out, _ = run(capsys, "frameworks")
    assert code == 0 and "eu-ai-act" in out and "iso-42001" in out


def test_search(capsys):
    code, out, _ = run(capsys, "search", "data", "poisoning", "-n", "3")
    assert code == 0 and len(out.strip().splitlines()) == 3


def test_search_no_match_exits_nonzero(capsys):
    code, _, err = run(capsys, "search", "zzzzqqqq")
    assert code == 1 and "no matches" in err


def test_show(capsys):
    code, out, _ = run(capsys, "show", "gdpr:Art.33")
    assert code == 0 and "breach" in out.lower()


def test_show_unknown(capsys):
    code, _, err = run(capsys, "show", "nope:1")
    assert code == 2 and "unknown control id" in err


def test_crosswalk_by_control_and_by_domain(capsys):
    code, out, _ = run(capsys, "crosswalk", "gdpr:Art.33")
    assert code == 0 and "consolidation guidance" in out
    code, out, _ = run(capsys, "crosswalk", "incident")
    assert code == 0 and "Incident Management" in out


def test_export_csv_and_json(capsys, tmp_path):
    code, out, _ = run(capsys, "export", "-f", "dora", "--format", "csv")
    rows = list(csv.DictReader(io.StringIO(out)))
    assert code == 0 and len(rows) == 29 and rows[0]["framework_id"] == "dora"
    target = tmp_path / "x.json"
    code, _, _ = run(capsys, "export", "-f", "dora", "--format", "json", "-o", str(target))
    assert code == 0 and len(json.loads(target.read_text())) == 29


def test_requires_subcommand():
    with pytest.raises(SystemExit):
        main([])
