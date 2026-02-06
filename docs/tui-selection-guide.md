# TUI Text Selection and Copy Guide

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
