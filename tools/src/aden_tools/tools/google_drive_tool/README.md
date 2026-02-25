# Google Drive Tool

This tool provides comprehensive integration with Google Drive API v3, enabling agents to manage files, folders, permissions, and sharing in Google Drive.

## Use Cases

- **File Management**: Upload, download, delete, and move files between folders
- **Folder Organization**: Create new folders and organize file hierarchies
- **File Discovery**: Search for files by name, type, modification date, or owner
- **Collaboration**: Share files via links and manage granular permissions
- **Storage Cleanup**: Empty trash and manage file lifecycle

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GOOGLE_DRIVE_ACCESS_TOKEN` | OAuth2 access token for Google Drive API | Yes |


## Tool Functions

### File Operations

#### `google_drive_upload_file(filepath: str) -> dict`
Upload a local file to Google Drive.

**Arguments:**
- `filepath`: Absolute or relative path to the file to upload

**Returns:**
- Success: `{"id": "file_id", "name": "filename", ...}`
- Error: `{"error": "error message"}`

**Example:**
```python
result = google_drive_upload_file("/path/to/document.pdf")
# Returns: {"id": "1abc...", "name": "document.pdf", "mimeType": "application/pdf"}
```

#### `google_drive_download_file(filename: str) -> dict`
Download a file from Google Drive to the current directory.

**Arguments:**
- `filename`: Name of the file in Google Drive (exact match required)

**Returns:**
- Success: `{"filename": "local_filename", "content_base64": "...", "size_bytes": 1234}`
- Error: `{"error": "File not found with name: filename"}`

**Example:**
```python
result = google_drive_download_file("report.pdf")
# Downloads file and returns metadata with base64 content
```

#### `google_drive_delete_file(filename: str) -> dict`
Move a file to trash in Google Drive.

**Arguments:**
- `filename`: Name of the file to delete

**Returns:**
- Success: `{"id": "file_id", "name": "filename", "trashed": true}`
- Error: `{"error": "File not found with name: filename"}`

### Folder Operations

#### `google_drive_create_folder(filename: str) -> dict`
Create a new folder in Google Drive root.

**Arguments:**
- `filename`: Name for the new folder

**Returns:**
- Success: `{"id": "folder_id", "name": "folder_name", "mimeType": "application/vnd.google-apps.folder"}`

#### `google_drive_move_file(filename: str, folder: str) -> dict`
Move a file to a specified folder.

**Arguments:**
- `filename`: Name of the file to move
- `folder`: Name of the destination folder

**Returns:**
- Success: `{"id": "file_id", "name": "filename", "parents": ["folder_id"]}`

### Search and Listing

#### `google_drive_search_file(filename: str, filetype: str, modified: str, people: str) -> dict`
Search for files based on multiple criteria.

**Arguments:**
- `filename`: Exact filename (optional)
- `filetype`: MIME type or partial type like "image" or "application/pdf" (optional)
- `modified`: ISO 8601 date string for files modified after (e.g., "2024-01-01T00:00:00Z") (optional)
- `people`: Email address of file owner (optional)

**Returns:**
- Success: `{"files": [{"id": "...", "name": "...", "mimeType": "..."}]}`

**Example:**
```python
# Find all PDFs modified after a date
result = google_drive_search_file("", "application/pdf", "2024-01-01T00:00:00Z", "")
```

#### `google_drive_list_files(specifyfolder: str) -> dict`
List files in Google Drive root or specific folder.

**Arguments:**
- `specifyfolder`: Folder name to list files from (optional, lists root if empty)

**Returns:**
- Success: `{"files": [{"id": "...", "name": "...", "mimeType": "...", "parents": [...]}]}`

### Permissions and Sharing

#### `google_drive_share_file_link(filename: str) -> dict`
Generate a shareable link for a file (anyone with link can view).

**Arguments:**
- `filename`: Name of the file to share

**Returns:**
- Success: `{"id": "file_id", "name": "filename", "webViewLink": "https://drive.google.com/..."}`

#### `google_drive_update_permissions(filename: str, p_type: str, respondent: str, role: str) -> dict`
Update permissions for a specific user or group.

**Arguments:**
- `filename`: Name of the file
- `p_type`: Permission type ("user", "group", "domain", "anyone")
- `respondent`: Email address (for user/group) or domain name
- `role`: Permission level ("reader", "writer", "commenter")

**Returns:**
- Success: Permission creation/update confirmation

### Maintenance

#### `google_drive_empty_trash() -> dict`
Permanently delete all files in trash.

**Returns:**
- Success: `{"status": "success", "message": "Trash emptied"}`

## Error Handling

The tool returns structured error responses for common issues:

- **Authentication**: `{"error": "Invalid or expired Google Drive access token"}`
- **Permissions**: `{"error": "Insufficient permissions or not authorized"}`
- **File Not Found**: `{"error": "File not found with name: filename"}`
- **Network Issues**: `{"error": "Request timed out"}` or `{"error": "Network error: details"}`
- **API Errors**: `{"error": "Google Drive API error (HTTP 403): details"}`

## Examples

### Complete Workflow
```python
# Create a folder
folder_result = google_drive_create_folder("Project Reports")

# Upload a file
upload_result = google_drive_upload_file("./report.pdf")

# Share the file
share_result = google_drive_share_file_link("report.pdf")
print(f"Share link: {share_result['webViewLink']}")

# Search for files
search_result = google_drive_search_file("", "application/pdf", "", "")
print(f"Found {len(search_result['files'])} PDF files")
```

### Batch Operations
```python
# List all files in a folder
files = google_drive_list_files("Documents")