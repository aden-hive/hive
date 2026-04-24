# Cloudinary Tool

Upload, manage, search, and transform media assets using the Cloudinary API.

## Tools

| Tool | Description |
|------|-------------|
| `cloudinary_upload` | Upload an image or file to Cloudinary |
| `cloudinary_list_resources` | List resources with optional type and prefix filters |
| `cloudinary_get_resource` | Get detailed info about a specific resource |
| `cloudinary_delete_resource` | Delete a resource by public ID |
| `cloudinary_search` | Search resources using Cloudinary's search API |
| `cloudinary_get_usage` | Get account usage statistics |
| `cloudinary_rename_resource` | Rename a resource's public ID |
| `cloudinary_add_tag` | Add a tag to one or more resources |

## Setup

Set the following environment variables:

| Variable | Description |
|----------|-------------|
| `CLOUDINARY_CLOUD_NAME` | Your Cloudinary cloud name |
| `CLOUDINARY_API_KEY` | API key |
| `CLOUDINARY_API_SECRET` | API secret |

Get credentials at: [Cloudinary Console](https://console.cloudinary.com/)

## Usage Examples

### Upload an image
```python
cloudinary_upload(file_url="https://example.com/photo.jpg", public_id="my-photo")
```

### Search for resources
```python
cloudinary_search(expression="cat AND format:jpg", max_results=10)
```

### Get account usage
```python
cloudinary_get_usage()
```

### Delete a resource
```python
cloudinary_delete_resource(public_id="my-photo")
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET not set", "help": "Get credentials from your Cloudinary dashboard at https://console.cloudinary.com/"}
{"error": "Cloudinary API error (HTTP 404): Resource not found"}
{"error": "Request timed out"}
```
