# Google Docs Tool

Create and manage Google Docs documents via the Google Docs API v1.

## Features

- Create new documents
- Read document content and structure
- Insert text at specific positions
- Find and replace text (template population)
- Insert images
- Format text (bold, italic, colors, etc.)
- Create bulleted and numbered lists
- Add comments
- Export to PDF, DOCX, TXT, and more

## Setup

### Option 1: OAuth2 Access Token (Recommended for Development)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable the **Google Docs API** and **Google Drive API**
4. Create OAuth 2.0 credentials
5. Use the OAuth2 Playground or your app to get an access token
6. Set the environment variable:

```bash
export GOOGLE_DOCS_ACCESS_TOKEN="your-access-token"
```

### Option 2: Service Account (Recommended for Production)

1. Create a service account in Google Cloud Console
2. Download the JSON key file
3. Share your documents with the service account email
4. Set the environment variable:

```bash
export GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
```

### Required OAuth Scopes

- `https://www.googleapis.com/auth/documents` - Full access to Google Docs
- `https://www.googleapis.com/auth/drive.file` - Access to files created/opened by the app
- `https://www.googleapis.com/auth/drive` - Required for document export and comment functionality

## Available Tools

| Tool | Description |
|------|-------------|
| `google_docs_create_document` | Create a new blank document with a specified title |
| `google_docs_get_document` | Retrieve the full structural content of a document |
| `google_docs_insert_text` | Insert text at a specific index or at the end |
| `google_docs_replace_all_text` | Global find-and-replace for template population |
| `google_docs_insert_image` | Insert images via public URI |
| `google_docs_format_text` | Apply styling (bold, italic, colors, font size) |
| `google_docs_batch_update` | Execute multiple requests atomically |
| `google_docs_create_list` | Create bulleted or numbered lists |
| `google_docs_add_comment` | Add comments to documents |
| `google_docs_export_content` | Export to PDF, DOCX, TXT, HTML, etc. |

## Usage Examples

### Create a Document

```python
result = google_docs_create_document(title="My New Document")
# Returns: {"document_id": "1abc...", "title": "My New Document", "document_url": "https://docs.google.com/..."}
```

### Populate a Template

```python
# Use placeholders in your template like {{Customer_Name}}, {{Date}}, etc.
result = google_docs_replace_all_text(
    document_id="1abc...",
    find_text="{{Customer_Name}}",
    replace_text="John Doe"
)
# Returns: {"occurrences_replaced": 3}
```

### Insert Text

```python
# Insert at the end
result = google_docs_insert_text(
    document_id="1abc...",
    text="Hello, World!\n"
)

# Insert at specific position (1-based index)
result = google_docs_insert_text(
    document_id="1abc...",
    text="Inserted text",
    index=10
)
```

### Format Text

```python
result = google_docs_format_text(
    document_id="1abc...",
    start_index=1,
    end_index=12,
    bold=True,
    font_size_pt=18.0,
    foreground_color_red=0.0,
    foreground_color_green=0.0,
    foreground_color_blue=1.0  # Blue text
)
```

### Export to PDF

```python
result = google_docs_export_content(
    document_id="1abc...",
    format="pdf"
)
# Returns: {"content_base64": "...", "size_bytes": 12345, "mime_type": "application/pdf"}
```

## Technical Notes

### Document Indexing

The Google Docs API uses **1-based indexing** for document positions:
- Index 1 is the start of the document body
- For complex updates, it's recommended to **write backwards** (start from the end) to avoid index shifting

### Comments API

Adding and listing comments uses the Google Drive API (`drive.googleapis.com/v3/files/{fileId}/comments`), not the Docs API directly.

### Image Insertion

The `insertInlineImage` request requires a **publicly accessible URL**. Google's servers must be able to fetch the image from this URL.

## Error Handling

All tools return a dict. On error, the dict contains an `"error"` key with a description:

```python
{"error": "Document not found"}
{"error": "Invalid or expired Google access token"}
{"error": "Insufficient permissions. Check your Google API scopes."}
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_DOCS_ACCESS_TOKEN` | Yes* | OAuth2 access token |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Yes* | Service account JSON (alternative to access token) |

*One of these is required.
