"""Account selection ModalScreen for picking a connected account before agent start."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets._option_list import Option


class AccountSelectionScreen(ModalScreen[dict | None]):
    """Modal screen showing connected accounts for pre-run selection.

    Returns the selected account dict, or None if dismissed.
    """

    SCOPED_CSS = False

    BINDINGS = [
        Binding("escape", "dismiss_picker", "Cancel"),
    ]

    DEFAULT_CSS = """
    AccountSelectionScreen {
        align: center middle;
    }
    #acct-container {
        width: 70%;
        max-width: 80;
        height: 60%;
        background: $surface;
        border: heavy $primary;
        padding: 1 2;
    }
    #acct-title {
        text-align: center;
        text-style: bold;
        width: 100%;
        color: $text;
    }
    #acct-subtitle {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }
    #acct-footer {
        text-align: center;
        width: 100%;
        margin-top: 1;
    }
    """

    def __init__(self, accounts: list[dict]) -> None:
        super().__init__()
        self._accounts = accounts

    def compose(self) -> ComposeResult:
        n = len(self._accounts)
        with Vertical(id="acct-container"):
            yield Label("Select Account to Test", id="acct-title")
            yield Label(
                f"[dim]{n} connected account{'s' if n != 1 else ''}[/dim]",
                id="acct-subtitle",
            )
            option_list = OptionList(id="acct-list")
            # Group: Aden accounts first, then local
            aden = [a for a in self._accounts if a.get("source") != "local"]
            local = [a for a in self._accounts if a.get("source") == "local"]
            ordered = aden + local
            for i, acct in enumerate(ordered):
                provider = acct.get("provider", "unknown")
                alias = acct.get("alias", "unknown")
                identity = acct.get("identity", {})
                source = acct.get("source", "aden")
                # Build identity label: prefer email, then username/workspace
                identity_label = (
                    identity.get("email")
                    or identity.get("username")
                    or identity.get("workspace")
                    or ""
                )
                label = Text()
                label.append(f"{provider}/", style="bold")
                label.append(alias, style="bold cyan")
                if source == "local":
                    label.append("  [local]", style="dim yellow")
                if identity_label:
                    label.append(f"  ({identity_label})", style="dim")
                option_list.add_option(Option(label, id=f"acct-{i}"))
            # Keep ordered list for index lookups
            self._accounts = ordered
            yield option_list
            yield Label(
                "[dim]Enter[/dim] Select  [dim]Esc[/dim] Cancel",
                id="acct-footer",
            )

    def on_mount(self) -> None:
        ol = self.query_one("#acct-list", OptionList)
        ol.styles.height = "1fr"

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        if 0 <= idx < len(self._accounts):
            self.dismiss(self._accounts[idx])

    def action_dismiss_picker(self) -> None:
        self.dismiss(None)
