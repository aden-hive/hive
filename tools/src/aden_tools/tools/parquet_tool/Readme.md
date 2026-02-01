# Parquet Tool

Read, preview, sample, and run structured queries on Parquet files within the workspace.

## Description

A set of MCP tools to inspect Parquet schemas, preview rows, sample data, and run safe, structured SELECT queries (with column allowlists and limits) using DuckDB. All file access is constrained to the current workspace/session via secure path checks.

## Tools & Arguments

### `parquet_info`
| Argument         | Type   | Required | Default | Description                               |
|------------------|--------|----------|---------|-------------------------------------------|
| `file_path`      | str    | Yes      | –       | Workspace-relative path to a `.parquet`   |
| `workspace_id`   | str    | Yes      | –       | Workspace ID                              |
| `agent_id`       | str    | Yes      | –       | Agent ID                                  |
| `session_id`     | str    | Yes      | –       | Session ID                                |
| `columns_limit`  | int    | Yes      | –       | Max columns to include in the schema list |

### `parquet_preview`
| Argument       | Type        | Required | Default | Description                                  |
|----------------|-------------|----------|---------|----------------------------------------------|
| `file_path`    | str         | Yes      | –       | Workspace-relative path to a `.parquet`      |
| `workspace_id` | str         | Yes      | –       | Workspace ID                                 |
| `agent_id`     | str         | Yes      | –       | Agent ID                                     |
| `session_id`   | str         | Yes      | –       | Session ID                                   |
| `limit`        | int         | No       | `100`   | Row cap (capped at 100)                      |
| `columns`      | list[str]   | No       | `None`  | Subset of columns to return                  |
| `where`        | str         | No       | `None`  | Optional SQL WHERE clause (use cautiously)   |

### `sample_parquet`
| Argument       | Type | Required | Default | Description                                 |
|----------------|------|----------|---------|---------------------------------------------|
| `file_path`    | str  | Yes      | –       | Workspace-relative path to a `.parquet`     |
| `n`            | int  | No       | `5`     | Number of sample rows (capped at 100)       |
| `workspace_id` | str  | Yes      | –       | Workspace ID                                |
| `agent_id`     | str  | Yes      | –       | Agent ID                                    |
| `session_id`   | str  | Yes      | –       | Session ID                                  |

### `run_sql_on_parquet` (structured SELECT only)
| Argument            | Type                      | Required | Default   | Description                                        |
|---------------------|---------------------------|----------|-----------|----------------------------------------------------|
| `file_path`         | str                       | Yes      | –         | Workspace-relative path to a `.parquet`            |
| `workspace_id`      | str                       | Yes      | –         | Workspace ID                                       |
| `agent_id`          | str                       | Yes      | –         | Agent ID                                           |
| `session_id`        | str                       | Yes      | –         | Session ID                                         |
| `selected_columns`  | list[str] \| None         | No       | `["*"]`   | Columns to project (validated against schema)      |
| `filters`           | list[tuple[str,str,Any]]  | No       | `None`    | WHERE predicates, e.g. `[("age", ">", 28)]`        |
| `group_by`          | list[str] \| None         | No       | `None`    | GROUP BY columns                                   |
| `order_by`          | list[tuple[str,str]]      | No       | `None`    | ORDER BY clauses, e.g. `[("age","desc")]`          |
| `limit`             | int \| None               | No       | `100`     | Row cap (1–100)                                    |
| `query`             | str                       | No       | `""`      | Ignored (kept for backward compatibility)          |

## Environment Variables

None required. DuckDB must be available in the environment (`pip install duckdb`).

## Error Handling

Common error responses include:
- `{"error": "The file does not exist."}` – Missing file
- `{"error": "The file is not a parquet file."}` – Wrong extension
- `{"error": "Column not found: <name>"}` – Requested column absent
- `{"error": "Operator not allowed: <op>"}` – Disallowed filter operator
- `{"error": "<DuckDB error message>"}` – Underlying DuckDB issues (e.g., invalid syntax)
- Limits are clamped to 1–100; invalid limits return an error

## Notes

- Paths are secured via `secure_parquet_path` and must be workspace-relative.
- SELECT-only: no DDL/DML; filter operators are allowlisted.
- Column names are quoted to avoid injection; limits protect against large reads.
