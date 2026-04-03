# Cloudinary Tool

Upload, manage, and search Cloudinary assets via the Cloudinary Admin API.

## Setup

```bash
export CLOUDINARY_CLOUD_NAME=your_cloud_name
export CLOUDINARY_API_KEY=your_api_key
export CLOUDINARY_API_SECRET=your_api_secret
```

Get credentials from your Cloudinary dashboard:
https://console.cloudinary.com/

Alternatively, configure credentials in the Aden credential store:
- `cloudinary_cloud_name`
- `cloudinary_key`
- `cloudinary_secret`

## Tools (8)

| Tool | Description |
|------|-------------|
| `cloudinary_upload` | Upload an asset from a URL |
| `cloudinary_list_resources` | List assets in your account |
| `cloudinary_get_resource` | Get details for a single asset |
| `cloudinary_delete_resource` | Delete an asset |
| `cloudinary_search` | Search assets with a query expression |
| `cloudinary_get_usage` | Get account usage and limits |
| `cloudinary_rename_resource` | Rename an asset |
| `cloudinary_add_tag` | Add tags to one or more assets |

## Usage

### Upload from URL

```python
result = cloudinary_upload(
    file_url="https://example.com/image.jpg",
    folder="marketing",
    tags="launch,hero",
)
```

### Search assets

```python
result = cloudinary_search(
    expression="resource_type:image AND tags=hero",
    max_results=25,
)
```

### Get usage

```python
result = cloudinary_get_usage()
```

## Scope

- Upload and manage assets (list, get, delete, rename)
- Search and tagging
- Usage and quota visibility

## API Reference

- Cloudinary Admin API: https://cloudinary.com/documentation/admin_api
