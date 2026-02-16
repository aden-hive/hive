# Shortcut Tool

Integration with Shortcut (formerly Clubhouse) for project management.

## Features

- Create stories (`create_shortcut_story`)
- Search stories (`search_shortcut_stories`)

## Environment Variables

- `SHORTCUT_API_TOKEN`: Required for authentication
- `SHORTCUT_BASE_URL`: Optional (default: `https://api.app.shortcut.com/api/v3`)

## Limitations

- Currently supports `story` operations only.
- `search` is limited to basic queries.
