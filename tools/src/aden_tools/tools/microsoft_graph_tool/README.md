# Microsoft Graph Tool

Access Outlook mail, Microsoft Teams, and OneDrive files via the Microsoft Graph API v1.0.

## Tools

### Outlook Mail

| Tool | Description |
|------|-------------|
| `outlook_list_messages` | List emails with optional folder and search filters |
| `outlook_get_message` | Get details of a specific email |
| `outlook_send_mail` | Send an email |

### Microsoft Teams

| Tool | Description |
|------|-------------|
| `teams_list_teams` | List teams the user belongs to |
| `teams_list_channels` | List channels in a team |
| `teams_send_channel_message` | Send a message to a team channel |
| `teams_get_channel_messages` | Get recent messages from a channel |

### OneDrive

| Tool | Description |
|------|-------------|
| `onedrive_search_files` | Search for files across OneDrive |
| `onedrive_list_files` | List files in a folder |
| `onedrive_download_file` | Download a file's content |
| `onedrive_upload_file` | Upload a small file to OneDrive (up to 4MB) |

## Setup

Set the following environment variable or use Aden OAuth:

| Variable | Description |
|----------|-------------|
| `MICROSOFT_GRAPH_ACCESS_TOKEN` | Microsoft Graph API access token |

Get credentials at: [Azure App Registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps)

Required permissions: `Mail.Read`, `Mail.Send`, `Team.ReadBasic.All`, `Channel.ReadBasic.All`, `ChannelMessage.Send`, `ChannelMessage.Read.All`, `Files.ReadWrite`

## Usage Examples

### List unread emails
```python
outlook_list_messages(folder="inbox", search="is:unread", top=10)
```

### Send an email
```python
outlook_send_mail(
    to=["jane@example.com"],
    subject="Meeting Notes",
    body="Here are the notes from today's meeting.",
)
```

### List Teams channels
```python
teams_list_channels(team_id="team-abc-123")
```

### Search OneDrive files
```python
onedrive_search_files(query="quarterly report", top=5)
```

### Upload a file to OneDrive
```python
onedrive_upload_file(file_path="Documents/notes.txt", content="Meeting notes here")
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "MICROSOFT_GRAPH_ACCESS_TOKEN not set", "help": "Set MICROSOFT_GRAPH_ACCESS_TOKEN or connect via hive.adenhq.com"}
{"error": "Microsoft Graph API error (HTTP 403): Insufficient privileges"}
{"error": "Request timed out"}
```
