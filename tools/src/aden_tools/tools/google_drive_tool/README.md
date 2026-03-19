# Google Drive Tool

List, search, upload, download, share, and organize files in Google Drive using the [Drive API v3](https://developers.google.com/drive/api/guides/about-sdk).

## Setup

### OAuth 2.0 (recommended)

1. Open [Google Cloud Console](https://console.cloud.google.com/) and select or create a project.
2. Enable **Google Drive API**: APIs & Services → Library → “Google Drive API” → Enable.
3. Configure the OAuth consent screen and create an **OAuth client ID**.
4. Run an OAuth flow with scopes that include Drive access, for example:
   - `https://www.googleapis.com/auth/drive` (full Drive), or
   - `https://www.googleapis.com/auth/drive.file` (files created or opened by the app only).
5. Set the access token for local development:

```bash
export GOOGLE_DRIVE_ACCESS_TOKEN="your-access-token"
```

Or store credentials via the Aden credential store under the **`google_drive`** key (see [google_drive.py](../../credentials/google_drive.py) for `aden_provider_name` and health check).

### Shared drives

Calls use `supportsAllDrives=true` and `includeItemsFromAllDrives=true` where the API allows, so team drives can be used when the token has the right scopes.

## Limits

- **`drive_upload_file`** uses the simple multipart upload (suitable for roughly **5 MiB** or smaller). Larger files need a resumable session (not implemented here).

## Available Tools

| Tool | Description |
|------|-------------|
| `drive_list_files` | List items in a folder (`folder_id` empty → My Drive root) |
| `drive_search_files` | Search by full text / name (`fullText contains`) |
| `drive_get_file_metadata` | Metadata (parents, links, owners, etc.) |
| `drive_get_file` | Read content; Workspace files exported with sensible defaults |
| `drive_download_file` | Binary download (`alt=media`); Workspace files need `export_mime_type` |
| `drive_upload_file` | Create a file from UTF-8 text (small uploads) |
| `drive_create_folder` | Create a folder (optional parent) |
| `drive_delete_file` | Delete a file by id |
| `drive_share_file` | Add a permission (`user`, `group`, `domain`, `anyone`) |
| `drive_copy_file` | Copy a file (optional name and parent) |
| `drive_move_file` | Move between folders (`new_parent_id`, `previous_parent_id`) |

## Examples

**List the root of My Drive**

```text
drive_list_files(folder_id="", page_size=20)
```

**Search**

```text
drive_search_files(query="quarterly report", page_size=10)
```

**Download a PDF (regular file)**

```text
drive_download_file(file_id="...")
```

**Export a Google Doc**

```text
drive_get_file(file_id="...")
# or
drive_download_file(file_id="...", export_mime_type="application/pdf")
```

**Upload a note into a folder**

```text
drive_upload_file(name="notes.txt", content="Hello", folder_id="folder-id-here")
```

## References

- [Drive API REST](https://developers.google.com/drive/api/reference/rest/v3)
- [Search query terms](https://developers.google.com/drive/api/guides/search-files)
