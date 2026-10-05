"""Jinja environment untuk email/newsletter: autoescape AKTIF (judul/ringkasan hasil scraping &
LLM tidak boleh jadi HTML). Field HTML buatan analis dipasang `| safe` eksplisit di template."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape


def http_url(value: object) -> str:
    """Hanya http(s); selain itu (javascript:, data:, ...) jadi '#'."""
    url = str(value or "").strip()
    return url if urlparse(url).scheme in ("http", "https") else "#"


def make_env(template_dir: Path | str) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "xml"])
    )
    env.filters["http_url"] = http_url
    return env
