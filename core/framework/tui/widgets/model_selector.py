"""Model selector TUI widget.

Interactive widget for selecting LLM provider and model configuration.
"""

from __future__ import annotations

import json
import os
from datetime import UTC
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, OptionList, Static
from textual.widgets.option_list import Option

from framework.config.model_providers import PROVIDERS, get_provider_by_id


class ModelSelectorScreen(ModalScreen):
    """Modal screen for selecting LLM model configuration."""

    CSS = """
    ModelSelectorScreen {
        align: center middle;
    }

    #modal-dialog {
        width: 90;
        height: auto;
        max-height: 40;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #title {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #provider-container {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    #provider-label {
        width: 100%;
        text-style: bold;
        margin-bottom: 1;
    }

    #provider-list {
        width: 100%;
        height: 10;
        border: solid $primary;
        background: $panel;
    }

    #model-container {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    #model-label {
        width: 100%;
        text-style: bold;
        margin-bottom: 1;
    }

    #model-list {
        width: 100%;
        height: 10;
        border: solid $primary;
        background: $panel;
    }

    #config-panel {
        width: 100%;
        height: auto;
        background: $panel;
        border: solid $primary;
        padding: 1;
        margin-bottom: 1;
    }

    #button-bar {
        width: 100%;
        height: auto;
        align: center middle;
    }

    Button {
        margin: 0 1;
    }

    .option-disabled {
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "cancel", "Cancel"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.selected_provider: str | None = None
        self.selected_model: str | None = None
        self._config_path = Path.home() / ".hive" / "configuration.json"

    def compose(self) -> ComposeResult:
        """Compose the modal dialog."""
        with Container(id="modal-dialog"):
            yield Label("🔧 LLM Model Configuration", id="title")

            # Provider selection
            with Vertical(id="provider-container"):
                yield Label("Select Provider:", id="provider-label")
                yield OptionList(id="provider-list")

            # Model selection
            with Vertical(id="model-container"):
                yield Label("Select Model:", id="model-label")
                yield OptionList(id="model-list")

            # Configuration panel
            yield Static("", id="config-panel")

            # Buttons
            with Horizontal(id="button-bar"):
                yield Button("Save & Test", variant="primary", id="save-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize provider list on mount."""
        self._load_current_config()
        self._populate_providers()

    def _load_current_config(self) -> None:
        """Load current configuration from file."""
        if not self._config_path.exists():
            return

        try:
            with open(self._config_path) as f:
                config = json.load(f)
                llm_config = config.get("llm", {})
                provider = llm_config.get("provider")
                model = llm_config.get("model")

                # Set current selections
                if provider:
                    self.selected_provider = provider
                if model:
                    self.selected_model = model
        except (json.JSONDecodeError, OSError):
            pass

    def _populate_providers(self) -> None:
        """Populate provider list with available providers."""
        provider_list = self.query_one("#provider-list", OptionList)
        provider_list.clear_options()

        for provider_id, provider in PROVIDERS.items():
            # Check if API key is configured
            api_key_configured = bool(os.environ.get(provider.env_var))
            status = "✓" if api_key_configured else "○"

            # Mark current provider
            current_marker = ""
            if provider_id == self.selected_provider:
                current_marker = " [current]"

            option_text = f"{status} {provider.name}{current_marker}"

            # Add option without prompt parameter (not supported in this Textual version)
            provider_list.add_option(Option(option_text, id=provider_id))

        # Select current provider if available
        if self.selected_provider:
            try:
                provider_list.highlighted = self._get_provider_index(self.selected_provider)
            except Exception:
                pass

    def _get_provider_index(self, provider_id: str) -> int:
        """Get index of provider in list."""
        for i, (pid, _) in enumerate(PROVIDERS.items()):
            if pid == provider_id:
                return i
        return 0

    def _populate_models(self, provider_id: str) -> None:
        """Populate model list for selected provider."""
        model_list = self.query_one("#model-list", OptionList)
        model_list.clear_options()

        provider = get_provider_by_id(provider_id)
        if not provider:
            return

        for model in provider.models:
            # Format context window
            ctx_str = f"{model.context_window // 1000}K"
            if model.context_window >= 1000000:
                ctx_str = f"{model.context_window // 1000000}M"

            # Build option text
            option_text = model.name
            if model.recommended:
                option_text = f"⭐ {option_text}"

            # Add details
            option_text += f" [{ctx_str} context]"

            # Mark current model
            if model.id == self.selected_model:
                option_text += " [current]"

            # Add option without prompt parameter (not supported in this Textual version)
            model_list.add_option(Option(option_text, id=model.id))

        # Select current model if available
        if self.selected_model:
            try:
                model_idx = self._get_model_index(provider.models, self.selected_model)
                model_list.highlighted = model_idx
            except Exception:
                pass

    def _get_model_index(self, models: list, model_id: str) -> int:
        """Get index of model in list."""
        for i, model in enumerate(models):
            if model.id == model_id:
                return i
        return 0

    def _update_config_panel(self) -> None:
        """Update configuration panel with current selections."""
        panel = self.query_one("#config-panel", Static)

        if not self.selected_provider:
            panel.update("[dim]Select a provider to continue[/dim]")
            return

        provider = get_provider_by_id(self.selected_provider)
        if not provider:
            panel.update("[red]Error: Invalid provider[/red]")
            return

        # Check API key status
        api_key_configured = bool(os.environ.get(provider.env_var))
        api_key_status = (
            "[green]✓ Configured[/green]"
            if api_key_configured
            else f"[yellow]⚠ Not configured ({provider.env_var})[/yellow]"
        )

        # Build config text
        lines = [
            f"[bold]Provider:[/bold] {provider.name}",
            f"[bold]API Key:[/bold] {api_key_status}",
        ]

        if self.selected_model:
            # Get model info
            model_info = None
            for model in provider.models:
                if model.id == self.selected_model:
                    model_info = model
                    break

            if model_info:
                lines.append(f"[bold]Model:[/bold] {model_info.name}")
                lines.append(f"[bold]Context:[/bold] {model_info.context_window:,} tokens")
                lines.append(f"[dim]{model_info.description}[/dim]")
        else:
            lines.append("[dim]Select a model to continue[/dim]")

        if not api_key_configured:
            lines.append("")
            lines.append(f"[yellow]Get API key:[/yellow] {provider.api_key_url}")

        panel.update("\n".join(lines))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection."""
        if event.option_list.id == "provider-list":
            # Provider selected
            self.selected_provider = event.option.id
            self._populate_models(self.selected_provider)
            self._update_config_panel()
        elif event.option_list.id == "model-list":
            # Model selected
            self.selected_model = event.option.id
            self._update_config_panel()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "save-btn":
            self._save_and_test()
        elif event.button.id == "cancel-btn":
            self.action_cancel()

    def _save_and_test(self) -> None:
        """Save configuration and test connection."""
        if not self.selected_provider or not self.selected_model:
            self.app.notify(
                "Please select both a provider and model",
                severity="warning",
                timeout=3,
            )
            return

        provider = get_provider_by_id(self.selected_provider)
        if not provider:
            self.app.notify("Invalid provider selected", severity="error", timeout=3)
            return

        # Check if API key is configured
        if not os.environ.get(provider.env_var):
            self.app.notify(
                f"API key not configured: {provider.env_var}",
                severity="warning",
                timeout=5,
            )
            # Still save, but warn user
            # return

        # Save configuration
        try:
            self._save_config()
            self.app.notify(
                f"✓ Configuration saved: {provider.name} / {self.selected_model}",
                severity="information",
                timeout=5,
            )
            self.dismiss(True)
        except Exception as e:
            self.app.notify(f"Error saving configuration: {e}", severity="error", timeout=5)

    def _save_config(self) -> None:
        """Save configuration to file atomically."""
        # Ensure directory exists
        self._config_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing config or create new
        config: dict[str, Any] = {}
        if self._config_path.exists():
            try:
                with open(self._config_path) as f:
                    config = json.load(f)
            except (json.JSONDecodeError, OSError):
                # If config is corrupted, back it up
                backup_path = self._config_path.with_suffix(".json.backup")
                if self._config_path.exists():
                    import shutil

                    shutil.copy(self._config_path, backup_path)

        # Get provider info
        provider = get_provider_by_id(self.selected_provider)
        if not provider:
            raise ValueError(f"Invalid provider: {self.selected_provider}")

        # Update LLM configuration
        config["llm"] = {
            "provider": self.selected_provider,
            "model": self.selected_model,
            "api_key_env_var": provider.env_var,
        }

        # Add timestamp
        from datetime import datetime

        config["updated_at"] = datetime.now(UTC).isoformat()

        # Write atomically (write to temp file, then rename)
        temp_path = self._config_path.with_suffix(".json.tmp")
        try:
            with open(temp_path, "w") as f:
                json.dump(config, f, indent=2)
            temp_path.replace(self._config_path)
        except Exception:
            # Clean up temp file on error
            if temp_path.exists():
                temp_path.unlink()
            raise

    def action_cancel(self) -> None:
        """Cancel and close modal."""
        self.dismiss(False)
