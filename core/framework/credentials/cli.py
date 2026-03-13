"""CLI commands for credential management."""

import argparse
import getpass
import json
import sys
from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr

from framework.credentials import (
    CredentialKey,
    CredentialObject,
    CredentialStore,
    CredentialType,
)


def _get_store() -> CredentialStore:
    """
    Get a credential store instance using the default encrypted storage.

    This uses EncryptedFileStorage which stores credentials in ~/.hive/credentials
    with Fernet encryption. The encryption key is read from HIVE_CREDENTIAL_KEY
    environment variable, or generated if not set.

    Returns:
        CredentialStore instance with encrypted file storage
    """
    return CredentialStore.with_encrypted_storage()


def _mask_value(value: str, show_chars: int = 4) -> str:
    """
    Mask a secret value, showing only the last few characters for verification.

    This ensures sensitive credential values are never fully displayed in output,
    reducing the risk of accidental exposure in logs or terminal history.

    Args:
        value: The secret value to mask
        show_chars: Number of characters to show at the end (default: 4)

    Returns:
        Masked string with asterisks and last N characters visible
    """
    if not value:
        return ""
    if len(value) <= show_chars:
        return "*" * len(value)
    return "*" * (len(value) - show_chars) + value[-show_chars:]


def _format_storage_type(store: CredentialStore) -> str:
    """
    Get a human-readable description of the storage backend being used.

    Args:
        store: The credential store instance

    Returns:
        String describing the storage type
    """
    storage_type = type(store._storage).__name__
    if "EncryptedFileStorage" in storage_type:
        return "encrypted file"
    elif "EnvVarStorage" in storage_type:
        return "environment variables"
    elif "VaultStorage" in storage_type:
        return "HashiCorp Vault"
    else:
        return storage_type.lower().replace("storage", "")


def register_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register credential management commands with the main CLI."""

    # Create the main 'creds' subcommand parser
    creds_parser = subparsers.add_parser(
        "creds",
        help="Manage credentials",
        description="Manage stored credentials for agents and tools.",
    )

    # Create subparsers for individual credential commands
    creds_subparsers = creds_parser.add_subparsers(dest="creds_command", required=True)

    # list command - show all stored credentials
    list_parser = creds_subparsers.add_parser(
        "list",
        help="List all stored credentials",
        description="Display all credentials with their metadata.",
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON format",
    )
    list_parser.set_defaults(func=cmd_list)

    # show command - display details of a specific credential
    show_parser = creds_subparsers.add_parser(
        "show",
        help="Show credential details",
        description="Display detailed information about a specific credential.",
    )
    show_parser.add_argument(
        "credential_id",
        type=str,
        help="ID of the credential to show",
    )
    show_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON format",
    )
    show_parser.set_defaults(func=cmd_show)

    # add command - interactively add a new credential
    add_parser = creds_subparsers.add_parser(
        "add",
        help="Add a new credential",
        description="Interactively create and save a new credential.",
    )
    add_parser.add_argument(
        "credential_id",
        type=str,
        help="Unique identifier for the credential (e.g., 'my_api', 'github_oauth')",
    )
    add_parser.add_argument(
        "--type",
        type=str,
        choices=["static", "oauth2", "api_key", "bearer_token", "custom"],
        default="static",
        help="Type of credential (default: static)",
    )
    add_parser.add_argument(
        "--storage",
        type=str,
        choices=["file", "env"],
        default="file",
        help="Storage backend to use (default: file)",
    )
    add_parser.set_defaults(func=cmd_add)

    # delete command - remove a credential
    delete_parser = creds_subparsers.add_parser(
        "delete",
        help="Delete a credential",
        description="Remove a credential from storage.",
    )
    delete_parser.add_argument(
        "credential_id",
        type=str,
        help="ID of the credential to delete",
    )
    delete_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt",
    )
    delete_parser.set_defaults(func=cmd_delete)

    # test command - validate a credential
    test_parser = creds_subparsers.add_parser(
        "test",
        help="Test a credential",
        description="Validate that a credential exists and is properly configured.",
    )
    test_parser.add_argument(
        "credential_id",
        type=str,
        help="ID of the credential to test",
    )
    test_parser.set_defaults(func=cmd_test)

    # refresh command - manually refresh an OAuth2 credential
    refresh_parser = creds_subparsers.add_parser(
        "refresh",
        help="Refresh an OAuth2 credential",
        description="Manually trigger refresh of an OAuth2 credential token.",
    )
    refresh_parser.add_argument(
        "credential_id",
        type=str,
        help="ID of the OAuth2 credential to refresh",
    )
    refresh_parser.set_defaults(func=cmd_refresh)


def cmd_list(args: argparse.Namespace) -> int:
    """
    List all stored credentials with their metadata.

    Shows credential ID, type, number of keys, storage location, and status.
    """
    try:
        store = _get_store()
        credential_ids = store.list_credentials()

        if not credential_ids:
            if args.json:
                print(json.dumps({"credentials": []}))
            else:
                print("No credentials found.")
            return 0

        # Collect credential information
        credentials_data = []
        for cred_id in credential_ids:
            cred = store.get_credential(cred_id, refresh_if_needed=False)
            if cred is None:
                continue

            # Determine expiration status
            status = "valid"
            expires_info = None
            for key in cred.keys.values():
                if key.expires_at:
                    if key.is_expired:
                        status = "expired"
                    else:
                        status = "expires soon"
                        expires_info = key.expires_at.strftime("%Y-%m-%d %H:%M:%S")
                    break

            cred_info = {
                "id": cred_id,
                "type": cred.credential_type.value,
                "keys": len(cred.keys),
                "storage": _format_storage_type(store),
                "status": status,
            }
            if expires_info:
                cred_info["expires_at"] = expires_info
            credentials_data.append(cred_info)

        if args.json:
            print(json.dumps({"credentials": credentials_data}, indent=2, default=str))
        else:
            # Format as table
            print(f"Found {len(credentials_data)} credential(s):\n")
            print(f"{'ID':<20} {'Type':<15} {'Keys':<6} {'Storage':<20} {'Status'}")
            print("-" * 80)
            for cred in credentials_data:
                expires_str = f" ({cred.get('expires_at', '')})" if "expires_at" in cred else ""
                print(
                    f"{cred['id']:<20} {cred['type']:<15} {cred['keys']:<6} "
                    f"{cred['storage']:<20} {cred['status']}{expires_str}"
                )

        return 0
    except Exception as e:
        print(f"Error listing credentials: {e}", file=sys.stderr)
        return 1


def cmd_show(args: argparse.Namespace) -> int:
    """
    Show detailed information about a specific credential.

    Displays all keys (masked), metadata, expiration, and validation status.
    """
    try:
        store = _get_store()
        cred = store.get_credential(args.credential_id, refresh_if_needed=False)

        if cred is None:
            print(f"Error: Credential '{args.credential_id}' not found.", file=sys.stderr)
            return 1

        # Build output data
        keys_data = {}
        for key_name, key_obj in cred.keys.items():
            masked_value = _mask_value(key_obj.get_secret_value())
            key_info: dict[str, Any] = {"value": masked_value}
            if key_obj.expires_at:
                key_info["expires_at"] = key_obj.expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                key_info["is_expired"] = key_obj.is_expired
            if key_obj.metadata:
                key_info["metadata"] = key_obj.metadata
            keys_data[key_name] = key_info

        output_data = {
            "id": cred.id,
            "type": cred.credential_type.value,
            "storage": _format_storage_type(store),
            "keys": keys_data,
            "provider_id": cred.provider_id,
            "auto_refresh": cred.auto_refresh,
        }

        # Add validation status
        is_valid = store.validate_credential(args.credential_id)
        output_data["valid"] = is_valid

        if args.json:
            print(json.dumps(output_data, indent=2, default=str))
        else:
            print(f"Credential: {cred.id}")
            print(f"Type: {cred.credential_type.value}")
            print(f"Storage: {_format_storage_type(store)}")
            print(f"Status: {'valid' if is_valid else 'invalid'}")
            print(f"Provider: {cred.provider_id or 'none'}")
            print(f"Auto-refresh: {cred.auto_refresh}")
            print("\nKeys:")
            for key_name, key_info in keys_data.items():
                print(f"  {key_name}: {key_info['value']}")
                if "expires_at" in key_info:
                    status = " (expired)" if key_info.get("is_expired") else ""
                    print(f"    Expires: {key_info['expires_at']}{status}")

        return 0
    except Exception as e:
        print(f"Error showing credential: {e}", file=sys.stderr)
        return 1


def cmd_add(args: argparse.Namespace) -> int:
    """
    Interactively add a new credential.

    Prompts the user for credential details including key names and values.
    Uses secure input (getpass) for secret values to prevent terminal echo.
    """
    try:
        # Check if credential already exists
        store = _get_store()
        if store.is_available(args.credential_id):
            response = input(
                f"Credential '{args.credential_id}' already exists. Overwrite? [y/N]: "
            ).strip()
            if response.lower() != "y":
                print("Cancelled.")
                return 0

        # Map type string to CredentialType enum
        type_map = {
            "static": CredentialType.API_KEY,
            "api_key": CredentialType.API_KEY,
            "oauth2": CredentialType.OAUTH2,
            "bearer_token": CredentialType.BEARER_TOKEN,
            "custom": CredentialType.CUSTOM,
        }
        cred_type = type_map.get(args.type, CredentialType.API_KEY)

        # Collect keys interactively
        keys: dict[str, CredentialKey] = {}
        print(f"\nAdding credential '{args.credential_id}' (type: {cred_type.value})")
        print("Enter key-value pairs. Press Enter with empty key name to finish.\n")

        while True:
            key_name = input("Key name (e.g., 'api_key', 'access_token'): ").strip()
            if not key_name:
                break

            if key_name in keys:
                print(f"Warning: Key '{key_name}' already added. Overwriting...")

            # Use getpass for secret input to prevent terminal echo
            key_value = getpass.getpass(f"Value for '{key_name}': ")
            if not key_value:
                print("Warning: Empty value. Skipping this key.")
                continue

            # Ask for expiration (optional)
            expires_str = input(
                "Expiration date (YYYY-MM-DD HH:MM:SS UTC, or press Enter to skip): "
            ).strip()
            expires_at = None
            if expires_str:
                try:
                    expires_at = datetime.strptime(expires_str, "%Y-%m-%d %H:%M:%S").replace(
                        tzinfo=UTC
                    )
                except ValueError:
                    print("Warning: Invalid date format. Skipping expiration.")
                    expires_at = None

            keys[key_name] = CredentialKey(
                name=key_name, value=SecretStr(key_value), expires_at=expires_at
            )

        if not keys:
            print("Error: At least one key is required.", file=sys.stderr)
            return 1

        # Create credential object
        credential = CredentialObject(
            id=args.credential_id,
            credential_type=cred_type,
            keys=keys,
        )

        # Save based on storage backend
        if args.storage == "env":
            # For env storage, we'd need to handle this differently
            # For now, just use file storage and warn
            print(
                "Warning: Environment variable storage requires manual setup.",
                file=sys.stderr,
            )
            print("Saving to encrypted file storage instead.", file=sys.stderr)
            store.save_credential(credential)
        else:
            store.save_credential(credential)

        print(f"Successfully saved credential '{args.credential_id}'")
        return 0
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error adding credential: {e}", file=sys.stderr)
        return 1


def cmd_delete(args: argparse.Namespace) -> int:
    """
    Delete a credential from storage.

    Prompts for confirmation unless --force flag is used.
    """
    try:
        store = _get_store()

        # Check if credential exists
        if not store.is_available(args.credential_id):
            print(f"Error: Credential '{args.credential_id}' not found.", file=sys.stderr)
            return 1

        # Confirm deletion unless forced
        if not args.force:
            response = input(
                f"Are you sure you want to delete credential '{args.credential_id}'? [y/N]: "
            ).strip()
            if response.lower() != "y":
                print("Cancelled.")
                return 0

        # Delete the credential
        deleted = store.delete_credential(args.credential_id)
        if deleted:
            print(f"Successfully deleted credential '{args.credential_id}'")
            return 0
        else:
            print(f"Error: Failed to delete credential '{args.credential_id}'", file=sys.stderr)
            return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error deleting credential: {e}", file=sys.stderr)
        return 1


def cmd_test(args: argparse.Namespace) -> int:
    """
    Test and validate a credential.

    Checks if the credential exists, is properly configured, and validates
    its structure and any registered usage requirements.
    """
    try:
        store = _get_store()
        cred = store.get_credential(args.credential_id, refresh_if_needed=False)

        if cred is None:
            print(f"Error: Credential '{args.credential_id}' not found.", file=sys.stderr)
            return 1

        # Validate the credential
        is_valid = store.validate_credential(args.credential_id)

        # Check for usage spec validation errors
        usage_errors = store.validate_for_usage(args.credential_id)

        print(f"Testing credential '{args.credential_id}'...\n")
        print(f"Status: {'valid' if is_valid else 'invalid'}")

        if cred.keys:
            print(f"Keys: {len(cred.keys)} ({', '.join(cred.keys.keys())})")

        # Check expiration
        expired_keys = []
        expiring_soon_keys = []
        for key_name, key_obj in cred.keys.items():
            if key_obj.expires_at:
                if key_obj.is_expired:
                    expired_keys.append(key_name)
                else:
                    # Check if expiring within 7 days
                    days_until_expiry = (key_obj.expires_at - datetime.now(UTC)).days
                    if 0 <= days_until_expiry <= 7:
                        expiring_soon_keys.append(
                            (key_name, key_obj.expires_at.strftime("%Y-%m-%d %H:%M:%S UTC"))
                        )

        if expired_keys:
            print(f"Warning: Expired keys: {', '.join(expired_keys)}")
        if expiring_soon_keys:
            for key_name, expiry in expiring_soon_keys:
                print(f"Warning: Key '{key_name}' expires soon: {expiry}")

        if usage_errors:
            print("\nValidation errors:")
            for error in usage_errors:
                print(f"  - {error}")
            return 1

        if is_valid:
            print("\nCredential is valid and ready to use.")
            return 0
        else:
            print("\nCredential validation failed.")
            return 1
    except Exception as e:
        print(f"Error testing credential: {e}", file=sys.stderr)
        return 1


def cmd_refresh(args: argparse.Namespace) -> int:
    """
    Manually refresh an OAuth2 credential.

    Triggers the refresh process for OAuth2 credentials that support
    token refresh. This is useful when tokens expire or need to be
    refreshed outside of the automatic refresh cycle.
    """
    try:
        store = _get_store()
        cred = store.get_credential(args.credential_id, refresh_if_needed=False)

        if cred is None:
            print(f"Error: Credential '{args.credential_id}' not found.", file=sys.stderr)
            return 1

        if cred.credential_type != CredentialType.OAUTH2:
            print(
                f"Error: Credential '{args.credential_id}' is not an OAuth2 credential.",
                file=sys.stderr,
            )
            return 1

        print(f"Refreshing credential '{args.credential_id}'...")

        # Attempt to refresh
        refreshed = store.refresh_credential(args.credential_id)

        if refreshed is None:
            print(
                "Error: Failed to refresh credential. Check provider configuration.",
                file=sys.stderr,
            )
            return 1

        # Show new expiration if available
        for key_obj in refreshed.keys.values():
            if key_obj.expires_at:
                print("Successfully refreshed.")
                print(f"New expiration: {key_obj.expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                return 0

        print("Successfully refreshed (no expiration set).")
        return 0
    except Exception as e:
        print(f"Error refreshing credential: {e}", file=sys.stderr)
        return 1
