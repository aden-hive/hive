"""CLI commands for configuration management."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC


def register_config_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register configuration commands with the main CLI."""

    # config command group
    config_parser = subparsers.add_parser(
        "config",
        help="Manage Hive configuration",
        description="Interactive configuration management for Hive.",
    )
    config_subparsers = config_parser.add_subparsers(
        dest="config_cmd",
        help="Configuration commands",
    )

    # config models command
    models_parser = config_subparsers.add_parser(
        "models",
        help="Configure LLM models",
        description="Interactive TUI for selecting LLM provider and model.",
    )
    models_parser.add_argument(
        "--list",
        action="store_true",
        help="List available providers and models (no TUI)",
    )
    models_parser.add_argument(
        "--provider",
        type=str,
        help="Set provider (for scripting, skips TUI)",
    )
    models_parser.add_argument(
        "--model",
        type=str,
        help="Set model (requires --provider, skips TUI)",
    )
    models_parser.set_defaults(func=cmd_config_models)

    # config show command
    show_parser = config_subparsers.add_parser(
        "show",
        help="Show current configuration",
        description="Display the current Hive configuration.",
    )
    show_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    show_parser.set_defaults(func=cmd_config_show)

    # config set command (for scripting)
    set_parser = config_subparsers.add_parser(
        "set",
        help="Set configuration value",
        description="Set a configuration value (for scripting).",
    )
    set_parser.add_argument(
        "key",
        type=str,
        help="Configuration key (e.g., 'llm.provider', 'llm.model')",
    )
    set_parser.add_argument(
        "value",
        type=str,
        help="Configuration value",
    )
    set_parser.set_defaults(func=cmd_config_set)


def cmd_config_models(args: argparse.Namespace) -> int:
    """Launch model configuration TUI or set models via CLI."""
    # List mode - show available providers and models
    if getattr(args, "list", False):
        from framework.config.model_providers import PROVIDERS

        print("\nAvailable LLM Providers and Models:\n")
        print("=" * 80)

        for provider_id, provider in PROVIDERS.items():
            # Check API key status
            api_key_configured = bool(os.environ.get(provider.env_var))
            status = "✓" if api_key_configured else "○"

            print(f"\n{status} {provider.name} ({provider_id})")
            print(f"  {provider.description}")
            print(f"  API Key: {provider.env_var}")
            print(f"  Get Key: {provider.api_key_url}")
            print("\n  Models:")

            for model in provider.models:
                ctx_str = f"{model.context_window // 1000}K"
                if model.context_window >= 1000000:
                    ctx_str = f"{model.context_window // 1000000}M"

                rec_marker = "⭐ " if model.recommended else "   "
                print(f"    {rec_marker}{model.name} [{ctx_str}]")
                print(f"       {model.description}")
                print(f"       ID: {model.id}")

        print("\n" + "=" * 80)
        print("\nUsage:")
        print("  hive config models  # Launch interactive TUI")
        print("  hive config set llm.provider <provider_id>")
        print("  hive config set llm.model <model_id>")
        print()
        return 0

    # CLI mode - set provider and model directly
    if hasattr(args, "provider") and args.provider:
        from framework.config.model_providers import PROVIDERS, validate_model_provider_match

        provider_id = args.provider
        model_id = getattr(args, "model", None)

        # Validate provider
        if provider_id not in PROVIDERS:
            print(
                f"Error: Unknown provider '{provider_id}'",
                file=sys.stderr,
            )
            print("\nAvailable providers:", ", ".join(PROVIDERS.keys()))
            return 1

        # Validate model if provided
        if model_id and not validate_model_provider_match(model_id, provider_id):
            print(
                f"Error: Model '{model_id}' is not compatible with provider '{provider_id}'",
                file=sys.stderr,
            )
            print(f"\nUse 'hive config models --list' to see available models for {provider_id}")
            return 1

        # Set the configuration
        if (
            cmd_config_set(
                type(
                    "Args",
                    (),
                    {"key": "llm.provider", "value": provider_id},
                )()
            )
            != 0
        ):
            return 1

        if model_id:
            provider = PROVIDERS[provider_id]
            if (
                cmd_config_set(
                    type(
                        "Args",
                        (),
                        {
                            "key": "llm.model",
                            "value": model_id,
                        },
                    )()
                )
                != 0
            ):
                return 1
            if (
                cmd_config_set(
                    type(
                        "Args",
                        (),
                        {
                            "key": "llm.api_key_env_var",
                            "value": provider.env_var,
                        },
                    )()
                )
                != 0
            ):
                return 1

        print("\n✓ Configuration updated successfully")
        print("\nCurrent configuration:")
        return cmd_config_show(type("Args", (), {"json": False})())

    # TUI mode - interactive configuration
    try:
        from textual.app import App

        from framework.tui.widgets.model_selector import ModelSelectorScreen

        class ModelConfigApp(App):
            """Standalone app for model configuration."""

            def on_mount(self) -> None:
                """Push model selector screen on mount."""

                def handle_result(result: bool) -> None:
                    """Handle modal result and exit."""
                    if result:
                        # User saved configuration
                        self.exit(0)
                    else:
                        # User cancelled
                        self.exit(1)

                self.push_screen(ModelSelectorScreen(), handle_result)

        app = ModelConfigApp()
        return app.run()
    except ImportError:
        print(
            "Error: Textual is not installed. Install with: uv pip install textual",
            file=sys.stderr,
        )
        return 1
    except Exception as e:
        print(f"Error launching model configuration: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


def cmd_config_show(args: argparse.Namespace) -> int:
    """Show current configuration."""
    import json
    from pathlib import Path

    config_path = Path.home() / ".hive" / "configuration.json"

    if not config_path.exists():
        print("No configuration file found at ~/.hive/configuration.json")
        print("Run 'hive config models' to configure your LLM settings.")
        return 1

    try:
        with open(config_path) as f:
            config = json.load(f)

        if args.json:
            print(json.dumps(config, indent=2))
        else:
            print("Current Hive Configuration:")
            print("=" * 60)

            # LLM configuration
            llm_config = config.get("llm", {})
            if llm_config:
                print("\n[LLM Configuration]")
                print(f"  Provider: {llm_config.get('provider', 'not set')}")
                print(f"  Model: {llm_config.get('model', 'not set')}")
                print(f"  API Key Env Var: {llm_config.get('api_key_env_var', 'not set')}")

            # Timestamps
            created_at = config.get("created_at")
            updated_at = config.get("updated_at")
            if created_at:
                print(f"\n  Created: {created_at}")
            if updated_at:
                print(f"  Updated: {updated_at}")

            print()

        return 0
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading configuration: {e}", file=sys.stderr)
        return 1


def cmd_config_set(args: argparse.Namespace) -> int:
    """Set configuration value (for scripting)."""
    import json
    from datetime import datetime
    from pathlib import Path

    config_path = Path.home() / ".hive" / "configuration.json"

    # Load existing config
    config = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            # If corrupted, back it up
            backup_path = config_path.with_suffix(".json.backup")
            if config_path.exists():
                import shutil

                shutil.copy(config_path, backup_path)
                print(f"Backed up corrupted config to {backup_path}")

    # Parse key path (e.g., "llm.provider" -> ["llm", "provider"])
    key_parts = args.key.split(".")

    # Navigate to the right place in the config dict
    current = config
    for part in key_parts[:-1]:
        if part not in current:
            current[part] = {}
        current = current[part]

    # Set the value
    final_key = key_parts[-1]
    current[final_key] = args.value

    # Update timestamp
    config["updated_at"] = datetime.now(UTC).isoformat()

    # Ensure directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Write atomically
    temp_path = config_path.with_suffix(".json.tmp")
    try:
        with open(temp_path, "w") as f:
            json.dump(config, f, indent=2)
        temp_path.replace(config_path)
        print(f"✓ Set {args.key} = {args.value}")
        return 0
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        print(f"Error saving configuration: {e}", file=sys.stderr)
        return 1
