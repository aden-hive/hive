# Release Notes Generator Agent

This agent automatically generates structured release notes from GitHub repository commits.

## Features

- Fetches recent commits from a GitHub repository
- Classifies changes into categories (Features, Bug Fixes, Improvements, Breaking Changes)
- Generates formatted release notes

## Setup

### GitHub Credentials

This agent requires GitHub API access. You need to set up a GitHub Personal Access Token:

1. Go to [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens)
2. Click "Generate new token" > "Generate new token (classic)"
3. Give it a descriptive name (e.g., "Hive Release Notes Agent")
4. Select these scopes:
   - `repo` (Full control of private repositories) - if you need private repos
   - `public_repo` (Access public repositories) - for public repos only
5. Click "Generate token" and copy the token
6. Set the environment variable: `export GITHUB_TOKEN=ghp_...`

Or configure it through the Hive credential store.

## Usage

Run the agent and provide:
- Repository in format `owner/repo` (e.g., `aden-hive/hive`)
- Version tag (e.g., `v1.2.0`)
- Optional: Since date in ISO format (e.g., `2024-01-01T00:00:00Z`) to filter commits

The agent will generate release notes like:

```
Release v1.2.0

Features
- Add OAuth login support

Bug Fixes
- Fix login redirect issue

Improvements
- Improve API response time
```

## Testing

To test the agent without credentials, it will prompt you to set them up. Make sure to:

1. Set `GITHUB_TOKEN` environment variable
2. Or configure through Hive credential store
3. Test with a public repository first (e.g., `octocat/Hello-World`)

## Video Recording

When recording a demo video:
1. Use a repository with recent commits
2. Show the credential setup process
3. Demonstrate with different date ranges
4. Show the structured output format