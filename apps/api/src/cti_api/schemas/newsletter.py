"""Adaptasi dari body `dict`/`Body(...)` TANPA validasi di
`ScraperNewsWeb/app/routers/newsletter.py` -- Pydantic model eksplisit
di sini, port `article id` dari ObjectId string ke `int`. Konsisten sama
router lain (RFI/PIR dst) yang juga naikin dict lepas jadi model
tervalidasi, bukan keputusan baru khusus newsletter."""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SummaryLanguage = Literal["id", "en"]
DEFAULT_SUMMARY_LANGUAGE: SummaryLanguage = "id"
"""Bahasa `key_points` dan `summary` per artikel (ROADMAP #22, "Design: Indonesian content"):
Indonesia secara default, Inggris tetap bisa supaya edisi berbahasa Inggris tidak hilang. Judul
bagian, label, subject, dan footer selalu Inggris. Ikut kunci cache ringkasan, jadi satu bahasa
tidak pernah memakai atau menimpa baris bahasa lain. Satu tempat untuk default-nya: field request
di bawah dan service newsletter memakai konstanta ini."""

MAX_HIGHLIGHTS = 3
MAX_FULL_PER_SECTION = 4
MAX_COMPACT_PER_SECTION = 15
"""Batas tier (ROADMAP #22, "Design: density"): per section, beberapa artikel teratas jadi kartu
PENUH (key points + ringkasan, butuh fetch + LLM kecuali sudah di-cache), sisanya masuk daftar
COMPACT (satu baris dari metadata tersimpan, tanpa fetch dan tanpa LLM). SATU tempat untuk
angkanya: deskripsi field di bawah, validasi (`services/newsletter_edition.py`), dan test
memakai konstanta ini. Angkanya titik mulai yang akan disetel setelah edisi pertama."""

LEGACY_MAX_PER_SECTION = 5
"""Batas field LAMA (`apac`/`global_news`/`indonesia`, semuanya kartu penuh). Hapus bersama
field-nya begitu composer baru (PR 9) hidup; sampai itu perilaku request lama tidak berubah."""


class NewsletterSectionsBody(BaseModel):
    # Dua bentuk request yang TIDAK boleh dicampur (lihat `_valid_shape`):
    #  - lama: `highlight`, `apac`, `global_news`, `indonesia`. Satu highlight dan maks 5 kartu
    #    penuh per section. Masih dipakai web sampai composer baru (PR 9); perilakunya tidak
    #    berubah, jadi jangan diubah di sini.
    #  - tier: `highlights` plus `<section>_full` / `<section>_compact`. Batasnya konstanta
    #    `MAX_*` di atas, dicek `services/newsletter_edition.py`.
    # Dicampur ditolak karena batas "full <= 4" jadi tidak berarti kalau `apac` (5) dan
    # `apac_full` (4) boleh dijumlah.
    # Template email merender semua `highlights`, kartu penuh, dan baris compact ("Also Noted");
    # bentuk lama sama-sama jadi kartu penuh dengan baris compact kosong.
    highlight: int | None = None
    apac: list[int] = []
    global_news: list[int] = []
    indonesia: list[int] = []

    highlights: list[int] = Field(
        default_factory=list,
        description=(
            f"Articles for the Highlights block, shown as full cards; at most {MAX_HIGHLIGHTS}. "
            "Replaces the "
            "legacy `highlight`; do not combine with the legacy fields."
        ),
    )
    apac_full: list[int] = Field(
        default_factory=list,
        description=(
            f"Asia Pacific articles shown as full cards (key points + summary); at most "
            f"{MAX_FULL_PER_SECTION}. "
            "Replaces the legacy `apac`; do not combine with the legacy fields."
        ),
    )
    apac_compact: list[int] = Field(
        default_factory=list,
        description=(
            "Asia Pacific articles shown as one-line rows built from stored metadata only "
            f"(no page fetch, no LLM call); at most {MAX_COMPACT_PER_SECTION}."
        ),
    )
    global_news_full: list[int] = Field(
        default_factory=list,
        description=(
            f"Global articles shown as full cards; at most {MAX_FULL_PER_SECTION}. Replaces the "
            "legacy `global_news`; "
            "do not combine with the legacy fields."
        ),
    )
    global_news_compact: list[int] = Field(
        default_factory=list,
        description=(
            "Global articles shown as one-line rows (no fetch, no LLM call); at most "
            f"{MAX_COMPACT_PER_SECTION}."
        ),
    )
    indonesia_full: list[int] = Field(
        default_factory=list,
        description=(
            f"Indonesia articles shown as full cards; at most {MAX_FULL_PER_SECTION}. Replaces the "
            "legacy `indonesia`; "
            "do not combine with the legacy fields."
        ),
    )
    indonesia_compact: list[int] = Field(
        default_factory=list,
        description=(
            "Indonesia articles shown as one-line rows (no fetch, no LLM call); at most "
            f"{MAX_COMPACT_PER_SECTION}."
        ),
    )

    regenerate: list[int] = Field(
        default_factory=list,
        description=(
            "Article ids whose cached summary is rebuilt (page fetched, LLM called again) "
            "instead of reused. Only affects articles shown as full cards or highlights."
        ),
    )
    period_start: datetime.date | None = Field(
        default=None,
        description=(
            "First day covered by the edition. Give both `period_start` and `period_end`, or "
            "neither: the default is the previous calendar month in the report time zone (WIB)."
        ),
    )
    period_end: datetime.date | None = Field(
        default=None, description="Last day (inclusive) covered by the edition; see `period_start`."
    )
    language: SummaryLanguage = Field(
        default=DEFAULT_SUMMARY_LANGUAGE,
        description=(
            "Language of the article summaries and key points: `id` (Indonesian, the default) "
            "or `en`. Headings, labels and the subject stay English. Summaries are cached per "
            "article and language, so an edition in one language never reuses or overwrites "
            "the other."
        ),
    )

    custom_css: str = ""
    custom_intro: str = ""
    custom_footer: str = ""
    notes: dict[str, str] = {}
    """Key = `str(article.id)`, sama pola kayak kode lama (dulu
    `str(ObjectId)`)."""
    include_clusters: bool = False
    cluster_days: int = 7

    @model_validator(mode="after")
    def _valid_shape(self) -> NewsletterSectionsBody:
        legacy = self.highlight is not None or any((self.apac, self.global_news, self.indonesia))
        tiered = any(
            (
                self.highlights,
                self.apac_full,
                self.apac_compact,
                self.global_news_full,
                self.global_news_compact,
                self.indonesia_full,
                self.indonesia_compact,
            )
        )
        if legacy and tiered:
            raise ValueError(
                "use either the legacy fields (highlight, apac, global_news, indonesia) or the "
                "tier fields (highlights, *_full, *_compact), not both"
            )
        # Template saat ini selalu merender satu highlight; dulu `highlight` wajib (422).
        if self.highlight is None and not self.highlights:
            raise ValueError("a highlight is required: set `highlight` or `highlights`")
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("set both period_start and period_end, or neither")
        if (
            self.period_start is not None
            and self.period_end is not None
            and self.period_start > self.period_end
        ):
            raise ValueError("period_start must not be after period_end")
        return self


class NewsletterListItem(BaseModel):
    id: int
    week: int
    year: int
    label: str
    """Label edisi: "October 2026" kalau periodenya terisi, selain itu "Week N, YYYY"
    (baris lama)."""
    period_start: datetime.date | None = None
    period_end: datetime.date | None = None
    generated_at: str
    created_by: str
    created_at: str
    sections: dict[str, object]


class NewsletterListResponse(BaseModel):
    newsletters: list[NewsletterListItem]
    total: int
    page: int
    page_size: int
