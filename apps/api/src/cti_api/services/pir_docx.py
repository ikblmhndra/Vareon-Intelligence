"""Port `build_docx()` dari `ScraperNewsWeb/scripts/export_pir_docx.py`
(fungsi murni, `data dict -> docx bytes`) -- SATU-SATUNYA salinan
sekarang. Kode lama py DUA salinan fungsi ini: satu di script standalone
`export_pir_docx.py` (dipanggil `pir_service.export_pir_to_docx_bytes` via
`importlib` runtime), satu lagi query builder yang sama persis diduplikat
di situ juga (`_build_article_query`, sekarang gantiin
`cti_core.db.repositories.pir._criteria_filters` + `AsyncArticleRepo.
list_filtered`). Di sini murni presentasi -- `data` shape-nya:

    {
      "pir": {title, description, priority, owner, status, criteria, ...},
      "articles": [ {title, url, source, posted_on, news_type,
                      threat_actors, impacted_industries, mentioned_countries,
                      analyst_note: {note, analyst, updated_at}}, ... ],
      "total_articles": int,
      "exported_at": ISO-string,
    }

sama persis kontrak lama -- dirakit `AsyncPIRRepo` + router `pir.py`,
BUKAN dibaca langsung dari Mongo kayak versi lama."""

from __future__ import annotations

import io
import re
from typing import Any


def build_docx(data: dict[str, Any]) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    doc = Document()
    pir = data["pir"]
    arts = data["articles"]

    h = doc.add_heading(level=1)
    h.alignment = WD_ALIGN_PARAGRAPH.LEFT
    h.add_run(f"PIR Report: {pir.get('title', 'Untitled')}")

    p_meta = doc.add_paragraph()
    meta_run = p_meta.add_run(
        f"Priority: {pir.get('priority', '—')}  ·  "
        f"Owner: {pir.get('owner', '—')}  ·  "
        f"Status: {pir.get('status', '—').upper()}  ·  "
        f"Generated: {data['exported_at'][:10]}"
    )
    meta_run.font.size = Pt(9)
    meta_run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    doc.add_paragraph()

    doc.add_heading("Intelligence Requirement", level=2)
    doc.add_paragraph(pir.get("description") or "No description provided.")

    doc.add_heading("Collection Criteria", level=2)
    criteria = pir.get("criteria", {})
    for label, key in [
        ("Threat Actors", "threat_actors"),
        ("Malware and tools", "malware"),
        ("Industries", "industries"),
        ("Countries", "countries"),
        ("News Types", "news_types"),
        ("Keywords", "keywords"),
        ("MITRE TTPs", "ttps"),
    ]:
        vals = criteria.get(key, [])
        if vals:
            p = doc.add_paragraph(style="List Bullet")
            r = p.add_run(f"{label}: ")
            r.bold = True
            p.add_run(", ".join(str(v) for v in vals))

    doc.add_heading("Coverage Summary", level=2)
    noted = sum(1 for a in arts if a.get("analyst_note", {}).get("note"))
    p = doc.add_paragraph()
    p.add_run(f"Total Matching Articles: {data['total_articles']}\n")
    p.add_run(f"Articles with Analyst Notes: {noted}\n")
    if arts:
        p.add_run(f"Date Range: {arts[-1].get('posted_on', '—')} → {arts[0].get('posted_on', '—')}")

    doc.add_paragraph()

    doc.add_heading(f"Matching Articles ({data['total_articles']})", level=2)

    for idx, a in enumerate(arts, 1):
        art_h = doc.add_heading(level=3)
        art_h.add_run(f"{idx}. {a.get('title', 'Untitled')}")

        meta_parts = [a.get("source", ""), a.get("posted_on", ""), a.get("news_type", "")]
        p_m = doc.add_paragraph()
        r_m = p_m.add_run("  ·  ".join(x for x in meta_parts if x))
        r_m.font.size = Pt(9)
        r_m.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

        if a.get("url"):
            p_u = doc.add_paragraph()
            r_u = p_u.add_run(a["url"])
            r_u.font.size = Pt(8)
            r_u.font.color.rgb = RGBColor(0x00, 0x78, 0xD4)

        tags = []
        if a.get("threat_actors"):
            tags.append("TA: " + ", ".join(a["threat_actors"]))
        if a.get("impacted_industries"):
            tags.append("IND: " + ", ".join(a["impacted_industries"]))
        if a.get("mentioned_countries"):
            tags.append("CTY: " + ", ".join(a["mentioned_countries"]))
        if tags:
            p_t = doc.add_paragraph()
            r_t = p_t.add_run(" | ".join(tags))
            r_t.font.size = Pt(9)

        note = a.get("analyst_note", {})
        if note and note.get("note"):
            p_n = doc.add_paragraph()
            r_lbl = p_n.add_run("Analyst Note: ")
            r_lbl.bold = True
            r_lbl.font.size = Pt(10)
            p_n.add_run(note["note"]).font.size = Pt(10)

            by_parts = []
            if note.get("analyst"):
                by_parts.append(f"By: {note['analyst']}")
            if note.get("updated_at"):
                by_parts.append(f"Saved: {note['updated_at'][:16].replace('T', ' ')}")
            if by_parts:
                p_by = doc.add_paragraph()
                r_by = p_by.add_run("  ".join(by_parts))
                r_by.font.size = Pt(8)
                r_by.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

        doc.add_paragraph()

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def export_filename(title: str, exported_at: str) -> str:
    safe_title = re.sub(r"[^a-zA-Z0-9]", "_", title or "PIR")[:40]
    date_part = exported_at[:10].replace("-", "")
    return f"PIR_{safe_title}_{date_part}.docx"
