# Excel Tools

All operations use sandbox-relative paths.  
Tools registered via `excel_tool.py`.

- `excel_read` — Read sheet data (limit/offset support)  
- `excel_write` — Create new Excel file with headers + rows  
- `excel_append` — Add rows to existing sheet  
- `excel_info` — Get metadata (sheets, columns, row counts, file size)  
- `excel_sheet_list` — List all sheet names  
- `excel_sql` — Run SELECT queries (DuckDB, multi-sheet joins)  
- `excel_search` — Text search across sheets  
- `excel_add_sheet` — Create new sheet  
- `excel_rename_sheet` — Rename sheet  
- `excel_delete_sheet` — Delete sheet (not last one)  
- `excel_update_cell` — Change single cell value  
- `excel_delete_row` — Delete data row (≥ row 2)  
- `excel_add_column` — Add new column + default value  
- `excel_sort` — Sort sheet by column(s)

Use secure_path internally — no direct filesystem access.
