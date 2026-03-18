"""
Model management CLI commands for Hive.
Allows users to view and change LLM models.
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

from framework.config import get_hive_config, HIVE_CONFIG_FILE
from framework.llm.provider_models import (
    get_provider_models,
    format_model_menu,
    get_model_info,
    PROVIDER_MODELS
)


def list_models(args):
    """List available models for all providers or a specific provider."""
    provider = args.provider if hasattr(args, 'provider') else None
    
    if provider:
        provider = provider.lower()
        if provider not in PROVIDER_MODELS:
            print(f" Provider '{provider}' not found")
            print(f"Available providers: {', '.join(PROVIDER_MODELS.keys())}")
            return
        
        print(format_model_menu(provider))
    else:
        print("\n Available Providers and Models:")
        print("=" * 60)
        for prov, models in PROVIDER_MODELS.items():
            print(f"\n{prov.upper()}:")
            for model in models[:3]:  # Show first 3 models
                tier = "🆓" if model["tier"] == "free" else "💰"
                speed_icon = {"fast": "⚡", "balanced": "⚖️", "slow": "🐢"}.get(model["speed"], "")
                quality_icon = {
                    "basic": "🔹", "good": "🔸", 
                    "better": "⭐", "best": "🌟🌟"
                }.get(model["quality"], "")
                print(f"  • {model['name']} {tier}{speed_icon}{quality_icon} - {model['description']}")
            if len(models) > 3:
                print(f"  ... and {len(models) - 3} more")
        print("\nUse 'hive model list --provider <name>' for detailed view")


def show_current_model(args):
    """Show the currently configured model."""
    config = get_hive_config().get("llm", {})
    provider = config.get("provider", "not set")
    model = config.get("model", "not set")
    model_display = config.get("model_display", model)
    env_var = config.get("api_key_env_var", "Not set")
    
    print("\n Current Model Configuration:")
    print("=" * 40)
    print(f"Provider:     {provider}")
    print(f"Model:        {model_display}")
    print(f"API Key Env:  {env_var}")
    print(f"API Key Set:  {'✅' if os.environ.get(env_var) else '❌'}")
    
    # Show model capabilities if available
    if provider and model and provider in PROVIDER_MODELS:
        model_info = get_model_info(provider, model)
        if model_info:
            print("\nCapabilities:")
            print(f"  • Max Tokens: {model_info['max_tokens']}")
            print(f"  • Streaming:  {'✅' if model_info['supports_streaming'] else '❌'}")
            print(f"  • Tools:      {'✅' if model_info['supports_tools'] else '❌'}")
            print(f"  • JSON Mode:  {'✅' if model_info['supports_json_mode'] else '❌'}")


def change_model(args):
    """Interactive model change wizard."""
    print("\n Change Model Wizard")
    print("=" * 40)
    
    # Show current config
    show_current_model(args)
    print("\n")
    
    # Select provider
    providers = list(PROVIDER_MODELS.keys())
    print("Select provider:")
    for i, prov in enumerate(providers, 1):
        print(f"  {i}. {prov.title()}")
    print(f"  {len(providers) + 1}. Cancel")
    
    try:
        choice = input(f"\nChoice (1-{len(providers) + 1}): ").strip()
        if not choice:
            return
        
        idx = int(choice) - 1
        if idx == len(providers):
            print(" Cancelled")
            return
        
        if 0 <= idx < len(providers):
            provider = providers[idx]
            
            # Show models for this provider
            print(format_model_menu(provider))
            
            models = get_provider_models(provider)
            model_choice = input(f"\nSelect model (1-{len(models)} or 0 for custom): ").strip()
            
            selected_model = None
            selected_display = None
            
            if model_choice == "0":
                model_name = input("Enter custom model name: ").strip()
                if not model_name:
                    print(" No model selected")
                    return
                selected_model = model_name
                selected_display = model_name
            else:
                try:
                    model_idx = int(model_choice) - 1
                    if 0 <= model_idx < len(models):
                        selected_model = models[model_idx]["api_name"]
                        selected_display = models[model_idx]["name"]
                    else:
                        print(" Invalid choice")
                        return
                except ValueError:
                    print(" Invalid input")
                    return
            
            # Get API key if needed
            env_var = f"{provider.upper()}_API_KEY"
            current_key = os.environ.get(env_var)
            
            if not current_key:
                print(f"\nEnter your {provider.title()} API key:")
                print(f"(will be saved as {env_var})")
                new_key = input("API key: ").strip()
                if new_key:
                    if save_api_key_to_shell(env_var, new_key):
                        os.environ[env_var] = new_key
                        print(f" API key saved to shell rc file")
                    else:
                        print(f"  Could not find shell rc file. Set {env_var} manually.")
                        print(f"Add this to your shell rc: export {env_var}=\"{new_key}\"")
            
            # Save configuration
            config = get_hive_config()
            if "llm" not in config:
                config["llm"] = {}
            
            config["llm"]["provider"] = provider
            config["llm"]["model"] = selected_model
            config["llm"]["model_display"] = selected_display
            config["llm"]["api_key_env_var"] = env_var
            config["llm"]["max_tokens"] = 8192  # Default
            
            # Save to file
            with open(HIVE_CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=2)
            
            print(f"\n Model changed to: {selected_display}")
            print("\nRestart Hive to apply changes:")
            print("  hive open")
    
    except KeyboardInterrupt:
        print("\n Cancelled")
    except Exception as e:
        print(f" Error: {e}")

def save_api_key_to_shell(env_var: str, api_key: str) -> bool:
    """Save API key to shell rc file."""
    shell_rc = None
    home = Path.home()
    
    # Detect shell rc file
    if (home / ".zshrc").exists():
        shell_rc = home / ".zshrc"
    elif (home / ".bashrc").exists():
        shell_rc = home / ".bashrc"
    elif (home / ".profile").exists():
        shell_rc = home / ".profile"
    else:
        return False
    
    # Append export line
    with open(shell_rc, "a") as f:
        f.write(f"\n# Hive - API key for {env_var}\n")
        f.write(f"export {env_var}=\"{api_key}\"\n")
    
    return True



def register_model_commands(subparsers):
    """Register model management commands with the CLI parser."""
    
    # Model command group
    model_parser = subparsers.add_parser(
        "model",
        help="Manage LLM models",
        description="View and change the LLM model used by Hive"
    )
    
    model_subparsers = model_parser.add_subparsers(
        dest="model_command",
        required=True,
        title="model commands"
    )
    
    # list command
    list_parser = model_subparsers.add_parser(
        "list",
        help="List available models",
        description="Show all available models for all providers or a specific provider"
    )
    list_parser.add_argument(
        "--provider",
        help="Provider name (anthropic, openai, gemini, groq, cerebras)"
    )
    list_parser.set_defaults(func=list_models)
    
    # show command
    show_parser = model_subparsers.add_parser(
        "show",
        help="Show current model",
        description="Display the currently configured model and its capabilities"
    )
    show_parser.set_defaults(func=show_current_model)
    
    # change command
    change_parser = model_subparsers.add_parser(
        "change",
        help="Change model interactively",
        description="Interactive wizard to change the LLM model"
    )
    change_parser.set_defaults(func=change_model)