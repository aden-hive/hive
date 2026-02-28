# Power BI Tool

Power BI integration for automated dataset refresh, report export, and workspace management.

## Features

- **Workspace Management**: List all available Power BI workspaces
- **Dataset Operations**: List and refresh datasets programmatically
- **Report Management**: List reports and export to PDF/PowerPoint
- **OAuth2 Authentication**: Secure credential storage via Hive credential system

## Available Functions

### `power_bi_get_workspaces()`
Get list of all Power BI workspaces accessible to the authenticated user.

### `power_bi_get_datasets(workspace_id)`
List all datasets in a specific workspace.

**Args:**
- `workspace_id`: The Power BI workspace ID

### `power_bi_get_reports(workspace_id)`
List all reports in a specific workspace.

**Args:**
- `workspace_id`: The Power BI workspace ID

### `power_bi_refresh_dataset(workspace_id, dataset_id)`
Trigger a dataset refresh.

**Args:**
- `workspace_id`: The Power BI workspace ID
- `dataset_id`: The dataset ID to refresh

### `power_bi_export_report(workspace_id, report_id, format)`
Export a report to PDF or PowerPoint.

**Args:**
- `workspace_id`: The Power BI workspace ID
- `report_id`: The report ID to export
- `format`: Export format - "PDF" or "PPTX" (default: "PDF")

## Authentication

Requires Power BI access token obtained via OAuth2.

**Via Credential Store:**
```python
# Token stored securely in Hive credential store under key "power_bi"
```

**Via Environment Variable:**
```bash
export POWER_BI_ACCESS_TOKEN="your-token-here"
```

## Example Use Cases

**Business Analytics Agent:**
```
1. Monthly sales analysis completes
2. Agent calls power_bi_refresh_dataset() to update dashboard
3. Agent calls power_bi_export_report() to generate PDF
4. Report emailed to stakeholders automatically
```

**Marketing Agent:**
```
1. Identifies trending products from data analysis
2. Calls power_bi_refresh_dataset() on marketing dashboard
3. Team receives updated insights in real-time
```

## API Reference

Based on Power BI REST API v1.0: https://learn.microsoft.com/en-us/rest/api/power-bi/
