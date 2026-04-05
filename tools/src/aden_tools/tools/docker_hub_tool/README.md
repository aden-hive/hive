# Docker Hub Tool

Search repositories, list tags, inspect images, manage webhooks, and delete tags via the Docker Hub API v2.

## Tools

| Tool | Description |
|------|-------------|
| `docker_hub_search` | Search Docker Hub for public repositories |
| `docker_hub_list_repos` | List repositories for a user or organization |
| `docker_hub_get_repo` | Get detailed info about a specific repository |
| `docker_hub_list_tags` | List tags for a repository |
| `docker_hub_get_tag_detail` | Get details for a specific image tag |
| `docker_hub_delete_tag` | Delete a tag from a repository |
| `docker_hub_list_webhooks` | List webhooks configured for a repository |

## Setup

Requires a Docker Hub Personal Access Token (PAT):

1. Go to [hub.docker.com](https://hub.docker.com) → **Account Settings → Security → New Access Token**
2. Give it a name and select the required permissions (Read, Write, Delete as needed)
3. Copy the token immediately — it is only shown once

```bash
DOCKER_HUB_TOKEN=your-personal-access-token
DOCKER_HUB_USERNAME=your-docker-hub-username
```

> `DOCKER_HUB_USERNAME` is used as the default namespace when listing repos. If it is unset and no `namespace` is passed to `docker_hub_list_repos`, the tool will return an error: `"namespace is required (or set DOCKER_HUB_USERNAME)"`.

## Usage Examples

### Search for public repositories

```python
docker_hub_search(query="nginx", max_results=10)
```

### List your own repositories

```python
docker_hub_list_repos(namespace="myusername", max_results=25)
```

### Get repository details

```python
docker_hub_get_repo(repository="library/nginx")
```

### List tags for a repository

```python
docker_hub_list_tags(repository="library/nginx", max_results=20)
```

### Get details for a specific tag

```python
docker_hub_get_tag_detail(
    repository="library/nginx",
    tag="latest",
)
```

### Delete a tag

```python
docker_hub_delete_tag(
    repository="myusername/myapp",
    tag="old-release-1.0",
)
```

### List webhooks for a repository

```python
docker_hub_list_webhooks(repository="myusername/myapp")
```

## Response Format

`docker_hub_list_tags` returns tags sorted by `last_updated` descending:

```python
{
    "repository": "library/nginx",
    "tags": [
        {
            "name": "latest",
            "full_size": 68000000,
            "last_updated": "2025-05-01T12:00:00Z",
            "digest": "sha256:abc123...",
        },
        ...
    ]
}
```

`docker_hub_get_tag_detail` includes per-architecture image info:

```python
{
    "repository": "library/nginx",
    "tag": "latest",
    "full_size": 68000000,
    "images": [
        {"architecture": "amd64", "os": "linux", "size": 34000000, "digest": "sha256:..."},
        {"architecture": "arm64", "os": "linux", "size": 32000000, "digest": "sha256:..."},
    ]
}
```

## Error Handling

All tools return error dicts on failure:

```python
{"error": "DOCKER_HUB_TOKEN not set", "help": "Create a PAT at https://hub.docker.com/settings/security"}
{"error": "Unauthorized. Check your DOCKER_HUB_TOKEN."}
{"error": "Not found"}
{"error": "Request to Docker Hub timed out"}
```
