# Example Tool

A template tool demonstrating the Aden tools pattern.

## Description

This tool processes text messages with optional transformations. It serves as a reference implementation for creating new tools using the FastMCP decorator pattern.

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `message` | str | Yes | - | The message to process (1-1000 chars) |
| `uppercase` | bool | No | `False` | Convert message to uppercase |
| `repeat` | int | No | `1` | Number of times to repeat (1-10) |

## Environment Variables

This tool does not require any environment variables.

## Error Handling

Returns error strings for validation issues:
- `Error: message must be 1-1000 characters` - Empty or too long message
- `Error: repeat must be 1-10` - Repeat value out of range
- `Error processing message: <error>` - Unexpected error
