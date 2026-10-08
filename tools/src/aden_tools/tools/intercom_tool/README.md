# Intercom Tool

Customer messaging, conversations, and support automation via the Intercom API (v2.11).

## Setup

### 1. Get an Access Token

1. Log in to your [Intercom Developer Hub](https://app.intercom.com/a/apps/_/developer-hub)
2. Create or select an app
3. Go to **Authentication** and copy the access token
4. Ensure the app has the required scopes for the tools you need (e.g., `Read and List conversations`, `Manage conversations`, `Read and Write contacts`)

### 2. Configure the Token

Set the environment variable:

```bash
export INTERCOM_ACCESS_TOKEN="your-access-token-here"
```

Or configure via the Hive credential store.

## Tools (8 Total)

### Conversations (2)

| Tool | Description |
|------|-------------|
| `intercom_search_conversations` | Search conversations with filters (status, assignee, tag, date) |
| `intercom_get_conversation` | Get full conversation details including message history |

### Contacts (2)

| Tool | Description |
|------|-------------|
| `intercom_get_contact` | Get a contact by ID or email |
| `intercom_search_contacts` | Search contacts by email, name, or custom attributes |

### Notes, Tags & Assignment (3)

| Tool | Description |
|------|-------------|
| `intercom_add_note` | Add an internal note to a conversation |
| `intercom_add_tag` | Add a tag to a conversation or contact |
| `intercom_assign_conversation` | Assign a conversation to an admin or team |

### Teams (1)

| Tool | Description |
|------|-------------|
| `intercom_list_teams` | List available teams for conversation routing |

## Usage Examples

```python
# Search open conversations
intercom_search_conversations(status="open", limit=10)

# Get full conversation details
intercom_get_conversation(conversation_id="12345")

# Find a contact by email
intercom_get_contact(email="jane@example.com")

# Add an internal note
intercom_add_note(conversation_id="12345", body="Escalating to engineering")

# Tag a conversation
intercom_add_tag(name="VIP", conversation_id="12345")

# Assign to a team
intercom_assign_conversation(
    conversation_id="12345",
    assignee_id="67890",
    assignee_type="team",
    body="Routing to billing team"
)

# List available teams
intercom_list_teams()
```

## Error Handling

All tools return error dictionaries on failure:

```python
{"error": "Intercom credentials not configured", "help": "Set INTERCOM_ACCESS_TOKEN..."}
{"error": "Invalid or expired Intercom access token"}
{"error": "Insufficient permissions. Check your Intercom app scopes."}
{"error": "Resource not found"}
{"error": "Intercom rate limit exceeded. Try again later."}
{"error": "Request timed out"}
```

## References

- [Intercom API Documentation](https://developers.intercom.com/docs/references/rest-api/api.intercom.io/)
