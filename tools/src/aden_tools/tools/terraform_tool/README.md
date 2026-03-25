# Terraform Tool

Manage workspaces and runs via the Terraform Cloud / HCP Terraform REST API v2.

## Supported Actions

- **terraform_list_workspaces** – List workspaces in an organization
- **terraform_get_workspace** – Get workspace details (VCS settings, execution mode, last run)
- **terraform_list_runs** – List runs for a workspace with status filtering
- **terraform_get_run** – Get detailed run information (plan, apply, cost estimate)
- **terraform_create_run** – Trigger a new plan/apply run

## Setup

1. Create an API token at [Terraform Cloud](https://app.terraform.io/app/settings/tokens) (User, Team, or Organization token).

2. Set the required environment variables:
   ```bash
   export TFC_TOKEN=your-terraform-cloud-token
   ```

3. For Terraform Enterprise (self-hosted):
   ```bash
   export TFC_URL=https://your-tfe-instance.example.com
   ```

## Use Case

Example: "List all workspaces in the production organization, check which ones have pending runs, and trigger a plan for any workspace that hasn't been applied in the last 7 days."
