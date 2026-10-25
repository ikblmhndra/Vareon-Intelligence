"""Harness evaluasi Tier 1 (P4 "deterministic extractors"): alat dev, bukan kode produk.

Mengukur kandidat Tier 1 terhadap keluaran LLM yang tersimpan, pada sampel 100 artikel dari dev.
Jalankan dari root repo: `uv run python -m tools.eval.tier1_eval {fetch,run,score} --workdir DIR`
(`tools` namespace package; root repo ada di sys.path lewat `python -m` dan `pythonpath` pytest).
`--workdir` wajib dan ditolak kalau ada di dalam repo (isi artikel tidak boleh ikut ter-commit).

Langkah operator (SQL read-only; tidak ada yang dijalankan oleh tool ini terhadap dev):

  ssh nameless@172.25.1.77 'cd ~/Vareon-Intelligence && docker compose exec -T postgres \\
      psql -U cti -d cti -At' < tools/eval/sample.sql > DIR/sample.jsonl
  ssh nameless@172.25.1.77 'cd ~/Vareon-Intelligence && docker compose exec -T postgres \\
      psql -U cti -d cti -At' < tools/eval/reference.sql > DIR/reference.json

(Dua file karena satu `psql -At` menghasilkan satu aliran; sample.sql = satu baris per artikel,
reference.sql = satu baris JSON.) Lalu: `fetch` (teks ke DIR/texts/<id>.txt, yang sudah ada
dilewati, kegagalan dicatat di DIR/fetch_failures.jsonl), `run` (DIR/candidates.jsonl TANPA
sumber, supaya pelabel tidak bias; DIR/provenance.jsonl; DIR/merged.jsonl untuk cakupan),
pelabelan (DIR/labels.jsonl: candidate_id, correct, quote, labeller), lalu `score`.

Sumber di provenance: dictionary (entitas), explicit/keyword (TTP), keyword (industri, insiden
dari Tier 1), llm (keluaran LLM tersimpan: aktor/TTP/industri), stored (flag
`confirmed_incident` tersimpan). Kandidat `ttp` bernilai ID teknik; `incident` bernilai
"confirmed". Cakupan "sesudah" = keluaran gabungan (industri lewat `merge_industries`; aktor,
TTP, insiden = gabungan per nilai, sama dengan `merge_ttps` yang memenangkan per ID).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FIELDS = ("actor", "malware", "ttp", "industry", "incident")
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class Label:
    candidate_id: str
    correct: bool
    quote: str
    labeller: str


@dataclass(frozen=True)
class Candidate:
    article_id: int
    field: str
    value: str
    sources: frozenset[str]

    @property
    def candidate_id(self) -> str:
        return f"{self.article_id}:{self.field}:{self.value.lower()}"

    def row(self) -> dict[str, Any]:
        """Baris candidates.jsonl: sengaja TANPA sumber (pelabel buta terhadap asal kandidat)."""
        return {
            "candidate_id": self.candidate_id,
            "article_id": self.article_id,
            "field": self.field,
            "value": self.value,
        }


def field_of(candidate_id: str) -> str:
    return candidate_id.split(":", 2)[1]


def score_precision(
    labels: Sequence[Label], provenance: Mapping[str, set[str]]
) -> dict[tuple[str, str], tuple[int, int]]:
    """(field, source) -> (benar, total). Kandidat bersumber ganda dihitung di tiap sumbernya.
    Satu kandidat dihitung sekali: label `user` mengalahkan label pelabel lain."""
    chosen: dict[str, Label] = {}
    for label in labels:
        prev = chosen.get(label.candidate_id)
        if prev is None or (label.labeller == "user" and prev.labeller != "user"):
            chosen[label.candidate_id] = label
    counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for cid, label in chosen.items():
        for source in provenance.get(cid, set()):
            cell = counts[(field_of(cid), source)]
            cell[0] += int(label.correct)
            cell[1] += 1
    return {k: (v[0], v[1]) for k, v in counts.items()}


def agreement_rate(labels: Sequence[Label]) -> tuple[int, int]:
    """(sepakat, total) untuk kandidat yang dilabeli `subagent` DAN `user`."""
    by: dict[str, dict[str, bool]] = defaultdict(dict)
    for label in labels:
        by[label.candidate_id][label.labeller] = label.correct
    both = [v for v in by.values() if "subagent" in v and "user" in v]
    return sum(1 for v in both if v["subagent"] == v["user"]), len(both)


def build_candidates(
    article: Mapping[str, Any], text: str, dictionary: Any, catalog: Any
) -> tuple[list[Candidate], dict[str, set[str]]]:
    """Kandidat Tier 1 + LLM tersimpan untuk satu artikel, dan keluaran gabungan per field.

    Meniru pipeline: entitas atas `title + "\\n" + text`; teknik/insiden atas `text or title`.
    """
    from cti_enrich.tier1.entities import match_entities
    from cti_enrich.tier1.incident import incident_verdict
    from cti_enrich.tier1.industry import match_industries
    from cti_enrich.tier1.merge import merge_industries
    from cti_enrich.tier1.ttps import extract_techniques

    aid = int(article["id"])
    title = article.get("title") or ""
    body = text or title
    found: dict[tuple[str, str], tuple[str, set[str]]] = {}  # (field, lower) -> (value, sources)

    def add(field: str, value: str, source: str) -> None:
        entry = found.setdefault((field, value.lower()), (value, set()))
        entry[1].add(source)

    for hit in match_entities(f"{title}\n{text}", dictionary):
        add("actor" if hit.kind == "actor" else "malware", hit.canonical, "dictionary")
    for actor in article.get("actors") or []:
        add("actor", actor, "llm")

    for t in extract_techniques(body, catalog):
        add("ttp", t.ttp_id, t.source)
    for t in article.get("ttps") or []:
        add("ttp", t["id"], "llm")

    tier1_inds = match_industries(title, text)
    for ind in tier1_inds:
        add("industry", ind, "keyword")
    llm_inds = list(article.get("industries") or [])
    for ind in llm_inds:
        add("industry", ind, "llm")

    victim = article.get("victim_name")
    if incident_verdict(title, body, victim).confirmed:
        add("incident", "confirmed", "keyword")
    if article.get("confirmed_incident"):
        add("incident", "confirmed", "stored")

    candidates = [
        Candidate(aid, field, value, frozenset(src)) for (field, _), (value, src) in found.items()
    ]
    merged: dict[str, set[str]] = defaultdict(set)
    for c in candidates:
        if c.field != "industry":
            merged[c.field].add(c.value.lower())
    merged_inds, _ = merge_industries(llm_inds, tier1_inds)
    merged["industry"] = {i.lower() for i in merged_inds}
    return candidates, merged


# ---------------------------------------------------------------- I/O dan CLI


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def check_workdir(raw: str) -> Path:
    path = Path(raw).expanduser().resolve()
    if path == _REPO_ROOT or _REPO_ROOT in path.parents:
        raise SystemExit(f"--workdir tidak boleh di dalam repo: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def cmd_fetch(workdir: Path) -> None:
    from cti_enrich.stages.fetch_text import fetch_text

    texts = workdir / "texts"
    texts.mkdir(exist_ok=True)
    failures: list[dict[str, Any]] = []
    for article in _read_jsonl(workdir / "sample.jsonl"):
        target = texts / f"{article['id']}.txt"
        if target.exists():
            continue
        try:
            text = fetch_text(article["url"])
        except Exception as exc:  # satu URL rusak tidak boleh menghentikan batch
            failures.append({"id": article["id"], "url": article["url"], "error": repr(exc)})
            continue
        if text:
            target.write_text(text)
        else:
            failures.append({"id": article["id"], "url": article["url"], "error": "empty"})
    _write_jsonl(workdir / "fetch_failures.jsonl", failures)
    print(f"fetch selesai; gagal/kosong: {len(failures)}")


def cmd_run(workdir: Path) -> None:
    from cti_core.attack_ttp import TechniqueCatalog
    from cti_enrich.tier1.dictionary import build_dictionary

    ref = json.loads((workdir / "reference.json").read_text())
    dictionary = build_dictionary(
        [(g["name"], g["aliases"] or []) for g in ref["groups"]],
        [(s["name"], s["software_type"], s["aliases"] or []) for s in ref["software"]],
        ref["ta_names"],
        ref["suppressed"],
    )
    catalog = TechniqueCatalog(names=ref["techniques"])
    cand_rows: list[dict[str, Any]] = []
    prov_rows: list[dict[str, Any]] = []
    merged_rows: list[dict[str, Any]] = []
    for article in _read_jsonl(workdir / "sample.jsonl"):
        path = workdir / "texts" / f"{article['id']}.txt"
        text = path.read_text() if path.exists() else ""
        candidates, merged = build_candidates(article, text, dictionary, catalog)
        for c in candidates:
            cand_rows.append(c.row())
            prov_rows.append({"candidate_id": c.candidate_id, "sources": sorted(c.sources)})
        for field, values in merged.items():
            merged_rows.extend(
                {"article_id": article["id"], "field": field, "value": v} for v in sorted(values)
            )
    _write_jsonl(workdir / "candidates.jsonl", cand_rows)
    _write_jsonl(workdir / "provenance.jsonl", prov_rows)
    _write_jsonl(workdir / "merged.jsonl", merged_rows)
    print(f"{len(cand_rows)} kandidat dari {len(_read_jsonl(workdir / 'sample.jsonl'))} artikel")


def _pct(num: int, den: int) -> str:
    return f"{num}/{den} ({100 * num / den:.0f}%)" if den else "0/0 (n/a)"


def cmd_score(workdir: Path) -> None:
    labels = [Label(**row) for row in _read_jsonl(workdir / "labels.jsonl")]
    provenance = {
        r["candidate_id"]: set(r["sources"]) for r in _read_jsonl(workdir / "provenance.jsonl")
    }
    print("Presisi per field dan sumber (benar/total):")
    for (field, source), (ok, total) in sorted(score_precision(labels, provenance).items()):
        print(f"  {field:9} {source:11} {_pct(ok, total)}")

    before: dict[str, set[int]] = defaultdict(set)
    for cid, sources in provenance.items():
        if sources & {"llm", "stored"}:
            before[field_of(cid)].add(int(cid.split(":", 1)[0]))
    after: dict[str, set[int]] = defaultdict(set)
    for row in _read_jsonl(workdir / "merged.jsonl"):
        after[row["field"]].add(row["article_id"])
    total_articles = len(_read_jsonl(workdir / "sample.jsonl"))
    print(f"Cakupan artikel (dari {total_articles}) sebelum -> sesudah:")
    for field in FIELDS:
        print(f"  {field:9} {len(before[field])} -> {len(after[field])}")

    agree, both = agreement_rate(labels)
    print(f"Kesepakatan subagent vs user: {_pct(agree, both)}")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluasi Tier 1 terhadap keluaran LLM tersimpan")
    parser.add_argument("command", choices=("fetch", "run", "score"))
    parser.add_argument("--workdir", required=True)
    args = parser.parse_args(argv)
    workdir = check_workdir(args.workdir)
    {"fetch": cmd_fetch, "run": cmd_run, "score": cmd_score}[args.command](workdir)


if __name__ == "__main__":
    sys.exit(main())
