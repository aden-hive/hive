"""Add Local Credential ModalScreen for storing named local API key accounts."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList
from textual.widgets._option_list import Option


class AddLocalCredentialScreen(ModalScreen[dict | None]):
    """Modal screen for adding a named local API key credential.

    Phase 1: Pick credential type from list.
    Phase 2: Enter alias + API key, run health check, save.

    Returns a dict with credential_id, alias, and identity on success, or None on cancel.
    """

    BINDINGS = [
        Binding("escape", "dismiss_screen", "Cancel"),
    ]

    DEFAULT_CSS = """
    AddLocalCredentialScreen {
        align: center middle;
    }
    #alc-container {
        width: 80%;
        max-width: 90;
        height: 80%;
        background: $surface;
        border: heavy $primary;
        padding: 1 2;
    }
    #alc-title {
        text-align: center;
        text-style: bold;
        width: 100%;
        color: $text;
    }
    #alc-subtitle {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }
    #alc-type-list {
        height: 1fr;
    }
    #alc-form {
        height: 1fr;
    }
    .alc-field {
        margin-bottom: 1;
        height: auto;
    }
    .alc-field Label {
        margin-bottom: 0;
    }
    #alc-status {
        width: 100%;
        height: auto;
        margin-top: 1;
        padding: 1;
        background: $panel;
    }
    .alc-buttons {
        height: auto;
        margin-top: 1;
        align: center middle;
    }
    .alc-buttons Button {
        margin: 0 1;
    }
    #alc-footer {
        text-align: center;
        width: 100%;
        margin-top: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        # Load credential specs that support direct API keys
        self._specs: list[tuple[str, object]] = self._load_specs()
        # Selected credential spec (set in phase 2)
        self._selected_id: str = ""
        self._selected_spec: object = None
        self._phase: int = 1  # 1 = type selection, 2 = form

    @staticmethod
    def _load_specs() -> list[tuple[str, object]]:
        """Return (credential_id, spec) pairs for direct-API-key credentials."""
        try:
            from aden_tools.credentials import CREDENTIAL_SPECS

            return [
                (cid, spec)
                for cid, spec in CREDENTIAL_SPECS.items()
                if getattr(spec, "direct_api_key_supported", False)
            ]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="alc-container"):
            yield Label("Add Local Credential", id="alc-title")
            yield Label("[dim]Store a named API key account[/dim]", id="alc-subtitle")
            # Phase 1: type selection
            option_list = OptionList(id="alc-type-list")
            for cid, spec in self._specs:
                description = getattr(spec, "description", cid)
                option_list.add_option(Option(f"{cid}  [dim]{description}[/dim]", id=f"type-{cid}"))
            yield option_list
            # Phase 2: form (hidden initially)
            with VerticalScroll(id="alc-form"):
                with Vertical(classes="alc-field"):
                    yield Label("[bold]Alias[/bold]  [dim](e.g. work, personal)[/dim]")
                    yield Input(value="default", id="alc-alias")
                with Vertical(classes="alc-field"):
                    yield Label("[bold]API Key[/bold]")
                    yield Input(placeholder="Paste API key...", password=True, id="alc-key")
                yield Label("", id="alc-status")
                with Vertical(classes="alc-buttons"):
                    yield Button("Test & Save", variant="primary", id="btn-save")
                    yield Button("Back", variant="default", id="btn-back")
            yield Label(
                "[dim]Enter[/dim] Select  [dim]Esc[/dim] Cancel",
                id="alc-footer",
            )

    def on_mount(self) -> None:
        self._show_phase(1)

    # ------------------------------------------------------------------
    # Phase switching
    # ------------------------------------------------------------------

    def _show_phase(self, phase: int) -> None:
        self._phase = phase
        type_list = self.query_one("#alc-type-list", OptionList)
        form = self.query_one("#alc-form", VerticalScroll)
        if phase == 1:
            type_list.display = True
            form.display = False
            subtitle = self.query_one("#alc-subtitle", Label)
            subtitle.update("[dim]Select the credential type to add[/dim]")
        else:
            type_list.display = False
            form.display = True
            spec = self._selected_spec
            description = getattr(spec, "description", self._selected_id) if spec else self._selected_id
            subtitle = self.query_one("#alc-subtitle", Label)
            subtitle.update(f"[dim]{self._selected_id}[/dim]  {description}")
            self._clear_status()
            # Focus the alias input
            self.query_one("#alc-alias", Input).focus()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self._phase != 1:
            return
        option_id = event.option.id or ""
        if option_id.startswith("type-"):
            cid = option_id[5:]  # strip "type-" prefix
            self._selected_id = cid
            self._selected_spec = next(
                (spec for spec_id, spec in self._specs if spec_id == cid), None
            )
            self._show_phase(2)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self._do_save()
        elif event.button.id == "btn-back":
            self._show_phase(1)

    # ------------------------------------------------------------------
    # Save logic
    # ------------------------------------------------------------------

    def _do_save(self) -> None:
        alias = self.query_one("#alc-alias", Input).value.strip() or "default"
        api_key = self.query_one("#alc-key", Input).value.strip()

        if not api_key:
            self._set_status("[red]API key cannot be empty.[/red]")
            return

        self._set_status("[dim]Running health check...[/dim]")
        # Disable save button while running
        btn = self.query_one("#btn-save", Button)
        btn.disabled = True

        try:
            from framework.credentials.local.registry import LocalCredentialRegistry

            registry = LocalCredentialRegistry.default()
            info, health_result = registry.save_account(
                credential_id=self._selected_id,
                alias=alias,
                api_key=api_key,
                run_health_check=True,
            )

            if health_result is not None and not health_result.valid:
                self._set_status(
                    f"[yellow]Saved with failed health check:[/yellow] {health_result.message}\n"
                    "[dim]You can re-validate later via validate_credential().[/dim]"
                )
            else:
                identity = info.identity.to_dict()
                identity_str = ""
                if identity:
                    parts = [f"{k}: {v}" for k, v in identity.items() if v]
                    identity_str = "  " + ", ".join(parts) if parts else ""
                self._set_status(
                    f"[green]Saved:[/green] {info.storage_id}{identity_str}"
                )
                # Dismiss with result so callers can react
                self.set_timer(1.0, lambda: self.dismiss(info.to_account_dict()))
                return
        except Exception as e:
            self._set_status(f"[red]Error:[/red] {e}")
        finally:
            btn.disabled = False

    def _set_status(self, markup: str) -> None:
        self.query_one("#alc-status", Label).update(markup)

    def _clear_status(self) -> None:
        self.query_one("#alc-status", Label).update("")

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)
