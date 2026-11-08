"""Layer ATT&CK Navigator dari heatmap (`build_heatmap_layer`): fungsi murni, tanpa DB."""

from __future__ import annotations

from typing import Any

from cti_core.db.repositories.mitre import build_heatmap_layer

HEATMAP: dict[str, Any] = {
    "rows": ["LockBit", "APT41"],
    "ttps": [
        {"id": "T1486", "name": "Data Encrypted"},
        {"id": "T1190", "name": "Exploit"},
    ],
    "matrix": [[22, 5], [0, 18]],
    "max_val": 22,
}


def _by_id(layer: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {t["techniqueID"]: t for t in layer["techniques"]}


def test_heatmap_layer_scores_are_column_sums() -> None:
    layer = build_heatmap_layer(HEATMAP, view="ta", days=90)
    assert {k: v["score"] for k, v in _by_id(layer).items()} == {"T1486": 22, "T1190": 23}


def test_heatmap_layer_comment_lists_nonzero_rows_desc() -> None:
    by_id = _by_id(build_heatmap_layer(HEATMAP, view="ta", days=90))
    assert by_id["T1190"]["comment"] == "APT41: 18, LockBit: 5"
    assert by_id["T1486"]["comment"] == "LockBit: 22"


def test_heatmap_layer_gradient_max() -> None:
    layer = build_heatmap_layer(HEATMAP, view="ta", days=90)
    assert layer["gradient"] == {
        "colors": ["#ffe766", "#ff6666"],
        "minValue": 0,
        "maxValue": 23,
    }


def test_heatmap_layer_skips_non_t_ids() -> None:
    heatmap = {**HEATMAP, "ttps": [HEATMAP["ttps"][0], {"id": "X999", "name": "x"}]}
    layer = build_heatmap_layer(heatmap, view="ta", days=90)
    assert list(_by_id(layer)) == ["T1486"]


def test_heatmap_layer_empty() -> None:
    layer = build_heatmap_layer({"rows": [], "ttps": [], "matrix": []}, view="ta", days=90)
    assert layer["techniques"] == []
    assert layer["gradient"]["maxValue"] == 1


def test_heatmap_layer_metadata_and_envelope() -> None:
    layer = build_heatmap_layer(HEATMAP, view="industry", days=30)
    assert layer["metadata"] == [
        {"name": "row", "value": "LockBit"},
        {"name": "row", "value": "APT41"},
    ]
    assert layer["versions"] == {"attack": "14", "navigator": "4.9", "layer": "4.5"}
    assert layer["domain"] == "enterprise-attack"
    assert "Industry" in layer["name"]
    assert "30" in layer["description"]
