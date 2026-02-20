# Excel Write Tool (Schema-First)

Writes `.xlsx` workbooks with multi-sheet support and basic formatting.

## Tool
- `excel_write(path, workbook, workspace_id, agent_id, session_id)`

## Features (MVP)
- Multi-sheet
- Header styling (bold)
- Freeze panes
- Per-column number formats
- Best-effort column autosize

## Schema
- WorkbookSpec: { sheets: [SheetSpec] }
- SheetSpec: { name, columns, rows, freeze_panes?, number_formats?, column_widths? }

