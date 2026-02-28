# PowerPoint Tool (Schema-First)

Generates local `.pptx` slide decks from a strict Pydantic schema.

## Tool
- `powerpoint_generate(path, deck, workspace_id, agent_id, session_id)`

## Schema
- DeckSpec: { title: str, slides: [SlideSpec] }
- SlideSpec: { title: str, bullets: [str], image_paths: [str] }

## Notes
- `path` and `image_paths` are relative to the session sandbox.
- Uses `python-pptx` (optional dependency group: `powerpoint`).
