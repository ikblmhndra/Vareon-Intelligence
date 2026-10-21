"""`cti_enrich.stages.alert.route_alerts` -- satu pesan per topik, dan satu thread rusak tidak
menghentikan topik sisanya (prod 2026-10-21: `Message thread not found` di topik `global`)."""

from __future__ import annotations

import pytest
import structlog.testing
from cti_enrich.routing import RoutingResult
from cti_enrich.stages import alert


def _result(*topics: str) -> RoutingResult:
    return RoutingResult(news_type="global", alert_topics=list(topics), msg_data="pesan")


def test_a_repeated_topic_is_sent_once(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(alert, "send_alert", lambda topic, msg: sent.append((topic, msg)))

    alert.route_alerts(_result("ot", "ot", "zero_day"))

    assert sent == [("ot", "pesan"), ("zero_day", "pesan")]


def test_a_broken_topic_does_not_stop_the_others_and_the_first_error_is_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []

    def fake_send(topic: str, msg: str) -> None:
        if topic == "global":
            raise RuntimeError("Message thread not found")
        sent.append(topic)

    monkeypatch.setattr(alert, "send_alert", fake_send)

    with structlog.testing.capture_logs() as logs, pytest.raises(RuntimeError, match="thread not"):
        alert.route_alerts(_result("global", "ot"))

    assert sent == ["ot"]
    failed = [entry for entry in logs if entry["event"] == "alert_send_failed"]
    assert [entry["topic"] for entry in failed] == ["global"]


def test_only_the_first_of_several_errors_is_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_send(topic: str, msg: str) -> None:
        raise RuntimeError(f"gagal {topic}")

    monkeypatch.setattr(alert, "send_alert", fake_send)

    with pytest.raises(RuntimeError, match="gagal global"):
        alert.route_alerts(_result("global", "ot"))
