# Hive Integrations Guide

Complete guide to integrating external services with Hive agents and the web dashboard.

## Overview

The Hive integration system allows agents to connect with external business tools and services such as Slack, Salesforce, HubSpot, email, and custom APIs. This enables complex, multi-step workflows without manual intervention.

## Architecture

### Components

1. **Integration Registry** - Central registry of available integrations
2. **Credential Management** - Secure storage and retrieval of API keys
3. **Integration Controller** - Handles configuration and testing
4. **Integration Service** - Business logic for each integration

## Supported Integrations

### 🟢 Production Ready

- **Slack** - Send messages and notifications
- **Email** - SMTP and email service integration
- **Custom API** - Connect to any REST API

### 🟡 Coming Soon

- **Salesforce** - CRM data sync and automation
- **HubSpot** - Lead and contact management
- **Stripe** - Payment processing
- **GitHub** - Repository and issue management
- **Notion** - Database and content management

## Setup & Configuration

### 1. List Available Integrations

**Endpoint:** `GET /api/integrations`

**Response:**

```json
{
  "integrations": [
    {
      "name": "slack",
      "displayName": "Slack",
      "description": "Send messages and notifications to Slack channels",
      "icon": "💬",
      "category": "communication",
      "credentials": ["webhook_url", "bot_token"],
      "status": "available",
      "configured": false
    }
  ],
  "count": 8
}
```

### 2. Configure an Integration

**Endpoint:** `POST /api/integrations/:name/configure`

**Request Body:**

```json
{
  "credentials": {
    "api_key": "your-api-key-here",
    "webhook_url": "https://hooks.slack.com/..."
  },
  "settings": {
    "defaultChannel": "#general"
  }
}
```

**Response:**

```json
{
  "status": "success",
  "message": "Integration slack configured successfully",
  "timestamp": "2026-02-12T10:30:00Z"
}
```

### 3. Test Integration Connection

**Endpoint:** `POST /api/integrations/:name/test`

**Response:**

```json
{
  "name": "slack",
  "status": "connected",
  "message": "Successfully connected to Slack",
  "timestamp": "2026-02-12T10:31:00Z"
}
```

## Integration Examples

### Slack Integration

**Setup Steps:**

1. Go to Slack API Dashboard: https://api.slack.com/apps
2. Create a new app
3. Get your Webhook URL or Bot Token
4. Configure in Hive Dashboard:

```json
{
  "credentials": {
    "webhook_url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
  }
}
```

**Usage in Agent:**

```python
# In your Hive agent
send_slack_message(
  channel="#general",
  message="Agent completed task successfully!"
)
```

### Email Integration

**Setup Steps:**

1. Get SMTP credentials (Gmail, SendGrid, etc.)
2. Configure in Hive Dashboard:

```json
{
  "credentials": {
    "smtp_host": "smtp.gmail.com",
    "smtp_port": "587",
    "email": "your-email@gmail.com",
    "password": "your-app-password"
  }
}
```

**Usage in Agent:**

```python
send_email(
  to="recipient@example.com",
  subject="Agent Notification",
  body="Your task has been completed"
)
```

### Custom API Integration

**Setup Steps:**

1. Get your API's base URL and authentication details
2. Configure in Hive Dashboard:

```json
{
  "credentials": {
    "base_url": "https://api.example.com",
    "api_key": "your-api-key",
    "headers": {
      "X-Custom-Header": "value"
    }
  }
}
```

**Usage in Agent:**

```python
response = call_custom_api(
  endpoint="/users/search",
  method="GET",
  params={"query": "john"}
)
```

## Building Custom Integrations

### Structure

Each integration needs:

1. **Functions** - API interaction logic
2. **Credentials** - Authentication configuration
3. **Documentation** - Setup and usage guide
4. **Tests** - Unit and integration tests

### Template

```python
# integrations/my_service.py

class MyServiceIntegration:
    """Integration with MyService API"""

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url

    def authenticate(self) -> bool:
        """Verify credentials work"""
        try:
            response = self._make_request("/status")
            return response.status_code == 200
        except Exception as e:
            print(f"Authentication failed: {e}")
            return False

    def _make_request(self, endpoint: str, method: str = "GET", **kwargs):
        """Make authenticated API request"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        url = f"{self.base_url}{endpoint}"
        return requests.request(method, url, headers=headers, **kwargs)

    # Add specific methods for API endpoints
    def get_resource(self, resource_id: str):
        """Get a resource by ID"""
        return self._make_request(f"/resources/{resource_id}")

    def create_resource(self, data: dict):
        """Create a new resource"""
        return self._make_request("/resources", method="POST", json=data)
```

### Credential Specification

```python
# credentials/my_service_spec.py

from hive.credentials import CredentialSpec

MYSERVICE_CREDENTIAL_SPEC = CredentialSpec(
    name="myservice",
    fields=[
        {
            "name": "api_key",
            "type": "secret",
            "required": True,
            "description": "Your MyService API key"
        },
        {
            "name": "base_url",
            "type": "string",
            "required": True,
            "description": "MyService API base URL",
            "default": "https://api.myservice.com"
        }
    ]
)
```

### Testing

```python
# tests/test_my_service_integration.py

import pytest
from integrations.my_service import MyServiceIntegration

class TestMyServiceIntegration:

    @pytest.fixture
    def integration(self):
        return MyServiceIntegration(
            api_key="test-key",
            base_url="https://api.test.com"
        )

    def test_authenticate(self, integration):
        assert integration.authenticate() is True

    def test_get_resource(self, integration):
        result = integration.get_resource("123")
        assert result.status_code == 200

    def test_create_resource(self, integration):
        data = {"name": "test"}
        result = integration.create_resource(data)
        assert result.status_code == 201
```

## Contributing New Integrations

### Step 1: Create Issue

Use this format for integration proposals:

**Title:** `[Integration]: <Service Name>`

**Description:**

```markdown
## Reason

Why this integration is needed (e.g., "Users need to sync CRM data")

## Use Case

Specific business process it enables (e.g., "Automatically create leads from form submissions")

## Scope

What endpoints/features are included:

- Create/Read/Update entities
- Custom webhooks support
- Batch operations

## Links

- Service API docs: [link]
- Reference issue: #2805
```

### Step 2: Implement Integration

1. Create integration class with core functions
2. Define credential specification
3. Add unit and integration tests
4. Write documentation with examples
5. Submit PR referencing your issue

### Step 3: Review & Merge

Maintainers will:

- Review code for security and quality
- Test against Hive agents
- Ensure documentation is clear
- Merge and release in next version

## Security Best Practices

### 1. Credential Storage

- Never commit credentials to version control
- Use environment variables or secure vaults
- Always use HTTPS for API communications

### 2. API Key Management

```python
# ✓ Good
api_key = os.getenv("MYSERVICE_API_KEY")

# ✗ Bad
api_key = "sk_live_abcd1234..."  # Don't hardcode!
```

### 3. Request Validation

```python
# Validate before making requests
if not self.api_key or not self.base_url:
    raise ValueError("Missing required credentials")
```

### 4. Error Handling

```python
try:
    response = self._make_request("/endpoint")
except requests.exceptions.Timeout:
    log_error("Request timeout")
except requests.exceptions.ConnectionError:
    log_error("Connection failed")
```

## Troubleshooting

### Integration Won't Connect

1. **Check credentials:**

   ```bash
   curl -H "Authorization: Bearer YOUR_KEY" https://api.service.com/status
   ```

2. **Verify API endpoint:**
   - Is it the correct URL?
   - Does it require special headers?
   - Is authentication working?

3. **Review logs:**
   ```bash
   # Check backend logs for detailed errors
   npm run dev  # in backend directory
   ```

### Agent Can't Access Integration

1. Ensure integration is configured
2. Verify credentials are saved
3. Test connection in dashboard
4. Check agent has permission to use integration

### Slow Integration Calls

- Add caching for frequently accessed data
- Use pagination for large datasets
- Consider async operations for long-running tasks

## API Reference

### Integration Controller Endpoints

| Method | Endpoint                            | Description            |
| ------ | ----------------------------------- | ---------------------- |
| GET    | `/api/integrations`                 | List all integrations  |
| GET    | `/api/integrations/:name`           | Get integration config |
| POST   | `/api/integrations/:name/configure` | Save credentials       |
| POST   | `/api/integrations/:name/test`      | Test connection        |
| DELETE | `/api/integrations/:name`           | Remove integration     |

## Examples Repository

Check the `examples/integrations/` directory for complete working examples:

- `slack_notification_agent.py` - Send Slack notifications
- `email_digest_agent.py` - Generate email reports
- `crm_sync_agent.py` - Sync CRM data
- `custom_api_agent.py` - Call custom APIs

## Resources

- **Hive Documentation:** https://docs.adenhq.com
- **Integration Issue Tracker:** https://github.com/adenhq/hive/issues?q=label:%22integration%22
- **API Testing Tool:** https://www.postman.com/
- **Security Guide:** See `docs/SECURITY.md`

## Support

- **Issues:** https://github.com/adenhq/hive/issues
- **Discussions:** https://github.com/adenhq/hive/discussions
- **Discord:** https://discord.gg/...

---

**Happy integrating! 🚀**
