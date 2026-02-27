"""Credential setup ModalScreen for configuring missing agent credentials."""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from framework.credentials.setup import CredentialSetupSession, MissingCredential


class CredentialSetupScreen(ModalScreen[bool | None]):
    """Modal screen for configuring missing agent credentials.

    Shows a form with one password Input per missing credential.
    For Aden-backed credentials (``aden_supported=True``), prompts for
    ``ADEN_API_KEY`` and runs the Aden sync flow instead of storing a
    raw value.

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
        # Track which credentials need Aden sync vs direct API key
        self._aden_creds: set[int] = set()
        self._needs_aden_key = False
        for i, cred in enumerate(self._missing):
            if cred.aden_supported and not cred.direct_api_key_supported:
                self._aden_creds.add(i)
                self._needs_aden_key = True

    def compose(self) -> ComposeResult:
        n = len(self._missing)
        with Vertical(id="cred-container"):
            yield Label("Credential Setup", id="cred-title")
            yield Label(
                f"[dim]{n} credential{'s' if n != 1 else ''} needed to run this agent[/dim]",
                id="cred-subtitle",
            )
            with VerticalScroll(id="cred-scroll"):
                # If any credential needs Aden, show ADEN_API_KEY input first
                if self._needs_aden_key:
                    aden_key = os.environ.get("ADEN_API_KEY", "")
                    with Vertical(classes="cred-entry"):
                        yield Label("[bold]ADEN_API_KEY[/bold]")
                        aden_names = [
                            self._missing[i].credential_name for i in sorted(self._aden_creds)
                        ]
                        yield Label(f"[dim]Required for OAuth sync: {', '.join(aden_names)}[/dim]")
                        yield Label("[cyan]Get key:[/cyan] https://hive.adenhq.com")
                        yield Input(
                            placeholder="Paste ADEN_API_KEY..."
                            if not aden_key
                            else "Already set (leave blank to keep)",
                            password=True,
                            id="key-aden",
                        )

                # Show direct API key inputs for non-Aden credentials
                for i, cred in enumerate(self._missing):
                    if i in self._aden_creds:
                        continue  # Handled via Aden sync above
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
        self._session._ensure_credential_key()

        configured = 0

        # Handle Aden-backed credentials
        if self._needs_aden_key:
            aden_input = self.query_one("#key-aden", Input)
            aden_key = aden_input.value.strip()
            if aden_key:
                from framework.credentials.key_storage import save_aden_api_key

                save_aden_api_key(aden_key)
                configured += 1  # ADEN_API_KEY itself counts as configured

            # Run Aden sync for all Aden-backed creds (best-effort)
            if aden_key or os.environ.get("ADEN_API_KEY"):
                self._sync_aden_credentials()

        # Handle direct API key credentials
        for i, cred in enumerate(self._missing):
            if i in self._aden_creds:
                continue
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
            self.notify("No credentials configured", severity="warning", timeout=3)

    def _sync_aden_credentials(self) -> int:
        """Sync Aden-backed credentials and return count of successfully synced."""
        # Build the Aden sync components directly so we get real errors
        # instead of CredentialStore.with_aden_sync() silently falling back.
        try:
            from framework.credentials.aden import (
                AdenCachedStorage,
                AdenClientConfig,
                AdenCredentialClient,
                AdenSyncProvider,
            )
            from framework.credentials.storage import EncryptedFileStorage

            client = AdenCredentialClient(AdenClientConfig(base_url="https://api.adenhq.com"))
            provider = AdenSyncProvider(client=client)
            local_storage = EncryptedFileStorage()
            cached_storage = AdenCachedStorage(
                local_storage=local_storage,
                aden_provider=provider,
            )
        except Exception as e:
            self.notify(
                f"Aden setup error: {e}",
                severity="error",
                timeout=8,
            )
            return 0

        # Sync all integrations from Aden to get the provider index populated
        try:
            from framework.credentials import CredentialStore

            store = CredentialStore(
                storage=cached_storage,
                providers=[provider],
                auto_refresh=True,
            )
            num_synced = provider.sync_all(store)
            if num_synced == 0:
                self.notify(
                    "No active integrations found in Aden. "
                    "Connect integrations at hive.adenhq.com.",
                    severity="warning",
                    timeout=8,
                )
        except Exception as e:
            self.notify(
                f"Aden sync error: {e}",
                severity="error",
                timeout=8,
            )
            return 0

        synced = 0
        for i in sorted(self._aden_creds):
            cred = self._missing[i]
            cred_id = cred.credential_id or cred.credential_name
            if store.is_available(cred_id):
                try:
                    value = store.get_key(cred_id, cred.credential_key)
                    if value:
                        os.environ[cred.env_var] = value
                        self._persist_to_local_store(cred_id, cred.credential_key, value)
                        synced += 1
                    else:
                        self.notify(
                            f"{cred.credential_name}: key "
                            f"'{cred.credential_key}' not found "
                            f"in credential '{cred_id}'",
                            severity="warning",
                            timeout=8,
                        )
                except Exception as e:
                    self.notify(
                        f"{cred.credential_name} extraction failed: {e}",
                        severity="error",
                        timeout=8,
                    )
            else:
                self.notify(
                    f"{cred.credential_name} (id='{cred_id}') "
                    f"not found in Aden. Connect this "
                    f"integration at hive.adenhq.com first.",
                    severity="warning",
                    timeout=8,
                )
        return synced

    @staticmethod
    def _persist_to_local_store(cred_id: str, key_name: str, value: str) -> None:
        """Save a synced token to the local encrypted store under the canonical ID."""
        try:
            from pydantic import SecretStr

            from framework.credentials.models import CredentialKey, CredentialObject, CredentialType
            from framework.credentials.storage import EncryptedFileStorage

            cred_obj = CredentialObject(
                id=cred_id,
                credential_type=CredentialType.OAUTH2,
                keys={
                    key_name: CredentialKey(
                        name=key_name,
                        value=SecretStr(value),
                    ),
                },
                auto_refresh=True,
            )
            EncryptedFileStorage().save(cred_obj)
        except Exception:
            pass  # Best-effort; env var is the primary delivery mechanism

    def action_dismiss_setup(self) -> None:
        self.dismiss(None)
