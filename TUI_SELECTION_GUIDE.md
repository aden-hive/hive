# TUI Text Selection and Copy Guide

The Aden TUI now supports text selection and copying from the log pane!

## How to Select and Copy Text:

### 1. **Focus the Log Pane**
   - Press `Tab` to cycle through panels (Graph View → Log Pane → Chat Input)
   - Or click directly on the blue log pane
   - When focused, the border will be brighter

### 2. **Select Text**
   - **Mouse Selection**: Click and drag to select text
   - **Keyboard Selection** (if supported by your terminal):
     - Use arrow keys to navigate
     - Hold `Shift` + arrow keys to select

### 3. **Copy Text**
   - **Windows**: `Ctrl+C` or right-click → Copy
   - **Mac**: `Cmd+C`
   - **Linux**: `Ctrl+Shift+C` or right-click → Copy

### 4. **Navigate Panels**
   - `Tab`: Move to next panel
   - `Shift+Tab`: Move to previous panel
   - `Q`: Quit the TUI

## Notes:
- The RichLog widget supports native text selection
- Copying works through your terminal's clipboard
- Auto-scroll is enabled, but you can scroll manually when focused
- The log pane shows a highlighted border when focused

## Troubleshooting:
If text selection doesn't work:
1. Make sure your terminal supports mouse mode (most modern terminals do)
2. Try clicking and dragging with your mouse
3. Some terminals require holding `Shift` while selecting
