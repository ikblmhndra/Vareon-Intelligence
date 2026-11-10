"""Helper CSV bersama untuk export Intelligence (SR, IOC): guard formula-injection + format."""

from __future__ import annotations

import csv
import datetime
import io

import pytest
from cti_api.services.csv_export import csv_response, safe_cell


@pytest.mark.parametrize("raw", ["=1", "+1", "-1", "@x", "\tx", "\rx"])
def test_safe_cell_formula_prefixes(raw: str) -> None:
    assert safe_cell(raw) == "'" + raw


def test_safe_cell_types() -> None:
    assert safe_cell(None) == ""
    assert (
        safe_cell(datetime.datetime(2026, 11, 9, 1, 2, tzinfo=datetime.UTC))
        == "2026-11-09T01:02:00+00:00"
    )
    assert safe_cell(datetime.date(2026, 11, 9)) == "2026-11-09"
    assert safe_cell(["a", "b"]) == "a;b"
    assert safe_cell(("a", 1)) == "a;1"
    assert safe_cell(["=x"]) == "'=x"
    assert safe_cell(True) == "true"
    assert safe_cell(False) == "false"
    assert safe_cell(42) == 42
    assert safe_cell(1.5) == 1.5


def test_csv_response_headers() -> None:
    resp = csv_response(["a", "b"], [[1, "x"], [2, "y"]], "out.csv", headers={"X-Total": "2"})
    assert resp.media_type == "text/csv; charset=utf-8"
    assert resp.headers["content-disposition"] == 'attachment; filename="out.csv"'
    assert resp.headers["x-total"] == "2"
    body = resp.body.decode("utf-8")
    assert body.startswith("﻿a,b\r\n")
    assert body.endswith("2,y\r\n")


def test_csv_quoting_and_types() -> None:
    rows = [
        ["a,b", 'say "hi"', "line1\nline2", 42, "Ärger", " =1+1", "=cmd", None],
    ]
    resp = csv_response(["h1", "h2", "h3", "n", "u", "sp", "f", "z"], rows, "q.csv")
    body = resp.body.decode("utf-8")
    assert body.count("﻿") == 1 and body.startswith("﻿")
    parsed = list(csv.reader(io.StringIO(body.removeprefix("﻿"))))
    assert parsed[0] == ["h1", "h2", "h3", "n", "u", "sp", "f", "z"]
    assert parsed[1] == ["a,b", 'say "hi"', "line1\nline2", "42", "Ärger", " =1+1", "'=cmd", ""]
