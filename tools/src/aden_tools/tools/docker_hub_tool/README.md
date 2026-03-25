# Docker Hub Tool

Search repositories, list tags, and inspect container images via the Docker Hub API v2.

## Supported Actions

- **docker_hub_search** – Search for public repositories
- **docker_hub_list_repos** – List repositories for an authenticated user/org
- **docker_hub_list_tags** – List available tags for a repository
- **docker_hub_get_repo** – Get detailed repository metadata
- **docker_hub_get_tag_detail** – Inspect a specific tag (architecture, size, digest)
- **docker_hub_delete_tag** – Delete a tag from a repository
- **docker_hub_list_webhooks** – List configured webhooks for a repository

## Setup

1. Create a Personal Access Token at [Docker Hub](https://hub.docker.com/settings/security).

2. Set the required environment variables:
   ```bash
   export DOCKER_HUB_USERNAME=your-username
   export DOCKER_HUB_TOKEN=dckr_pat_xxxxxxxxxxxx
   ```

## Use Case

Example: "List all tags for the `myorg/api-server` image, find any that are older than 90 days, and delete them to free up storage."
