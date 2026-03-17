"""Interactive LLM provider selector with fallback options."""

import asyncio
import json
import logging
import os
from typing import Any

from litellm import completion

from framework.config import (
    get_available_providers,
    format_provider_menu,
    save_provider_selection,
    get_api_key,
    get_hive_config,
)

logger = logging.getLogger(__name__)


async def test_provider(provider_id: str, config: dict) -> tuple[bool, str | None]:
    """Test if a provider actually works (has credits, valid key).

    Returns:
        Tuple of (works, error_message)
    """
    try:
        model = config["default_model"]

        # Format model correctly
        if provider_id == "gemini":
            model_name = model
        else:
            model_name = f"{provider_id}/{model}"

        # Get API key
        api_key = config.get("api_key") or get_api_key(provider_id)
        if not api_key:
            return False, "No API key found"

        # Make a minimal test call
        response = await asyncio.to_thread(
            completion,
            model=model_name,
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5,
            api_key=api_key,
        )

        if response and response.choices:
            return True, None
        return False, "No response"

    except Exception as e:
        error_str = str(e).lower()
        if "credit" in error_str or "balance" in error_str:
            return False, "No credits available"
        if "invalid" in error_str or "auth" in error_str or "key" in error_str:
            return False, "Invalid API key"
        if "rate" in error_str or "limit" in error_str:
            return False, "Rate limited"
        return False, str(e)[:100]


async def test_provider_with_model(provider_id: str, model: str, api_key: str) -> tuple[bool, str | None]:
    """Test a specific model for a provider.

    Returns:
        Tuple of (works, error_message)
    """
    try:
        # Format model correctly
        if provider_id == "gemini":
            model_name = model
        else:
            model_name = f"{provider_id}/{model}"

        # Make a minimal test call
        response = await asyncio.to_thread(
            completion,
            model=model_name,
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5,
            api_key=api_key,
        )

        if response and response.choices:
            return True, None
        return False, "No response"

    except Exception as e:
        error_str = str(e).lower()
        if "credit" in error_str or "balance" in error_str:
            return False, "No credits available"
        if "invalid" in error_str or "auth" in error_str or "key" in error_str:
            return False, "Invalid API key"
        if "rate" in error_str or "limit" in error_str:
            return False, "Rate limited"
        return False, str(e)[:100]


async def get_working_providers() -> dict[str, dict]:
    """Get all providers that actually work (have credits, valid keys)."""
    all_providers = get_available_providers()
    working = {}

    print("\n🔍 Testing available providers...")

    for provider_id, config in all_providers.items():
        print(f"  Testing {config['name']}... ", end="", flush=True)

        if config["status"] == "available" and config.get("free_tier"):
            # Free tier providers are assumed working
            print("✅ Available")
            working[provider_id] = config
        else:
            # Test if they actually work
            works, error = await test_provider(provider_id, config)
            if works:
                print("✅ Working")
                working[provider_id] = config
            else:
                print(f"❌ {error}")

    return working


async def get_working_models(provider_id: str, api_key: str, models: list[str]) -> list[str]:
    """Test which models actually work for a provider."""
    working = []
    print(f"\n  Testing models for {provider_id}...")

    for model in models:
        print(f"    Testing {model}... ", end="", flush=True)
        works, error = await test_provider_with_model(provider_id, model, api_key)
        if works:
            print("✅")
            working.append(model)
        else:
            print(f"❌ ({error})")

    return working


async def interactive_fallback(original_provider: str, error: Exception) -> dict | None:
    """Show interactive menu of working providers for user to choose.

    Args:
        original_provider: The provider that failed
        error: The error that occurred

    Returns:
        Selected provider config or None to abort
    """
    print("\n" + "=" * 60)
    print(f"⚠️  {original_provider.upper()} FAILED")
    print("=" * 60)
    print(f"Error: {error}")
    print("\nThis could be due to:")
    print("• No credits in your account")
    print("• Invalid API key")
    print("• Rate limiting")

    # Find working providers
    print("\n🔍 Checking for alternative providers...")
    working = await get_working_providers()

    if not working:
        print("\n❌ No alternative providers found.")
        print("Please add credits to your account or configure another provider.")
        return None

    # Show menu
    print("\n✅ Found working alternatives:")
    providers_list = list(working.items())

    for idx, (_provider_id, info) in enumerate(providers_list, 1):
        free_tag = " 🆓 FREE" if info.get("free_tier") else ""
        print(f"\n{idx}. {info['name']}{free_tag}")
        print(f"   Models: {', '.join(info['models'][:3])}")

    print(f"\n{len(providers_list) + 1}. Abort and show error")
    print("0. Retry with original provider")

    # Get user choice
    while True:
        try:
            choice = input(f"\nSelect option (0-{len(providers_list) + 1}): ")
            if not choice.strip():
                continue

            choice = int(choice)

            if choice == 0:
                print("\n🔄 Retrying with original provider...")
                return {"retry": True}

            if 1 <= choice <= len(providers_list):
                selected_id, selected_config = providers_list[choice - 1]
                print(f"\n✅ Selected: {selected_config['name']}")

                # Get API key
                api_key = selected_config.get("api_key") or get_api_key(selected_id)

                # Test which models actually work
                working_models = await get_working_models(
                    selected_id,
                    api_key,
                    selected_config["models"]
                )

                if not working_models:
                    print("\n❌ No working models found for this provider.")
                    continue

                # Ask for model selection
                print(f"\nAvailable models for {selected_config['name']}:")
                for midx, model in enumerate(working_models, 1):
                    print(f"  {midx}. {model}")

                model_choice = input(
                    f"Select model (1-{len(working_models)}, Enter for default): "
                )

                selected_model = working_models[0]  # Default to first
                if model_choice.strip():
                    try:
                        model_idx = int(model_choice) - 1
                        if 0 <= model_idx < len(working_models):
                            selected_model = working_models[model_idx]
                    except ValueError:
                        pass

                # Save selection
                save_provider_selection(selected_id, selected_model)

                return {
                    "provider": selected_id,
                    "model": selected_model,
                    "api_key": api_key,
                    "name": selected_config["name"],
                }

            if choice == len(providers_list) + 1:
                print("\n❌ Aborting. Showing original error.")
                return None

        except ValueError:
            print("Invalid input. Please enter a number.")
        except KeyboardInterrupt:
            print("\n❌ Interrupted.")
            return None


async def quick_provider_check() -> dict | None:
    """Quick check of providers at startup.

    Returns:
        Recommended provider or None
    """
    configured = get_hive_config().get("llm", {})
    if configured.get("provider"):
        # Already configured, skip
        return None

    print("\n🔍 Checking for available providers...")
    working = await get_working_providers()

    if not working:
        print("\n❌ No working providers found.")
        return None

    # Prefer free tier providers
    free_providers = {k: v for k, v in working.items() if v.get("free_tier")}
    if free_providers:
        # Return the first free provider
        provider_id = next(iter(free_providers))
        provider = free_providers[provider_id]

        # Get API key
        api_key = provider.get("api_key") or get_api_key(provider_id)

        # Test which models work
        working_models = await get_working_models(
            provider_id,
            api_key,
            provider["models"]
        )

        if working_models:
            default_model = working_models[0]
            print(f"\n✅ Auto-selected {provider['name']} (free tier)")
            print(f"   Model: {default_model}")

            save_provider_selection(provider_id, default_model)

            return {
                "provider": provider_id,
                "model": default_model,
                "api_key": api_key,
                "name": provider["name"],
            }

    return None


async def interactive_provider_selection() -> dict | None:
    """Interactive provider selection at startup.

    Returns:
        Selected provider config or None
    """
    print("\n" + "=" * 60)
    print("🤖 LLM PROVIDER SELECTION")
    print("=" * 60)

    # Get all available providers
    all_providers = get_available_providers()

    if not all_providers:
        print("\n❌ No providers configured.")
        print("Please set up API keys in your environment.")
        return None

    # Show menu
    print("\nAvailable providers:")
    providers_list = list(all_providers.items())

    for idx, (provider_id, info) in enumerate(providers_list, 1):
        free_tag = " 🆓 FREE" if info.get("free_tier") else ""
        status = "✅" if info.get("status") == "available" else "⚠️"
        print(f"\n{idx}. {status} {info['name']}{free_tag}")
        print(f"   Models: {', '.join(info['models'][:3])}")

    print(f"\n{len(providers_list) + 1}. Skip for now")

    # Get user choice
    while True:
        try:
            choice = input(f"\nSelect provider (1-{len(providers_list) + 1}): ")
            if not choice.strip():
                continue

            choice = int(choice)

            if 1 <= choice <= len(providers_list):
                selected_id, selected_config = providers_list[choice - 1]
                print(f"\n✅ Selected: {selected_config['name']}")

                # Get API key if not already set
                api_key = selected_config.get("api_key") or get_api_key(selected_id)

                if not api_key:
                    print(f"\nEnter your {selected_config['name']} API key:")
                    api_key = input("API key: ").strip()
                    if not api_key:
                        print("❌ No API key provided.")
                        continue

                # Test which models work
                working_models = await get_working_models(
                    selected_id,
                    api_key,
                    selected_config["models"]
                )

                if not working_models:
                    print(f"\n❌ No working models found for {selected_config['name']}.")
                    print("Please check your API key and try again.")
                    continue

                # Ask for model selection
                print(f"\nAvailable models for {selected_config['name']}:")
                for midx, model in enumerate(working_models, 1):
                    print(f"  {midx}. {model}")

                model_choice = input(
                    f"Select model (1-{len(working_models)}, Enter for default): "
                )

                selected_model = working_models[0]  # Default to first
                if model_choice.strip():
                    try:
                        model_idx = int(model_choice) - 1
                        if 0 <= model_idx < len(working_models):
                            selected_model = working_models[model_idx]
                    except ValueError:
                        pass

                # Save selection
                save_provider_selection(selected_id, selected_model)

                return {
                    "provider": selected_id,
                    "model": selected_model,
                    "api_key": api_key,
                    "name": selected_config["name"],
                }

            if choice == len(providers_list) + 1:
                print("\n⏭️  Skipping provider selection.")
                return None

        except ValueError:
            print("Invalid input. Please enter a number.")
        except KeyboardInterrupt:
            print("\n❌ Interrupted.")
            return None