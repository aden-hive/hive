# Trello Tools

Trello tools let agents create, update, and manage Trello cards and lists via the Trello REST API.

## Required Credentials

- `TRELLO_API_KEY`
- `TRELLO_API_TOKEN`

### How to get a Trello API key

1. Go to `https://trello.com/power-ups/admin`
2. Create or open a Power-Up
3. Copy the API key shown in the Power-Up admin page

### How to get a Trello API token

1. Ensure you have a Trello API key
2. Go to the recently created Power-Up
3. Click on API key section
4. Click on Token button
5. Authorize and copy the token returned by Trello

## Tools

### `trello_list_boards`

List boards for a member.

Parameters:
- `member_id` (string, default `"me"`)
- `fields` (list[string], optional) Trello board fields or `["all"]`
- `limit` (int, optional, 1-1000)

Example:
```json
{"member_id":"me","fields":["id","name","url"],"limit":10}
```

### `trello_get_member`

Get info for a Trello member.

Parameters:
- `member_id` (string, default `"me"`)
- `fields` (list[string], optional) Trello member fields or `["all"]`

Example:
```json
{"member_id":"me","fields":["id","fullName","username","url"]}
```

### `trello_list_lists`

List lists in a board.

Parameters:
- `board_id` (string, required)
- `fields` (list[string], optional) Trello list fields or `["all"]`

Example:
```json
{"board_id":"<board_id>"}
```

### `trello_list_cards`

List cards in a list.

Parameters:
- `list_id` (string, required)
- `fields` (list[string], optional) Trello card fields or `["all"]`
- `limit` (int, optional, 1-1000)

Example:
```json
{"list_id":"<list_id>","limit":20}
```

### `trello_create_card`

Create a card in a list.

Parameters:
- `list_id` (string, required)
- `name` (string, required)
- `desc` (string, optional, max 16384 chars)
- `due` (string, optional, ISO-8601)
- `id_members` (list[string], optional)
- `id_labels` (list[string], optional)
- `pos` (string, optional)

Example:
```json
{"list_id":"<list_id>","name":"Investigate webhook failures","desc":"See runbook","pos":"top"}
```

### `trello_move_card`

Move a card to another list.

Parameters:
- `card_id` (string, required)
- `list_id` (string, required)
- `pos` (string, optional)

Example:
```json
{"card_id":"<card_id>","list_id":"<list_id>","pos":"bottom"}
```

### `trello_update_card`

Update card fields.

Parameters:
- `card_id` (string, required)
- `name` (string, optional)
- `desc` (string, optional, max 16384 chars)
- `due` (string, optional)
- `closed` (bool, optional)
- `list_id` (string, optional)
- `pos` (string, optional)

Example:
```json
{"card_id":"<card_id>","name":"Updated title","closed":false}
```

### `trello_add_comment`

Add a comment to a card.

Parameters:
- `card_id` (string, required)
- `text` (string, required)

Example:
```json
{"card_id":"<card_id>","text":"Approved. Moving to Done."}
```

### `trello_add_attachment`

Attach a URL to a card.

Parameters:
- `card_id` (string, required)
- `attachment_url` (string, required)
- `name` (string, optional)

Example:
```json
{"card_id":"<card_id>","attachment_url":"https://example.com/report.pdf","name":"Report"}
```

## Field Examples

Use Trello object field names in the `fields` list, or pass `["all"]` to request all fields.

Board fields (common): `id`, `name`, `url`, `closed`, `idOrganization`

List fields (common): `id`, `name`, `closed`, `idBoard`, `pos`

Card fields (common): `id`, `name`, `desc`, `url`, `idList`, `idMembers`, `labels`, `due`, `closed`

Member fields (common): `id`, `fullName`, `username`, `url`

## Permissions and Common Failures

- `401 Unauthorized`: invalid or missing API key/token
- `403 Forbidden`: token missing required scopes
- `404 Not Found`: board/list/card does not exist or not visible to the token
- `429 Too Many Requests`: rate limited by Trello

## Validation Errors

Tools return a structured error object when inputs are outside Trello limits. Examples:

- `limit` outside 1-1000:
```json
{"error":"limit must be between 1 and 1000","field":"limit","help":"Reduce the limit or paginate by calling again with a smaller limit to fetch additional results."}
```

- `desc` longer than 16384 characters:
```json
{"error":"desc exceeds the 16384-character limit","field":"desc","help":"Trim the description and retry."}
```
