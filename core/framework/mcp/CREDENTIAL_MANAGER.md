# Credential Manager MCP Server

An MCP (Model Context Protocol) server for secure credential management in Hive.

## Features

- **List credentials**: View all available credential IDs
- **Retrieve credentials**: Safely access credential values with audit logging
- **Validate credentials**: Check credential health and provider status
- **Rotate encryption keys**: Re-encrypt all credentials with a new key atomically
- **Save/delete credentials**: Manage secrets programmatically
- **Generate keys**: Create new Fernet encryption keys
- **Health checks**: Validate credential storage integrity

## Usage

### Start the Server

```bash
cd core
uv run python -m framework.mcp.credential_manager_server
```

### Available Tools

#### list_credentials
List all available credential IDs in storage.

```
Tool: list_credentials
Returns: JSON array of credential IDs
```

#### get_credential
Retrieve a credential value by ID (logged for audit).

```
Tool: get_credential
Input: credential_id (string)
Returns: Credential value (masked in logs)
```

#### validate_credential
Check if a credential is valid and accessible.

```
Tool: validate_credential
Input: credential_id (string)
Returns: Validation status and any errors
```

#### rotate_encryption_key
Re-encrypt all credentials with a new encryption key.

```
Tool: rotate_encryption_key
Input: new_key_b64 (base64-encoded Fernet key)
Returns: Status of rotation
```

Example:
```bash
# Generate new key
new_key=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Rotate (via MCP client)
mcp_client.call_tool("rotate_encryption_key", {"new_key_b64": new_key})
```

#### save_credential
Save a new credential to encrypted storage.

```
Tool: save_credential
Inputs:
  - credential_id: string
  - credential_value: string (the secret)
  - credential_type: API_KEY | OAUTH2 | BEARER_TOKEN | etc.
Returns: Status message
```

#### delete_credential
Remove a credential from storage.

```
Tool: delete_credential
Input: credential_id (string)
Returns: Status message
```

#### check_credential_health
Validate all credentials for integrity and accessibility.

```
Tool: check_credential_health
Returns: Health report with OK/ERROR counts
```

#### generate_fernet_key
Generate a new Fernet encryption key for rotation.

```
Tool: generate_fernet_key
Returns: Base64-encoded key ready for use
```

## Security Considerations

- **Audit logging**: All credential access is logged (values masked)
- **Encryption**: Credentials stored with Fernet (AES-128-CBC + HMAC) at rest
- **Atomicity**: Key rotation uses atomic writes to prevent partial failures
- **Validation**: Provider validation (e.g., OAuth refresh) when available

## Typical Workflow

### Initial Setup
```bash
# 1. Generate encryption key
key=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
export HIVE_CREDENTIAL_KEY=$key

# 2. Start server
python -m framework.mcp.credential_manager_server

# 3. Save initial credentials
mcp_client.call_tool("save_credential", {
    "credential_id": "github_token",
    "credential_value": "ghp_...",
    "credential_type": "BEARER_TOKEN"
})
```

### Routine Key Rotation
```bash
# 1. Generate new key
new_key=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# 2. Backup existing credentials
cp -r ~/.hive/credentials ~/.hive/credentials.backup

# 3. Rotate key
mcp_client.call_tool("rotate_encryption_key", {"new_key_b64": new_key})

# 4. Verify health
mcp_client.call_tool("check_credential_health", {})

# 5. Update env var
export HIVE_CREDENTIAL_KEY=$new_key

# 6. Clean up old backup (after verification)
rm -rf ~/.hive/credentials.backup
```

## Integration

The server integrates with:
- `framework.credentials.CredentialStore` — main credential storage
- `framework.credentials.EncryptedFileStorage` — Fernet-encrypted file backend
- Credential validation providers (OAuth2, static, etc.)

## Troubleshooting

### "Storage backend does not support key rotation"
- Ensure you're using `EncryptedFileStorage` (not `EnvVarStorage`)
- Check: `store._storage.__class__.__name__` should be `EncryptedFileStorage`

### "Invalid key format"
- Ensure the key is base64-encoded Fernet key bytes
- Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

### Corruption during rotation
- Key rotation is atomic per file, but network/process interruption can cause issues
- Always backup credentials before rotating: `cp -r ~/.hive/credentials backup/`
- If corruption occurs, restore from backup and try again with correct key

