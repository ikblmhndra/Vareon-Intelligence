"""Setiap pemanggil LLM wajib menamai task-nya (log `llm_calls`, spec bagian 3).

Pemindaian pakai `ast`, bukan regex: `get_llm_client()` juga muncul di docstring/komentar
(client.py, usage.py, ta_profile.py) dan itu tidak boleh dihitung sebagai pemanggil."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TASKS = {
    "classify",
    "classify_tweet",
    "ttp",
    "recap_daily",
    "recap_weekly",
    "newsletter_article",
    "newsletter_metadata",
    "newsletter_summary",
    "cve_email_validate",
    "cve_email_mitigation",
    "cve_email_risk",
    "ta_profile",
    "exec_brief",
    "news_of_the_day",
}


def _sources() -> list[Path]:
    files: list[Path] = []
    for top in ("apps", "packages", "scrapers"):
        for p in (ROOT / top).rglob("*.py"):
            parts = p.relative_to(ROOT).parts
            if "tests" in parts or ".venv" in parts or "node_modules" in parts:
                continue
            files.append(p)
    return files


def _callee(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _scan() -> tuple[list[str], set[str]]:
    """(pemanggil `get_llm_client` tanpa `task=`, himpunan literal task)."""
    missing: list[str] = []
    literals: set[str] = set()
    for path in _sources():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                kw = {k.arg: k.value for k in node.keywords}
                if _callee(node) == "get_llm_client" and "task" not in kw:
                    missing.append(f"{path.relative_to(ROOT)}:{node.lineno}")
                t = kw.get("task")
                if isinstance(t, ast.Constant) and isinstance(t.value, str):
                    literals.add(t.value)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                args = node.args
                pos = args.posonlyargs + args.args
                pairs = list(zip(pos[len(pos) - len(args.defaults) :], args.defaults, strict=True))
                pairs += [
                    (a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True) if d
                ]
                for a, d in pairs:
                    if a.arg == "task" and isinstance(d, ast.Constant) and isinstance(d.value, str):
                        literals.add(d.value)
    return missing, literals


def test_every_get_llm_client_call_names_a_task() -> None:
    missing, literals = _scan()
    assert not missing, f"get_llm_client() tanpa task=: {missing}"
    assert literals == EXPECTED_TASKS
