"""Skema request recap (#21 PR 3). Respons recap lainnya `dict[str, object]` (bentuk longgarnya
ada di `apps/web/src/lib/api/loose-types.ts`), jadi yang punya skema hanya body yang ditulis klien.

`Verdict` diimpor dari `recap_quality` (modul murni, tanpa DB) alih-alih ditulis ulang di sini:
empat verdict itu harus sama persis dengan yang ditulis model dan yang dibaca hit rate."""

from __future__ import annotations

from pydantic import BaseModel

from cti_api.services.recap_quality import Verdict


class ScorecardOverrideIn(BaseModel):
    """Verdict analis untuk satu event forecast di scorecard: `happened`, `partly`,
    `not_happened`, atau `unclear` (dikeluarkan dari penyebut hit rate)."""

    verdict: Verdict
