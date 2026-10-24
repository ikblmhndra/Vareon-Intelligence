"""News of the Day -- gantiin `ScraperNews/supportFile/trendingNewsToday.py`.

Tiap hari, judul berita GLOBAL dan APAC hari itu dikelompokkan LLM jadi (maks 8)
topik, hasilnya dikirim sebagai dokumen JSON ke topik `notd`. Sumber daftar judul
dulu `supportFile/GLOBAL.txt` / `APAC.txt` (file yang ditambah `nlp.py` per artikel
lalu dikosongkan sesudah dikirim -- hilang kalau job gagal); sekarang dibaca dari
`articles` untuk satu hari lokal, jadi job yang gagal tinggal diulang.

Perbedaan dari skrip lama:
  - Prompt minta OBJEK `{"topics": [...]}` (bukan array telanjang): mode
    `response_format=json_object` tidak menerima array di level atas. Jawaban
    array telanjang tetap diterima.
  - Percobaan ulang atas JSON rusak dengan bentuk pesan yang dikuatkan
    (`llm_messages.build_messages`, persona "Kiro" di gateway dev) -- skrip lama
    memakai `.replace("json", "")` + dua kali `json.loads`.
  - Judul->URL dicocokkan persis, lalu tanpa peduli huruf besar/spasi ekstra
    (LLM sering merapikan spasi/kapitalisasi).
  - Hari tanpa artikel dilewati (kode lama tetap memanggil LLM dengan input kosong).
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from typing import Any

from cti_core.db.models.article import Article
from cti_core.llm.client import get_llm_client, parse_json_response, store_param
from cti_core.llm.usage import prompt_version
from cti_enrich.stages.llm_messages import build_messages
from sqlalchemy import select
from sqlalchemy.orm import Session

from cti_worker.reports.timeutil import local_day_bounds_utc

CATEGORIES = ("global", "apac")
"""Nilai `Article.news_type` yang jadi bahan (kode lama: GLOBAL.txt dan APAC.txt)."""
_MAX_ATTEMPTS = 3
_MAX_TOKENS = 6000  # reasoning `<think>` makan token duluan (lihat classify._MAX_TOKENS)

_SYSTEM_PROMPT = """
Analyze these security news headlines and group them into threat intelligence topics with maximum 8 topics. Output ONLY valid JSON, no other text.

Format: {"topics": [{"topic_name": "topic", "reference_title": ["headline1", "headline2"]}]}

Categories: vulnerabilities, threat actors, malware, data breaches, policy/compliance, infrastructure attacks, supply chain.

Output JSON only.
"""  # noqa: E501 -- prompt disalin apa adanya dari skrip lama
_PROMPT_VERSION = prompt_version(_SYSTEM_PROMPT)


@dataclass(frozen=True)
class NewsOfTheDay:
    category: str
    filename: str
    payload: list[dict[str, list[dict[str, str]]]]
    caption: str

    def as_json(self) -> str:
        return json.dumps(self.payload, indent=4, ensure_ascii=False)


def collect_titles(
    session: Session, local_day: datetime.date, offset_hours: int, category: str, *, limit: int
) -> list[tuple[str, str]]:
    """[(judul, url)] artikel `category` yang pertama kali terlihat di hari lokal itu."""
    start, end = local_day_bounds_utc(local_day, offset_hours)
    rows = session.execute(
        select(Article.title, Article.url)
        .where(
            Article.first_seen_at >= start,
            Article.first_seen_at < end,
            Article.news_type == category,
        )
        .order_by(Article.first_seen_at, Article.id)
        .limit(limit)
    ).all()
    return [(t, u) for t, u in rows]


def _topics_from(data: Any) -> list[dict[str, Any]]:
    """Terima `{"topics": [...]}` maupun array telanjang; buang entri yang bentuknya salah."""
    items = data.get("topics") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise json.JSONDecodeError("jawaban LLM tidak berisi daftar topik", "", 0)
    return [
        i
        for i in items
        if isinstance(i, dict)
        and isinstance(i.get("topic_name"), str)
        and isinstance(i.get("reference_title"), list)
    ]


def group_topics(titles: list[str]) -> list[dict[str, Any]]:
    """Satu panggilan LLM (dengan retry JSON). Kegagalan NAIK -- jangan diam-diam
    mengirim laporan kosong."""
    client, model = get_llm_client(task="news_of_the_day")
    user = "\n".join(titles)
    last_error: json.JSONDecodeError | None = None
    for attempt in range(_MAX_ATTEMPTS):
        completion = client.chat.completions.create(
            model=model,
            messages=build_messages(_SYSTEM_PROMPT, user, attempt=attempt, tag="headlines"),  # type: ignore[arg-type]
            temperature=0,
            n=1,
            max_tokens=_MAX_TOKENS,
            prompt_version=_PROMPT_VERSION,
            **store_param(),
        )
        try:
            return _topics_from(parse_json_response(completion.choices[0].message.content))
        except json.JSONDecodeError as e:
            last_error = e
    assert last_error is not None
    raise last_error


def build_payload(
    topics: list[dict[str, Any]], titles_urls: list[tuple[str, str]]
) -> list[dict[str, list[dict[str, str]]]]:
    """Format lama: `[{nama_topik: [{"title", "url"}, ...]}, ...]`. Judul yang
    dikembalikan LLM tapi tidak ada di daftar asli dibuang (sama dengan lama)."""
    exact = dict(titles_urls)
    loose = {" ".join(t.split()).casefold(): u for t, u in titles_urls}
    payload: list[dict[str, list[dict[str, str]]]] = []
    for topic in topics:
        refs: list[dict[str, str]] = []
        for title in topic["reference_title"]:
            title = str(title)
            url = exact.get(title) or loose.get(" ".join(title.split()).casefold())
            if url:
                refs.append({"title": title, "url": url.strip()})
        payload.append({topic["topic_name"]: refs})
    return payload


def build(
    session: Session, local_day: datetime.date, offset_hours: int, category: str, *, max_titles: int
) -> NewsOfTheDay | None:
    titles_urls = collect_titles(session, local_day, offset_hours, category, limit=max_titles)
    if not titles_urls:
        return None
    topics = group_topics([t for t, _ in titles_urls])
    label = category.upper()
    return NewsOfTheDay(
        category=category,
        filename=f"Top_News_{label}_{local_day.strftime('%d-%m-%Y')}.json",
        payload=build_payload(topics, titles_urls),
        caption=(
            f"\n<b>=== TOP 5 HOT TOPIC {label} NEWS TODAY ===</b>\n"
            "Here is the list of top topic mentioned today"
        ),
    )
