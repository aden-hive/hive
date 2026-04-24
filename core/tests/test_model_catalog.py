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


def test_groq_catalog_tracks_current_production_models():
    groq_default = model_catalog.get_default_models()["groq"]
    groq_models = model_catalog.get_models_catalogue()["groq"]

    assert groq_default == "openai/gpt-oss-120b"
    assert [model["id"] for model in groq_models] == [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
    ]
    assert groq_models[0]["max_tokens"] == 65536
    assert groq_models[0]["max_context_tokens"] == 131072


def test_cerebras_catalog_tracks_public_models_endpoint():
    cerebras_default = model_catalog.get_default_models()["cerebras"]
    cerebras_models = model_catalog.get_models_catalogue()["cerebras"]

    assert cerebras_default == "gpt-oss-120b"
    assert [model["id"] for model in cerebras_models] == [
        "gpt-oss-120b",
        "zai-glm-4.7",
        "qwen-3-235b-a22b-instruct-2507",
    ]
    assert all(model["max_tokens"] == 40960 for model in cerebras_models)
    assert all(model["max_context_tokens"] == 131072 for model in cerebras_models)


def test_minimax_catalog_tracks_current_non_legacy_text_models():
    minimax_default = model_catalog.get_default_models()["minimax"]
    minimax_models = model_catalog.get_models_catalogue()["minimax"]

    assert minimax_default == "MiniMax-M2.7"
    assert [model["id"] for model in minimax_models] == [
        "MiniMax-M2.7",
        "MiniMax-M2.5",
    ]
    assert all(model["max_context_tokens"] == 180000 for model in minimax_models)
    assert all(model["max_tokens"] == 40960 for model in minimax_models)


def test_mistral_catalog_tracks_current_curated_models():
    mistral_default = model_catalog.get_default_models()["mistral"]
    mistral_models = model_catalog.get_models_catalogue()["mistral"]

    assert mistral_default == "mistral-large-2512"
    assert [model["id"] for model in mistral_models] == [
        "mistral-large-2512",
        "mistral-medium-2508",
        "mistral-small-2603",
        "codestral-2508",
    ]
    assert mistral_models[0]["max_context_tokens"] == 256000
    assert mistral_models[1]["max_context_tokens"] == 128000
    assert mistral_models[2]["max_context_tokens"] == 256000
    assert mistral_models[3]["max_context_tokens"] == 128000


def test_together_catalog_tracks_current_serverless_recommendations():
    together_default = model_catalog.get_default_models()["together"]
    together_models = model_catalog.get_models_catalogue()["together"]

    assert together_default == "deepseek-ai/DeepSeek-V3.1"
    assert [model["id"] for model in together_models] == [
        "deepseek-ai/DeepSeek-V3.1",
        "Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8",
        "openai/gpt-oss-120b",
        "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    ]
    assert together_models[0]["max_context_tokens"] == 128000
    assert together_models[1]["max_context_tokens"] == 262144
    assert together_models[2]["max_context_tokens"] == 128000
    assert together_models[3]["max_context_tokens"] == 131072


def test_deepseek_catalog_tracks_current_api_models():
    deepseek_default = model_catalog.get_default_models()["deepseek"]
    deepseek_models = model_catalog.get_models_catalogue()["deepseek"]

    assert deepseek_default == "deepseek-chat"
    assert [model["id"] for model in deepseek_models] == [
        "deepseek-chat",
        "deepseek-reasoner",
    ]
    assert deepseek_models[0]["max_tokens"] == 8192
    assert deepseek_models[0]["max_context_tokens"] == 128000
    assert deepseek_models[1]["max_tokens"] == 64000
    assert deepseek_models[1]["max_context_tokens"] == 128000


def test_openrouter_catalog_tracks_current_frontier_set():
    openrouter_default = model_catalog.get_default_models()["openrouter"]
    openrouter_models = model_catalog.get_models_catalogue()["openrouter"]

    assert openrouter_default == "openai/gpt-5.4"
    assert [model["id"] for model in openrouter_models] == [
        "openai/gpt-5.4",
        "anthropic/claude-sonnet-4.6",
        "anthropic/claude-opus-4.6",
        "google/gemini-3.1-pro-preview-customtools",
        "qwen/qwen3.6-plus",
        "z-ai/glm-5v-turbo",
        "z-ai/glm-5.1",
        "minimax/minimax-m2.7",
        "xiaomi/mimo-v2-pro",
    ]
    assert openrouter_models[0]["max_tokens"] == 128000
    assert openrouter_models[0]["max_context_tokens"] == 872000
    assert openrouter_models[1]["max_context_tokens"] == 872000
    assert openrouter_models[2]["max_context_tokens"] == 872000
    assert openrouter_models[3]["max_context_tokens"] == 872000
    assert openrouter_models[4]["max_context_tokens"] == 240000


def test_find_model_any_provider_returns_provider_and_model():
    provider_id, model = model_catalog.find_model_any_provider("google/gemini-3.1-pro-preview-customtools")

    assert provider_id == "openrouter"
    assert model["max_context_tokens"] == 872000


def test_get_preset_returns_subscription_specific_limits():
    preset = model_catalog.get_preset("kimi_code")

    assert preset is not None
    assert preset["provider"] == "kimi"
    assert preset["model"] == "kimi-k2.5"
    assert preset["max_tokens"] == 32768
    assert preset["max_context_tokens"] == 240000
    assert preset["api_base"] == "https://api.kimi.com/coding"


def test_minimax_preset_uses_current_default_model():
    preset = model_catalog.get_preset("minimax_code")

    assert preset is not None
    assert preset["model"] == "MiniMax-M2.7"
    assert preset["max_tokens"] == 40960
    assert preset["max_context_tokens"] == 180800


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
