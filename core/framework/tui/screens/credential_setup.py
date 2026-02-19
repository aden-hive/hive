"""Credential setup ModalScreen for configuring missing agent credentials."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from framework.credentials.setup import CredentialSetupSession, MissingCredential


class CredentialSetupScreen(ModalScreen[bool | None]):
    """Modal screen for configuring missing agent credentials.

    Shows a form with one password Input per missing credential.
    Returns True on successful save, or None on cancel/skip.
    """

    BINDINGS = [
        Binding("escape", "dismiss_setup", "Cancel"),
    ]

    DEFAULT_CSS = """
    CredentialSetupScreen {
        align: center middle;
    }
    #cred-container {
        width: 80%;
        max-width: 100;
        height: 80%;
        background: $surface;
        border: heavy $primary;
        padding: 1 2;
    }
    #cred-title {
        text-align: center;
        text-style: bold;
        width: 100%;
        color: $text;
    }
    #cred-subtitle {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }
    #cred-scroll {
        height: 1fr;
    }
    .cred-entry {
        margin-bottom: 1;
        padding: 1;
        background: $panel;
        height: auto;
    }
    .cred-entry Input {
        margin-top: 1;
    }
    .cred-buttons {
        height: auto;
        margin-top: 1;
        align: center middle;
    }
    .cred-buttons Button {
        margin: 0 1;
    }
    #cred-footer {
        text-align: center;
        width: 100%;
        margin-top: 1;
    }
    """

    def __init__(self, session: CredentialSetupSession) -> None:
        super().__init__()
        self._session = session
        self._missing: list[MissingCredential] = session.missing

    def compose(self) -> ComposeResult:
        n = len(self._missing)
        with Vertical(id="cred-container"):
            yield Label("Credential Setup", id="cred-title")
            yield Label(
                f"[dim]{n} credential{'s' if n != 1 else ''} needed to run this agent[/dim]",
                id="cred-subtitle",
            )
            with VerticalScroll(id="cred-scroll"):
                for i, cred in enumerate(self._missing):
                    with Vertical(classes="cred-entry"):
                        yield Label(f"[bold]{cred.env_var}[/bold]")
                        affected = cred.tools or cred.node_types
                        if affected:
                            yield Label(f"[dim]Required by: {', '.join(affected)}[/dim]")
                        if cred.description:
                            yield Label(f"[dim]{cred.description}[/dim]")
                        if cred.help_url:
                            yield Label(f"[cyan]Get key:[/cyan] {cred.help_url}")
                        yield Input(
                            placeholder="Paste API key...",
                            password=True,
                            id=f"key-{i}",
                        )
            with Vertical(classes="cred-buttons"):
                yield Button("Save & Continue", variant="primary", id="btn-save")
                yield Button("Skip", variant="default", id="btn-skip")
            yield Label(
                "[dim]Enter[/dim] Submit  [dim]Esc[/dim] Cancel",
                id="cred-footer",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self._save_credentials()
        elif event.button.id == "btn-skip":
            self.dismiss(None)

    def _save_credentials(self) -> None:
        """Collect inputs, store credentials, and dismiss."""
        # Init encryption key (generates one if missing)
        self._session._ensure_credential_key()

        configured = 0
        for i, cred in enumerate(self._missing):
            input_widget = self.query_one(f"#key-{i}", Input)
            value = input_widget.value.strip()
            if not value:
                continue
            try:
                self._session._store_credential(cred, value)
                configured += 1
            except Exception as e:
                self.notify(f"Error storing {cred.env_var}: {e}", severity="error")

        if configured > 0:
            self.dismiss(True)
        else:
            self.notify("No credentials entered", severity="warning", timeout=3)

    def action_dismiss_setup(self) -> None:
        self.dismiss(None)
