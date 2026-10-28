"""Bangun `dev_2026-10_minilm.npz`: vektor MiniLM judul unik fixture replay story (P5).

Pemakaian:
    FASTEMBED_CACHE_PATH=<cache> HF_HUB_OFFLINE=1 \
        uv run --with fastembed python tools/eval/embed_story_fixture.py <fixture.json> <out.npz>

`titles` disimpan sebagai array unicode (bukan object) supaya `np.load` tak butuh
`allow_pickle`; `vecs` float16 untuk menjaga ukuran (~1 MB), test me-normalisasi ulang.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from cti_enrich.relevance.embedder import get_embedder


def main(fixture: Path, out: Path) -> None:
    titles = sorted({a["title"] for a in json.loads(fixture.read_text())})
    vecs = get_embedder().embed(titles)
    np.savez_compressed(out, titles=np.array(titles, dtype=str), vecs=vecs.astype(np.float16))
    print(f"{len(titles)} judul unik -> {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
