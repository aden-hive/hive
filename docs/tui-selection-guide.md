# TUI Dashboard Guide

## Launching the TUI

There are two ways to launch the TUI dashboard:

```bash
# Browse and select an agent interactively
hive tui

# Launch the TUI for a specific agent
hive run exports/my_agent --tui
```

`hive tui` scans both `exports/` and `examples/templates/` for available agents, then presents a selection menu.

## Dashboard Panels

The TUI dashboard is divided into four areas:

- **Status Bar** - Shows the current agent name, execution state, and model in use
- **Graph Overview** - Live visualization of the agent's node graph with highlighted active node
- **Log Pane** - Scrollable event log streaming node transitions, LLM calls, and tool outputs
- **Chat REPL** - Input area for interacting with client-facing nodes (`ask_user()` prompts appear here)

## Keybindings

| Key           | Action                |
|---------------|-----------------------|
| `Tab`         | Next panel            |
| `Shift+Tab`   | Previous panel        |
| `Ctrl+S`      | Save SVG screenshot   |
| `Ctrl+O`      | Command palette       |
| `Q`           | Quit                  |

## Panel Cycle Order

`Tab` cycles: **Log Pane → Graph View → Chat Input**

## Text Selection

Textual apps capture the mouse, so normal click-drag selection won't work by default. To select and copy text from any pane:

1. **Hold `Shift`** while clicking and dragging — this bypasses Textual's mouse capture and lets your terminal handle selection natively.
2. Copy with your terminal's shortcut (`Cmd+C` on macOS, `Ctrl+Shift+C` on most Linux terminals).

## Log Pane Scrolling

The log pane uses `auto_scroll=False`. New output only scrolls to the bottom when you are already at the bottom of the log. If you've scrolled up to read earlier output, it stays in place.

## Screenshots

`Ctrl+S` saves an SVG screenshot to the `screenshots/` directory with a timestamped filename. Open the SVG in any browser to view it.

## Tips

- Use `--mock` mode to explore agent execution without spending API credits: `hive run exports/my_agent --tui --mock`
- Override the default model with `--model`: `hive run exports/my_agent --model gpt-4o`
- Screenshots are saved as SVG files to `screenshots/` and can be opened in any browser
