# Greenhouse Tool

Manage jobs, candidates, applications, and offers using the Greenhouse Harvest API.

## Tools

| Tool | Description |
|------|-------------|
| `greenhouse_list_jobs` | List jobs with optional status and department filters |
| `greenhouse_get_job` | Get details of a specific job |
| `greenhouse_list_candidates` | List candidates with optional search and date filters |
| `greenhouse_get_candidate` | Get details of a specific candidate |
| `greenhouse_list_applications` | List applications with optional job and status filters |
| `greenhouse_get_application` | Get details of a specific application |
| `greenhouse_list_offers` | List offers with optional status filter |
| `greenhouse_add_candidate_note` | Add a note to a candidate's profile |
| `greenhouse_list_scorecards` | List scorecards for an application |

## Setup

Set the following environment variable:

| Variable | Description |
|----------|-------------|
| `GREENHOUSE_API_TOKEN` | Greenhouse Harvest API token |

Get a token at: Configure > Dev Center > API Credential Management in your Greenhouse account.

The token uses HTTP Basic Auth (token as username, empty password).

## Usage Examples

### List open jobs
```python
greenhouse_list_jobs(status="open", per_page=20)
```

### Search candidates
```python
greenhouse_list_candidates(search="jane@example.com", per_page=10)
```

### Get application details
```python
greenhouse_get_application(application_id=12345)
```

### Add a note to a candidate
```python
greenhouse_add_candidate_note(candidate_id=12345, body="Strong technical interview performance.")
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "GREENHOUSE_API_TOKEN not set", "help": "Get your API key from Greenhouse: Configure > Dev Center > API Credential Management"}
{"error": "Greenhouse API error (HTTP 404): Resource not found"}
{"error": "Request timed out"}
```
