"""Tests for the shared curated LLM model catalogue."""

import json

import pytest

from framework.llm import model_catalog


@pytest.fixture(autouse=True)
def clear_model_catalog_cache():
    model_catalog.load_model_catalog.cache_clear()
    yield
    model_catalog.load_model_catalog.cache_clear()


def test_default_models_exist_in_each_provider_catalogue():
    defaults = model_catalog.get_default_models()
    catalogue = model_catalog.get_models_catalogue()

    for provider_id, default_model in defaults.items():
        assert provider_id in catalogue
        assert any(model["id"] == default_model for model in catalogue[provider_id])


def test_find_model_returns_curated_token_limits():
    model = model_catalog.find_model("openai", "gpt-5.4")

    assert model is not None
    assert model["label"] == "GPT-5.4 - Best intelligence"
    assert model["max_tokens"] == 128000
    assert model["max_context_tokens"] == 960000


def test_anthropic_curated_limits_track_documented_caps_with_safe_input_budget():
    haiku = model_catalog.find_model("anthropic", "claude-haiku-4-5-20251001")
    sonnet_45 = model_catalog.find_model("anthropic", "claude-sonnet-4-5-20250929")
    opus_46 = model_catalog.find_model("anthropic", "claude-opus-4-6")

    assert haiku["max_tokens"] == 64000
    assert haiku["max_context_tokens"] == 136000
    assert sonnet_45["max_tokens"] == 64000
    assert sonnet_45["max_context_tokens"] == 136000
    assert opus_46["max_tokens"] == 128000
    assert opus_46["max_context_tokens"] == 872000


def test_find_model_any_provider_returns_provider_and_model():
    provider_id, model = model_catalog.find_model_any_provider("google/gemini-2.5-pro")

    assert provider_id == "openrouter"
    assert model["max_context_tokens"] == 900000


def test_get_preset_returns_subscription_specific_limits():
    preset = model_catalog.get_preset("kimi_code")

    assert preset is not None
    assert preset["provider"] == "kimi"
    assert preset["model"] == "kimi-k2.5"
    assert preset["max_tokens"] == 32768
    assert preset["max_context_tokens"] == 240000
    assert preset["api_base"] == "https://api.kimi.com/coding"


def test_load_model_catalog_rejects_duplicate_model_ids(tmp_path, monkeypatch):
    bad_catalog = {
        "schema_version": 1,
        "providers": {
            "anthropic": {
                "default_model": "dup-model",
                "models": [
                    {
                        "id": "dup-model",
                        "label": "First",
                        "recommended": True,
                        "max_tokens": 1,
                        "max_context_tokens": 1,
                    },
                    {
                        "id": "dup-model",
                        "label": "Second",
                        "recommended": False,
                        "max_tokens": 1,
                        "max_context_tokens": 1,
                    },
                ],
            }
        },
    }
    bad_path = tmp_path / "model_catalog.json"
    bad_path.write_text(json.dumps(bad_catalog), encoding="utf-8")

    monkeypatch.setattr(model_catalog, "MODEL_CATALOG_PATH", bad_path)

    with pytest.raises(model_catalog.ModelCatalogError, match="Duplicate model id"):
        model_catalog.load_model_catalog()
