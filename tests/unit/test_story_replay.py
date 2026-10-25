"""Replay dev (P3): seluruh artikel dev lewat `resolve` berurutan.

Fixture `tests/fixtures/story_replay/dev_2026-10.json`: 1.401 artikel dev
(2026-09-26 .. 2026-10-24) berurutan `first_seen_at`, tiap item `{id, title, source,
scraper_id, first_seen_at, cves}` dengan `cves` dari `article_cves`. Diekspor read-only
dari dev pada 2026-10-25. `first_seen_at` dipakai sebagai waktu kedatangan.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from cti_core.config import StorySettings
from cti_core.db.repositories.story import StoryCandidate, StoryMember
from cti_enrich.story.resolver import ArticleKeys, key_cves, resolve

FIXTURE = Path(__file__).parent.parent / "fixtures" / "story_replay" / "dev_2026-10.json"


def _replay() -> tuple[dict[int, int], Counter[int], int]:
    cfg = StorySettings()
    stories: list[StoryCandidate] = []
    story_of: dict[int, int] = {}
    follow_ups = 0
    for a in json.loads(FIXTURE.read_text()):
        at = datetime.fromisoformat(a["first_seen_at"])
        cves = key_cves(a["cves"], cfg.max_key_cves)  # produksi: story hanya simpan CVE kunci
        match = resolve(ArticleKeys(a["title"], a["source"], cves, at), stories, cfg)
        member = StoryMember(a["title"], a["source"])
        if match is None:
            sid = len(stories) + 1
            stories.append(StoryCandidate(sid, cves, at, at, [member], False))
        else:
            sid = match.story_id
            old = stories[sid - 1]
            stories[sid - 1] = StoryCandidate(
                sid,
                old.cve_ids | cves,
                old.first_seen_at,
                max(old.last_seen_at, at),
                [*old.members, member],
                old.has_classify,
            )
            follow_ups += 1
        story_of[a["id"]] = sid
    return story_of, Counter(story_of.values()), follow_ups


def test_dev_replay():
    story_of, sizes, follow_ups = _replay()
    top = sizes.most_common(10)
    msg = f"top-10 story sizes: {top}; follow-ups: {follow_ups}"
    assert sizes[story_of[1302]] >= 22, msg
    assert sizes[story_of[162]] >= 14, msg
    assert sizes[story_of[713]] >= 8, msg
    assert len({story_of[i] for i in (956, 957, 958)}) == 3, msg
    assert 150 <= follow_ups <= 220, msg
