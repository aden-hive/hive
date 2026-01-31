# Changes (2026-01-29)

## What I changed
- Added a Windows-safe console configuration helper (`framework.runtime.console.configure_console_output`) and wired it into the CLI entrypoint and the manual agent example.
- Improved `FunctionNode` input handling to pull missing inputs from shared memory, and added support for dict/tuple outputs when multiple `output_keys` are defined.
- Updated `core/examples/manual_agent.py` to accept a `style` input and produce a visibly different greeting output (example uses `reverse`).
- Fixed `hive list` output to use the stored node count key instead of a missing `steps` key.

## How to run
```
$env:PYTHONPATH="core"
.\.venv\Scripts\python.exe core\examples\manual_agent.py
```

## Example output
```
Final output: !ecilA ,olleH
```

Notes:
- If you see a warning about `CEREBRAS_API_KEY` not being set, that is expected unless you have configured the output-cleaning LLM.
