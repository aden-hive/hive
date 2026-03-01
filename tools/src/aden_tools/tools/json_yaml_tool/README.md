# JSON/YAML Validation Tool

A tool for validating and converting JSON and YAML data structures.

## Features

- **JSON Validation**: Validate JSON syntax and optionally against JSON Schema
- **YAML Validation**: Validate YAML syntax and structure using safe loading
- **JSON to YAML Conversion**: Convert JSON documents to YAML format
- **YAML to JSON Conversion**: Convert YAML documents to JSON format

## Tools

### `validate_json`

Validate JSON content and optionally validate against a JSON Schema.

**Parameters:**
- `content` (str): JSON string to validate
- `schema` (dict, optional): JSON Schema dictionary to validate against

**Returns:**
- `valid` (bool): Whether the JSON is valid
- `data` (dict/list): Parsed JSON data (if valid)
- `error` (str): Error message (if invalid)

**Example:**
```python
result = validate_json(
    content='{"name": "agent", "version": 1}',
    schema={"type": "object", "required": ["name"]}
)
# Returns: {"valid": True, "data": {"name": "agent", "version": 1}}
```

### `validate_yaml`

Validate YAML content and parse it.

**Parameters:**
- `content` (str): YAML string to validate

**Returns:**
- `valid` (bool): Whether the YAML is valid
- `data` (dict/list): Parsed YAML data (if valid)
- `error` (str): Error message (if invalid)

**Example:**
```python
result = validate_yaml(content='name: agent\nversion: 1')
# Returns: {"valid": True, "data": {"name": "agent", "version": 1}}
```

### `json_to_yaml`

Convert JSON content to YAML format.

**Parameters:**
- `content` (str): JSON string to convert
- `indent` (int, optional): Number of spaces for YAML indentation (default: 2)
- `default_flow_style` (bool, optional): Use flow style for nested structures (default: False)

**Returns:**
- `success` (bool): Whether conversion was successful
- `yaml` (str): YAML output (if successful)
- `error` (str): Error message (if failed)

**Example:**
```python
result = json_to_yaml(content='{"key": "value", "nested": {"a": 1}}')
# Returns: {"success": True, "yaml": "key: value\nnested:\n  a: 1"}
```

### `yaml_to_json`

Convert YAML content to JSON format.

**Parameters:**
- `content` (str): YAML string to convert
- `indent` (int, optional): Number of spaces for JSON indentation (default: 2)

**Returns:**
- `success` (bool): Whether conversion was successful
- `json` (str): JSON output (if successful)
- `error` (str): Error message (if failed)

**Example:**
```python
result = yaml_to_json(content='key: value\nnested:\n  a: 1')
# Returns: {"success": True, "json": '{"key": "value", "nested": {"a": 1}}'}
```

## Security Considerations

- Uses `yaml.safe_load` for YAML parsing to prevent arbitrary code execution
- Input size limited to 10MB to prevent DoS attacks
- Clear error messages without exposing internal details

## Dependencies

- `pyyaml`: YAML parsing and serialization
- `jsonschema` (optional): JSON Schema validation
