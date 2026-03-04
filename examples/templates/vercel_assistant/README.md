# Vercel Assistant Agent

An interactive assistant for managing Vercel deployments, projects, and environment variables through natural language commands.

## Features

- **List Projects**: View all your Vercel projects with optional search and filtering
- **Create Deployments**: Deploy projects to production or preview environments
- **Check Status**: Monitor deployment status and get real-time updates
- **Set Environment Variables**: Manage environment variables across environments

## Prerequisites

Before using this agent, you need:

1. **Vercel Account**: Sign up at [vercel.com](https://vercel.com)
2. **Vercel Auth Token**: Generate a token at [vercel.com/account/tokens](https://vercel.com/account/tokens)
3. **Set Environment Variable**: 
   ```bash
   export VERCEL_AUTH_TOKEN="your_token_here"
   ```

## Usage

### Interactive Shell Mode (Recommended)

```bash
cd /path/to/hive
PYTHONPATH=exports uv run python -m vercel_assistant shell
```

Then interact with the assistant:
```
Task> list my projects
Task> create a deployment for project abc123
Task> check status of deployment dpl_xyz789
Task> set environment variable API_KEY for project abc123
```

### Single Task Mode

```bash
cd /path/to/hive
PYTHONPATH=exports uv run python -m vercel_assistant run --task "list all projects"
```

### TUI Dashboard Mode

```bash
cd /path/to/hive
PYTHONPATH=exports uv run python -m vercel_assistant tui
```

### Validate Agent

```bash
cd /path/to/hive
PYTHONPATH=exports uv run python -m vercel_assistant validate
```

### View Agent Info

```bash
cd /path/to/hive
PYTHONPATH=exports uv run python -m vercel_assistant info
```

## Example Interactions

### List Projects
```
You: List all my Vercel projects
Assistant: I'll list all your Vercel projects for you.
[Calls vercel_list_projects tool]
You have 3 projects:
1. my-nextjs-app (Next.js) - https://github.com/user/my-nextjs-app
2. api-server (Node.js) - https://github.com/user/api-server
3. portfolio (React) - https://github.com/user/portfolio
```

### Create Deployment
```
You: Deploy project my-nextjs-app to production
Assistant: I'll create a production deployment for my-nextjs-app.
[Calls vercel_create_deployment tool]
Deployment created successfully!
Deployment ID: dpl_abc123
URL: https://my-nextjs-app.vercel.app
Status: BUILDING
```

### Check Deployment Status
```
You: What's the status of deployment dpl_abc123?
Assistant: Let me check the status of that deployment.
[Calls vercel_get_deployment_status tool]
Deployment Status: READY
URL: https://my-nextjs-app.vercel.app
Deployed at: 2026-03-04 12:34:56
```

### Set Environment Variable
```
You: Set API_KEY to secret123 for my-nextjs-app in production
Assistant: I'll set the API_KEY environment variable for my-nextjs-app in production.
[Calls vercel_set_env_variable tool]
Environment variable set successfully!
Key: API_KEY
Target: production
```

## Architecture

The agent uses a 3-node workflow:

1. **Intake Node** (client-facing): Understands what the user wants to do
2. **Action Node**: Executes the appropriate Vercel tool
3. **Review Node** (client-facing): Presents results and asks what's next

## Tools Used

- `vercel_list_projects` - List Vercel projects
- `vercel_create_deployment` - Create new deployments
- `vercel_get_deployment_status` - Check deployment status
- `vercel_set_env_variable` - Set environment variables

## Error Handling

The agent provides clear error messages and guidance:

- **Missing Credentials**: Explains how to set VERCEL_AUTH_TOKEN
- **Invalid Project ID**: Suggests listing projects first
- **API Errors**: Provides actionable solutions

## Development

### Running Tests

```bash
cd tools
uv run pytest tests/tools/test_vercel_tool.py -v
```

### Modifying the Agent

- **Nodes**: Edit `exports/vercel_assistant/nodes/__init__.py`
- **Edges**: Edit `exports/vercel_assistant/agent.py`
- **Configuration**: Edit `exports/vercel_assistant/config.py`

## Troubleshooting

### "Vercel credentials not configured"

Make sure you've set the VERCEL_AUTH_TOKEN environment variable:
```bash
export VERCEL_AUTH_TOKEN="your_token_here"
```

### "Invalid auth token"

Generate a new token at [vercel.com/account/tokens](https://vercel.com/account/tokens)

### "Project not found"

List your projects first to get the correct project ID:
```
Task> list my projects
```

## License

Apache 2.0 - See LICENSE file for details
