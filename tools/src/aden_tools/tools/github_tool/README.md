# GitHub Tool

Interact with GitHub repositories, issues, and pull requests within the Aden agent framework.

## Installation

The GitHub tool uses `httpx` which is already included in the base dependencies. No additional installation required.

## Setup

You need a GitHub Personal Access Token (PAT) to use this tool.

### Getting a GitHub Token

1. Go to https://github.com/settings/tokens
2. Click "Generate new token" → "Generate new token (classic)"
3. Give your token a descriptive name (e.g., "Aden Agent Framework")
4. Select the following scopes:
   - `repo` - Full control of private repositories (includes all repo scopes)
   - `read:org` - Read org and team membership (optional, for org access)
   - `user` - Read user profile data (optional)
5. Click "Generate token"
6. Copy the token (starts with `ghp_`)

**Note:** Keep your token secure! It provides access to your GitHub account.

### Configuration

Set the token as an environment variable:

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

Or configure via the credential store (recommended for production).

## Available Functions

### Repository Management

#### `github_list_repos`

List repositories for a user or the authenticated user.

**Parameters:**
- `username` (str, optional): GitHub username (if None, lists authenticated user's repos)
- `visibility` (str, optional): Repository visibility ("all", "public", "private", default "all")
- `sort` (str, optional): Sort order ("created", "updated", "pushed", "full_name", default "updated")
- `limit` (int, optional): Maximum number of repositories (1-100, default 30)

**Returns:**
```python
{
    "success": True,
    "data": [
        {
            "id": 123456,
            "name": "my-repo",
            "full_name": "username/my-repo",
            "description": "A cool project",
            "private": False,
            "html_url": "https://github.com/username/my-repo",
            "stargazers_count": 42,
            "forks_count": 7
        }
    ]
}
```

**Example:**
```python
# List your repositories
result = github_list_repos()

# List another user's public repositories
result = github_list_repos(username="octocat", limit=10)
```

#### `github_get_repo`

Get detailed information about a specific repository.

**Parameters:**
- `owner` (str): Repository owner (username or organization)
- `repo` (str): Repository name

**Returns:**
```python
{
    "success": True,
    "data": {
        "id": 123456,
        "name": "my-repo",
        "full_name": "owner/my-repo",
        "description": "Project description",
        "private": False,
        "default_branch": "main",
        "stargazers_count": 100,
        "forks_count": 25,
        "language": "Python",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-31T12:00:00Z"
    }
}
```

**Example:**
```python
result = github_get_repo(owner="adenhq", repo="hive")
print(f"Stars: {result['data']['stargazers_count']}")
```

#### `github_search_repos`

Search for repositories on GitHub.

**Parameters:**
- `query` (str): Search query (supports GitHub search syntax)
- `sort` (str, optional): Sort field ("stars", "forks", "updated")
- `limit` (int, optional): Maximum results (1-100, default 30)

**Returns:**
```python
{
    "success": True,
    "data": {
        "total_count": 1000,
        "items": [
            {
                "id": 123,
                "name": "awesome-python",
                "full_name": "user/awesome-python",
                "description": "A curated list",
                "stargazers_count": 5000
            }
        ]
    }
}
```

**Example:**
```python
# Search for Python repos with many stars
result = github_search_repos(
    query="language:python stars:>1000",
    sort="stars",
    limit=10
)

# Search in a specific organization
result = github_search_repos(query="org:adenhq agent")
```

### Issue Management

#### `github_list_issues`

List issues for a repository.

**Parameters:**
- `owner` (str): Repository owner
- `repo` (str): Repository name
- `state` (str, optional): Issue state ("open", "closed", "all", default "open")
- `limit` (int, optional): Maximum issues (1-100, default 30)

**Returns:**
```python
{
    "success": True,
    "data": [
        {
            "number": 42,
            "title": "Bug in feature X",
            "state": "open",
            "user": {"login": "username"},
            "labels": [{"name": "bug"}],
            "created_at": "2024-01-30T10:00:00Z",
            "html_url": "https://github.com/owner/repo/issues/42"
        }
    ]
}
```

**Example:**
```python
# List open issues
issues = github_list_issues(owner="adenhq", repo="hive", state="open")
for issue in issues["data"]:
    print(f"#{issue['number']}: {issue['title']}")
```

#### `github_get_issue`

Get a specific issue by number.

**Parameters:**
- `owner` (str): Repository owner
- `repo` (str): Repository name
- `issue_number` (int): Issue number

**Returns:**
```python
{
    "success": True,
    "data": {
        "number": 42,
        "title": "Issue title",
        "body": "Detailed description...",
        "state": "open",
        "user": {"login": "username"},
        "assignees": [],
        "labels": [{"name": "enhancement"}],
        "comments": 5
    }
}
```

**Example:**
```python
issue = github_get_issue(owner="adenhq", repo="hive", issue_number=2805)
print(issue["data"]["body"])
```

#### `github_create_issue`

Create a new issue in a repository.

**Parameters:**
- `owner` (str): Repository owner
- `repo` (str): Repository name
- `title` (str): Issue title
- `body` (str, optional): Issue description (supports Markdown)
- `labels` (list[str], optional): List of label names
- `assignees` (list[str], optional): List of usernames to assign

**Returns:**
```python
{
    "success": True,
    "data": {
        "number": 43,
        "title": "New issue",
        "html_url": "https://github.com/owner/repo/issues/43"
    }
}
```

**Example:**
```python
result = github_create_issue(
    owner="myorg",
    repo="myrepo",
    title="Add new feature",
    body="## Description\n\nWe need to add...",
    labels=["enhancement", "help wanted"],
    assignees=["developer1"]
)
print(f"Created issue #{result['data']['number']}")
```

#### `github_update_issue`

Update an existing issue.

**Parameters:**
- `owner` (str): Repository owner
- `repo` (str): Repository name
- `issue_number` (int): Issue number
- `title` (str, optional): New title
- `body` (str, optional): New body
- `state` (str, optional): New state ("open" or "closed")
- `labels` (list[str], optional): New list of label names

**Returns:**
```python
{
    "success": True,
    "data": {
        "number": 43,
        "title": "Updated title",
        "state": "closed"
    }
}
```

**Example:**
```python
# Close an issue
result = github_update_issue(
    owner="myorg",
    repo="myrepo",
    issue_number=43,
    state="closed",
    body="Fixed in PR #44"
)
```

### Pull Request Management

#### `github_list_pull_requests`

List pull requests for a repository.

**Parameters:**
- `owner` (str): Repository owner
- `repo` (str): Repository name
- `state` (str, optional): PR state ("open", "closed", "all", default "open")
- `limit` (int, optional): Maximum PRs (1-100, default 30)

**Returns:**
```python
{
    "success": True,
    "data": [
        {
            "number": 10,
            "title": "Add new feature",
            "state": "open",
            "user": {"login": "contributor"},
            "head": {"ref": "feature-branch"},
            "base": {"ref": "main"},
            "html_url": "https://github.com/owner/repo/pull/10"
        }
    ]
}
```

**Example:**
```python
prs = github_list_pull_requests(owner="adenhq", repo="hive", state="open")
for pr in prs["data"]:
    print(f"PR #{pr['number']}: {pr['title']}")
```

#### `github_get_pull_request`

Get a specific pull request.

**Parameters:**
- `owner` (str): Repository owner
- `repo` (str): Repository name
- `pull_number` (int): Pull request number

**Returns:**
```python
{
    "success": True,
    "data": {
        "number": 10,
        "title": "PR title",
        "body": "Description...",
        "state": "open",
        "merged": False,
        "draft": False,
        "head": {"ref": "feature"},
        "base": {"ref": "main"}
    }
}
```

**Example:**
```python
pr = github_get_pull_request(owner="adenhq", repo="hive", pull_number=2814)
print(f"PR by {pr['data']['user']['login']}")
```

#### `github_create_pull_request`

Create a new pull request.

**Parameters:**
- `owner` (str): Repository owner
- `repo` (str): Repository name
- `title` (str): Pull request title
- `head` (str): Branch with your changes (e.g., "my-feature")
- `base` (str): Branch to merge into (e.g., "main")
- `body` (str, optional): Pull request description (supports Markdown)
- `draft` (bool, optional): Create as draft PR (default False)

**Returns:**
```python
{
    "success": True,
    "data": {
        "number": 11,
        "title": "New PR",
        "html_url": "https://github.com/owner/repo/pull/11"
    }
}
```

**Example:**
```python
result = github_create_pull_request(
    owner="myorg",
    repo="myrepo",
    title="feat: Add GitHub integration tool",
    head="feature/github-tool",
    base="main",
    body="## Summary\n\n- Implements GitHub API integration\n- Adds 30+ tests",
    draft=False
)
print(f"Created PR: {result['data']['html_url']}")
```

### Search

#### `github_search_code`

Search code across GitHub.

**Parameters:**
- `query` (str): Search query (supports GitHub code search syntax)
- `limit` (int, optional): Maximum results (1-100, default 30)

**Returns:**
```python
{
    "success": True,
    "data": {
        "total_count": 50,
        "items": [
            {
                "name": "example.py",
                "path": "src/example.py",
                "repository": {
                    "full_name": "owner/repo"
                },
                "html_url": "https://github.com/owner/repo/blob/main/src/example.py"
            }
        ]
    }
}
```

**Example:**
```python
# Search for function usage
result = github_search_code(
    query="register_tools language:python repo:adenhq/hive"
)

# Search for specific code pattern
result = github_search_code(query="FastMCP extension:py")
```

### Branch Management

#### `github_list_branches`

List branches for a repository.

**Parameters:**
- `owner` (str): Repository owner
- `repo` (str): Repository name
- `limit` (int, optional): Maximum branches (1-100, default 30)

**Returns:**
```python
{
    "success": True,
    "data": [
        {
            "name": "main",
            "protected": True,
            "commit": {"sha": "abc123..."}
        },
        {
            "name": "develop",
            "protected": False
        }
    ]
}
```

**Example:**
```python
branches = github_list_branches(owner="adenhq", repo="hive")
for branch in branches["data"]:
    print(f"Branch: {branch['name']}")
```

#### `github_get_branch`

Get information about a specific branch.

**Parameters:**
- `owner` (str): Repository owner
- `repo` (str): Repository name
- `branch` (str): Branch name

**Returns:**
```python
{
    "success": True,
    "data": {
        "name": "main",
        "protected": True,
        "commit": {
            "sha": "abc123...",
            "commit": {
                "message": "Latest commit message"
            }
        }
    }
}
```

**Example:**
```python
main_branch = github_get_branch(owner="adenhq", repo="hive", branch="main")
print(f"Latest commit: {main_branch['data']['commit']['sha']}")
```

## Error Handling

All functions return a dict with an `error` key if something goes wrong:

```python
{
    "error": "GitHub API error (HTTP 404): Not Found"
}
```

Common errors:
- `not configured` - No GitHub token provided
- `Invalid or expired GitHub token` - Token authentication failed (401)
- `Forbidden` - Insufficient permissions or rate limit exceeded (403)
- `Resource not found` - Repository, issue, or PR doesn't exist (404)
- `Validation error` - Invalid request parameters (422)
- `Request timed out` - Network timeout
- `Network error` - Connection issues

## Security

- Personal Access Tokens are never logged or exposed
- All API calls use HTTPS
- Tokens are retrieved from secure credential store or environment variables
- Fine-grained permissions can be configured via GitHub token scopes

## Use Cases

### Automated Issue Management
```python
# Create issues from bug reports
github_create_issue(
    owner="myorg",
    repo="myapp",
    title="Bug: Login fails on mobile",
    body="## Steps to reproduce\n1. Open app on mobile...",
    labels=["bug", "mobile"]
)
```

### CI/CD Integration
```python
# Create PR after automated changes
github_create_pull_request(
    owner="myorg",
    repo="myrepo",
    title="chore: Update dependencies",
    head="bot/update-deps",
    base="main",
    body="Automated dependency updates"
)
```

### Repository Analytics
```python
# Analyze repository activity
repo = github_get_repo(owner="adenhq", repo="hive")
issues = github_list_issues(owner="adenhq", repo="hive", state="open")
prs = github_list_pull_requests(owner="adenhq", repo="hive", state="open")

print(f"Stars: {repo['data']['stargazers_count']}")
print(f"Open Issues: {len(issues['data'])}")
print(f"Open PRs: {len(prs['data'])}")
```

### Code Discovery
```python
# Find examples of API usage
results = github_search_code(
    query="register_tools language:python",
    limit=50
)
for item in results["data"]["items"]:
    print(f"Found in: {item['repository']['full_name']}")
```

### Project Automation
```python
# Auto-close stale issues
issues = github_list_issues(owner="myorg", repo="myrepo", state="open")
for issue in issues["data"]:
    # Check if stale (custom logic)
    if is_stale(issue):
        github_update_issue(
            owner="myorg",
            repo="myrepo",
            issue_number=issue["number"],
            state="closed",
            body="Closing due to inactivity"
        )
```

## Rate Limits

GitHub enforces rate limits on API calls:
- **Authenticated requests**: 5,000 requests per hour
- **Search API**: 30 requests per minute
- **Unauthenticated requests**: 60 requests per hour (not applicable with token)

The tool handles rate limit errors gracefully with appropriate error messages. Monitor your usage at: https://api.github.com/rate_limit

## GitHub Search Syntax

For `github_search_repos` and `github_search_code`, you can use advanced search qualifiers:

### Repository Search
- `language:python` - Filter by language
- `stars:>1000` - Repositories with more than 1000 stars
- `forks:>100` - Repositories with more than 100 forks
- `org:adenhq` - Search within an organization
- `topic:machine-learning` - Filter by topic
- `created:>2024-01-01` - Created after date

### Code Search
- `repo:owner/repo` - Search in specific repository
- `extension:py` - Filter by file extension
- `path:src/` - Search in specific path
- `language:python` - Filter by language

Examples:
```python
# Find popular Python ML projects
github_search_repos(
    query="language:python topic:machine-learning stars:>5000",
    sort="stars"
)

# Find FastMCP usage examples
github_search_code(
    query="FastMCP extension:py"
)
```
