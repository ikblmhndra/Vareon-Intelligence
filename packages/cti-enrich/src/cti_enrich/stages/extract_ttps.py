"""Stage: ekstrak TTP MITRE ATT&CK dari ringkasan artikel -- port
`articleValidator.extractTTPs()` (`ScraperNews/modules/articleValidator.py:153-193`).

Udah pasang `response_format={"type":"json_object"}` di kode asli -- gak ada
bug di sini (beda dari `articleValidator()`/`classify.py`), disalin apa
adanya termasuk prompt-nya."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from cti_core.attack_ttp import NormalizedTTP, TechniqueCatalog, normalize_ttps
from cti_core.llm.client import first_choice, get_llm_client, parse_json_response, store_param
from cti_core.llm.usage import prompt_version
from openai import RateLimitError

from cti_enrich.stages.classify import OpenAIQuotaExhausted
from cti_enrich.stages.llm_messages import build_messages

_TTP_SYSTEM_PROMPT = """Based on the provided article summary, identify the top 5 most relevant MITRE ATT&CK techniques. For each technique return:
    The technique name, the technique ID (e.g. "T1566.001"), and the specific string or sentence from the input that led to the identification (evidence). If the content is not related to a threat campaign, set "has_techniques" to false.

    Respond ONLY with a valid JSON object:
    {
    "has_techniques": true/false,
    "techniques": [
        {"technique_name": "text", "technique_id": "text", "evidence": "exact phrase from input"}
    ]
    }
    """


@dataclass
class Technique:
    technique_id: str
    technique_name: str
    evidence: str = ""
    extracted_id: str | None = None
    extracted_name: str | None = None
    """Pasangan asli LLM -- diisi `normalize_ttp_result()`; `technique_id`/
    `technique_name` setelah itu = ID + nama kanonik ATT&CK."""


@dataclass
class TtpResult:
    has_techniques: bool
    techniques: list[Technique] = field(default_factory=list)


_MAX_TOKENS = 2000
"""Kode lama pasang `max_tokens=1000` (cukup buat OpenAI asli, respons
langsung tanpa reasoning tokens). Gateway dev (9router) modelnya
reasoning-style -- lihat catatan sama persis di `classify.py::_MAX_TOKENS`,
bug yang sama (truncated mid-`<think>`) berisiko kejadian di sini juga
walau belum ketauan nyata di korpus test. Dinaikin preventif, bukan reaktif."""


_PROMPT_VERSION = prompt_version(_TTP_SYSTEM_PROMPT)

_MAX_ATTEMPTS = 3
"""2 retry -- sama alasan `classify.py::_MAX_ATTEMPTS`, respons kosong/
rusak dari gateway reasoning-model itu transien."""


def extract_ttps(summary: str) -> TtpResult:
    """Terima ringkasan (LSA, `stages/summarize.py`) yang udah dipotong
    caller -- `nlp.py` manggil ini dengan `result[:2000]`, potongan itu
    tanggung jawab caller (`pipeline.py`), bukan di sini."""
    client, model_name = get_llm_client(task="ttp")
    last_error: json.JSONDecodeError | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            completion = client.chat.completions.create(
                model=model_name,
                response_format={"type": "json_object"},
                messages=build_messages(
                    _TTP_SYSTEM_PROMPT, summary, attempt=attempt, tag="article_summary"
                ),
                max_tokens=_MAX_TOKENS,
                n=1,
                temperature=0,
                prompt_version=_PROMPT_VERSION,
                **store_param(),
            )
        except RateLimitError as e:
            if any(
                code in str(e)
                for code in (
                    "insufficient_funds",
                    "billing_hard_limit_reached",
                    "exceeded your current quota",
                )
            ):
                raise OpenAIQuotaExhausted(f"OpenAI credit exhausted: {e}") from e
            raise

        try:
            data = parse_json_response(first_choice(completion).message.content)
            break
        except json.JSONDecodeError as e:
            last_error = e
    else:
        assert last_error is not None
        raise last_error
    techniques = [
        Technique(
            technique_id=t["technique_id"],
            technique_name=t["technique_name"],
            evidence=t.get("evidence", ""),
        )
        for t in data.get("techniques", [])
    ]
    return TtpResult(has_techniques=bool(data.get("has_techniques")), techniques=techniques)


def normalize_ttp_result(result: TtpResult, catalog: TechniqueCatalog) -> TtpResult:
    """Pasangan ID/nama LLM -> ID + nama kanonik katalog ATT&CK (QA BUG-C01/
    BUG-04/BUG-B8 -- aturannya di `cti_core.attack_ttp`). Technique yang
    dibuang (nama tactic, ID+nama gak dikenal) hilang dari hasil; duplikat
    per ID akhir digabung. Teks asli LLM ikut dibawa (`extracted_*`)."""
    if not result.techniques:
        return result
    evidence = {(t.technique_id, t.technique_name): t.evidence for t in result.techniques}
    normalized = normalize_ttps(
        [(t.technique_id, t.technique_name) for t in result.techniques], catalog
    )
    techniques = [
        Technique(
            technique_id=n.ttp_id,
            technique_name=n.ttp_name,
            evidence=evidence.get((n.extracted_id or "", n.extracted_name or ""), ""),
            extracted_id=n.extracted_id,
            extracted_name=n.extracted_name,
        )
        for n in normalized
    ]
    return TtpResult(
        has_techniques=result.has_techniques and bool(techniques), techniques=techniques
    )


def as_normalized(t: Technique) -> NormalizedTTP:
    return NormalizedTTP(t.technique_id, t.technique_name, t.extracted_id, t.extracted_name)
