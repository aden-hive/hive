# Hash Tool

A utility tool for computing cryptographic hashes of text content.

## Description

This tool computes cryptographic hashes using various algorithms. Use it to verify content integrity, detect changes, generate unique identifiers, or compute checksums for text content.

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `text` | str | Yes | - | The text to hash (1-100000 chars) |
| `algorithm` | str | No | `sha256` | Hash algorithm: md5, sha1, sha256, sha512 |

## Returns

On success:
```json
{
  "algorithm": "sha256",
  "hash": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
  "length": 5
}
```

On error:
```json
{
  "error": "text must be 1-100000 characters"
}
```

## Environment Variables

This tool does not require any environment variables.

## Usage Examples

### Basic SHA256 hash (default)
```python
result = hash_tool(text="hello")
# Returns: {"algorithm": "sha256", "hash": "2cf24...", "length": 5}
```

### MD5 hash
```python
result = hash_tool(text="hello world", algorithm="md5")
# Returns: {"algorithm": "md5", "hash": "5eb63bbbe01eeed093cb22bb8f5acdc3", "length": 11}
```

### SHA512 for stronger security
```python
result = hash_tool(text="sensitive data", algorithm="sha512")
```

## Error Handling

Returns error dicts for validation issues:
- `text must be 1-100000 characters` - Empty or too long input
- `algorithm must be one of: md5, sha1, sha256, sha512` - Invalid algorithm
- `Hash computation failed: <error>` - Unexpected error

## Use Cases

- **Content verification**: Check if file contents changed
- **Deduplication**: Generate unique IDs for content
- **Integrity checks**: Verify data hasn't been corrupted
- **Caching keys**: Create deterministic cache identifiers
