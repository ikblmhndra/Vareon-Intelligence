"""Stage: kirim alert -- TERPISAH TOTAL dari `persist.py` (plan §5), beda
dari `_sendAlert()` lama yang nulis DB di tengah proses kirim Telegram.
Kegagalan kirim di sini TIDAK BOLEH bikin artikel gak kesimpen -- caller
(`pipeline.py`) manggil `persist()` DULU, `route_alerts()` BELAKANGAN.

`build_message_base()` = bagian AWAL `msg_data` (`nlp.py:333-339` + baris
Funding `:429-432`) yang `routing.route()` butuh SEBELUM mutusin cabang --
`route()` sendiri yang nambahin baris Threat Actor/Country-People/TTP
(lihat `routing.py`)."""

from __future__ import annotations

import html

from cti_alerts.telegram import send_alert

from cti_enrich.routing import RoutingResult


def build_message_base(
    *,
    script_name: str,
    title: str,
    posted_on: str,
    url: str,
    industries_string: str,
    funding_keyword: str | None,
) -> str:
    # Telegram `parse_mode="HTML"` menolak seluruh pesan kalau judul feed memuat `<tag>` yang tak
    # dikenal; judul/URL/industri berasal dari luar (feed, LLM), jadi di-escape seperti `cve_alert`.
    msg = f"""
        === <b>{html.escape(script_name.upper(), quote=False)}</b> ===
<b>Title</b>: {html.escape(title, quote=False)}
<b>Posted On</b>: {posted_on}
<b>Link</b>: <a href="{html.escape(url)}">Read Now</a>
<b>Impacted Industries</b>: {html.escape(industries_string, quote=False)}
"""
    if funding_keyword:
        msg += f"<b>Funding Related Article</b>: True ({funding_keyword})\n"
    return msg


def route_alerts(routing_result: RoutingResult) -> None:
    for topic in routing_result.alert_topics:
        send_alert(topic, routing_result.msg_data)
