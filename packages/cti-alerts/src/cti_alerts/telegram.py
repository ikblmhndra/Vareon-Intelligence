"""SATU `send_alert(topic, msg)` -- gantiin 14 fungsi `send_alert_*` di
`ScraperNews/modules/telegramAlert.py`, tiap fungsi bikin `telegram.Bot(...)`
+ event loop sendiri, semua nelan exception (`except Exception: print(e);
pass`) jadi config Telegram yang rusak gak pernah ketauan.

Topic -> thread Telegram lewat `TelegramSettings.thread_ids` (dict bebas,
BUKAN 17 field `thread_id_*` terpisah kayak `config.yml` lama). Topic yang
dipakai `cti_enrich.routing.route()`: global, apac, apac_indo, apt, ot,
zero_day, data_breach, data_breach_indo, vendor_report, tech_stack,
tech_stack_unrelated, best_practice -- lihat `.env.example` buat daftar
lengkap.

Beda dari kode lama: gak nelan exception. Kegagalan Telegram (token salah,
thread_id gak valid, dst) HARUS keliatan, bukan `pass` diam-diam -- ini aman
dilakukan karena pipeline `cti_enrich` udah misahin `persist` (Fase 5 §5.7,
selalu jalan duluan) dari `route_alerts` (§5.8) TOTAL; kegagalan alert gak
lagi bisa nyulik penulisan artikel kayak `_sendAlert()` lama yang gabungin
dua-duanya. Caller (Celery task, Fase 6) yang mutusin mau retry/log,
bukan modul ini yang diam-diam nutupin."""

from __future__ import annotations

import asyncio
from typing import Any

import telegram
from cti_core.config import TelegramSettings
from cti_core.runtime_secrets.overlay import effective_settings


class UnknownAlertTopic(Exception):
    """Topic dipanggil tapi gak ada di `TelegramSettings.thread_ids` --
    typo topic HARUS keliatan pas dipanggil, bukan diam-diam kirim ke
    channel default yang salah."""


async def _send(settings: TelegramSettings, msg: str, thread_id: int | None) -> None:
    bot = telegram.Bot(token=settings.bot_token)
    kwargs: dict[str, Any] = {"chat_id": settings.chat_id, "text": msg, "parse_mode": "HTML"}
    if thread_id:
        kwargs["message_thread_id"] = thread_id
    await bot.send_message(**kwargs)


def send_alert(topic: str, msg: str, *, settings: TelegramSettings | None = None) -> None:
    settings = settings or effective_settings().telegram
    if topic not in settings.thread_ids:
        raise UnknownAlertTopic(
            f"topic alert '{topic}' gak terdaftar di TELEGRAM__THREAD_IDS -- "
            f"daftar yang ada: {sorted(settings.thread_ids)}"
        )
    thread_id = settings.thread_ids[topic] or None
    asyncio.run(_send(settings, msg, thread_id))


async def _send_document(
    settings: TelegramSettings, path: str, caption: str, thread_id: int | None
) -> None:
    bot = telegram.Bot(token=settings.bot_token)
    with open(path, "rb") as f:
        kwargs: dict[str, Any] = {
            "chat_id": settings.chat_id,
            "document": f,
            "caption": caption,
            "parse_mode": "HTML",
        }
        if thread_id:
            kwargs["message_thread_id"] = thread_id
        await bot.send_document(**kwargs)


def send_file(
    topic: str, path: str, caption: str, *, settings: TelegramSettings | None = None
) -> None:
    """Port `send_file`/`send_report_file`/`send_alert_news_of_the_day` --
    ketiganya sama-sama "kirim dokumen ke satu thread", beda cuma topic-nya."""
    settings = settings or effective_settings().telegram
    if topic not in settings.thread_ids:
        raise UnknownAlertTopic(
            f"topic alert '{topic}' gak terdaftar di TELEGRAM__THREAD_IDS -- "
            f"daftar yang ada: {sorted(settings.thread_ids)}"
        )
    thread_id = settings.thread_ids[topic] or None
    asyncio.run(_send_document(settings, path, caption, thread_id))


TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024


def send_document(
    topic: str,
    filename: str,
    content: str | bytes,
    caption: str = "",
    *,
    settings: TelegramSettings | None = None,
) -> None:
    """Kirim `content` sebagai dokumen `filename` -- tanpa file sementara di CWD
    (skrip lama menulis `supportFile/...` lalu memindah/menghapusnya; run yang
    mati di tengah meninggalkan sisa yang tercampur ke run berikutnya).

    Caption dokumen dibatasi 1024 karakter oleh Telegram: caption yang lebih
    panjang dikirim sebagai PESAN terpisah dan dokumennya tanpa caption, alih-alih
    ditolak API. Nama file dipotong ke basename (bukan path)."""
    import tempfile
    from pathlib import Path

    name = Path(filename or "document.txt").name
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        if len(caption) <= CAPTION_LIMIT:
            send_file(topic, str(path), caption, settings=settings)
        else:
            send_alert(topic, caption, settings=settings)
            send_file(topic, str(path), "", settings=settings)
