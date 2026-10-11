"""Unit test `cti_core.llm.client` -- pindah dari `cti_enrich.llm` (Fase
7.5, "buang duplikasi"), belum pernah punya test khusus sebelum ini
walau sekarang dipakai 7 caller (`cti_enrich.stages.classify`/
`extract_ttps` + `apps/api`'s `ta_profile`/`exec_brief`/`cve_email`/
`newsletter`/`recap`)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from cti_core.config import LlmSettings
from cti_core.llm import client as llm_client


def test_parse_json_response_dict_passthrough() -> None:
    assert llm_client.parse_json_response({"a": 1}) == {"a": 1}


def test_parse_json_response_plain_json() -> None:
    assert llm_client.parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_json_response_strips_think_block() -> None:
    raw = '<think>reasoning about the answer</think>{"a": 1}'
    assert llm_client.parse_json_response(raw) == {"a": 1}


def test_parse_json_response_strips_code_fence() -> None:
    raw = '```json\n{"a": 1}\n```'
    assert llm_client.parse_json_response(raw) == {"a": 1}


def test_parse_json_response_extracts_braces_from_surrounding_text() -> None:
    raw = 'Sure, here is the JSON: {"a": 1} Hope that helps!'
    assert llm_client.parse_json_response(raw) == {"a": 1}


def test_parse_json_response_empty_raises() -> None:
    with pytest.raises(json.JSONDecodeError):
        llm_client.parse_json_response("")
    with pytest.raises(json.JSONDecodeError):
        llm_client.parse_json_response(None)


def test_parse_json_response_unparseable_raises() -> None:
    with pytest.raises(json.JSONDecodeError):
        llm_client.parse_json_response("not json at all, no braces here")


def test_get_llm_client_default_openai() -> None:
    settings = LlmSettings(provider="openai", api_key="sk-test")
    client, model = llm_client.get_llm_client(settings=settings)
    assert model == "gpt-4o"
    assert client.api_key == "sk-test"


def test_get_llm_client_custom_base_url() -> None:
    settings = LlmSettings(provider="openai", api_key="sk-test", url="https://gateway.local/v1")
    client, _ = llm_client.get_llm_client(settings=settings)
    assert str(client.base_url) == "https://gateway.local/v1/"


def test_get_llm_client_unknown_provider_raises() -> None:
    settings = LlmSettings.model_construct(provider="bogus", api_key="x", url="", model="")
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        llm_client.get_llm_client(settings=settings)


def test_store_param_true_for_plain_openai() -> None:
    settings = LlmSettings(provider="openai", api_key="sk-test")
    assert llm_client.store_param(settings) == {"store": True}


def test_store_param_false_when_custom_url() -> None:
    settings = LlmSettings(provider="openai", api_key="sk-test", url="https://gateway.local/v1")
    assert llm_client.store_param(settings) == {}


def test_store_param_false_for_non_openai_provider() -> None:
    settings = LlmSettings(provider="deepseek", api_key="sk-test")
    assert llm_client.store_param(settings) == {}


def _completion(usage: object) -> SimpleNamespace:
    return SimpleNamespace(choices=[], usage=usage)


def test_usage_from_reads_the_three_counters() -> None:
    usage = SimpleNamespace(prompt_tokens=120, completion_tokens=30, total_tokens=150)
    assert llm_client.usage_from(_completion(usage)) == {
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "total_tokens": 150,
    }


def test_usage_from_without_usage_is_empty_and_does_not_raise() -> None:
    """Gateway dev kadang membuang `usage` (atau mengirim `null`): hasilnya `{}`, bukan error --
    pemanggil sudah membayar token-nya, jangan sampai pencatatan menggagalkan recap."""
    assert llm_client.usage_from(_completion(None)) == {}
    assert llm_client.usage_from(SimpleNamespace(choices=[])) == {}  # atribut `usage` tidak ada
    assert llm_client.usage_from(None) == {}


def test_usage_from_partial_usage_keeps_only_the_integer_fields() -> None:
    missing_total = SimpleNamespace(prompt_tokens=120, completion_tokens=30)
    assert llm_client.usage_from(_completion(missing_total)) == {
        "prompt_tokens": 120,
        "completion_tokens": 30,
    }
    with_nulls = SimpleNamespace(prompt_tokens=None, completion_tokens=30, total_tokens=None)
    assert llm_client.usage_from(_completion(with_nulls)) == {"completion_tokens": 30}


def test_usage_from_accepts_plain_dicts() -> None:
    """Gateway kadang mengembalikan objek yang sudah di-parse (lihat `parse_json_response`)."""
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert llm_client.usage_from({"usage": usage}) == usage
    assert llm_client.usage_from(_completion(usage)) == usage
    assert llm_client.usage_from({"usage": None}) == {}


def test_usage_from_drops_values_that_are_not_integers() -> None:
    usage = SimpleNamespace(prompt_tokens="lots", completion_tokens=[1], total_tokens=2.5)
    assert llm_client.usage_from(_completion(usage)) == {}
    assert llm_client.usage_from(_completion("not an object at all")) == {}
