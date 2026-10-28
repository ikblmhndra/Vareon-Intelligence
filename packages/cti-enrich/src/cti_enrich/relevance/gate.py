"""Keputusan gate relevansi (P5, spec 5): fungsi murni, tanpa DB dan tanpa model.

`Probs` hanya di-import untuk type checker: `cti_enrich.relevance.model` menarik sklearn/scipy
di level modul, dan `cti_enrich.pipeline` harus tetap bisa di-import tanpa extra `nlp`
(lihat komentar di `story/attach.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from cti_core.config import RelevanceSettings

    from cti_enrich.relevance.model import Probs

Decision = Literal["shadow", "gated", "audit", "llm"]
"""`shadow` = LLM tetap dipanggil, gate mati; `gated` = LLM dilewati; `audit` = dalam band tapi
dikirim ke LLM sebagai sampel; `llm` = di luar band."""


@dataclass(frozen=True)
class GateDecision:
    decision: Decision
    in_band: bool


def in_audit_sample(url_hash: str, rate: float) -> bool:
    """Sampel audit deterministik dari hash URL: artifak yang sama selalu jatuh di sisi yang
    sama, jadi replay/enrich ulang tidak mengubah ukuran kesepakatan."""
    return int(url_hash[:8], 16) / 0xFFFFFFFF < rate


def decide(
    probs: Probs,
    *,
    url_hash: str,
    gate_state: Literal["shadow", "gate"],
    cfg: RelevanceSettings,
) -> GateDecision:
    in_band = probs.threat_news >= cfg.accept_threshold
    # `mode != auto` menang atas state di DB: operator yang menahan prod di shadow tidak boleh
    # dilangkahi oleh baris model yang sudah terlanjur `gate`.
    if gate_state != "gate" or cfg.mode != "auto":
        return GateDecision("shadow", in_band)
    if not in_band:
        return GateDecision("llm", False)
    if in_audit_sample(url_hash, cfg.audit_rate):
        return GateDecision("audit", True)
    return GateDecision("gated", True)
