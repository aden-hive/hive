# Brevo Tool

The Brevo tool allows Aden Hive agents to send transactional emails and SMS, and manage contacts using the [Brevo API v3](https://developers.brevo.com/reference).

## Features

- **Transactional Emails**: Send high-deliverability emails with HTML and text content.
- **Transactional SMS**: Send SMS notifications and alerts worldwide.
- **Contact Management**: Create, update, and retrieve contact details, including attributes and list associations.

## Configuration

The tool requires a Brevo API key. You can provide it in two ways:

1. **Environment Variable**: Set `BREVO_API_KEY` in your environment.
2. **Credential Store**: Add a credential named `brevo` to the Hive credential store.

Get your API key at [Brevo API Settings](https://app.brevo.com/settings/keys/api).

## Tools

### `brevo_send_email`
Sends a transactional email.
- **to**: List of recipient dictionaries (email and optional name).
- **subject**: Email subject line.
- **html_content**: HTML body of the email.
- **sender_email**: Verified sender email in Brevo.
- **sender_name**: Optional display name for the sender.
- **text_content**: Optional plain text alternative.
- **cc/bcc**: Optional lists of CC/BCC recipients.
- **reply_to_email**: Optional reply-to address.
- **tags**: Optional tags for categorization.

### `brevo_send_sms`
Sends a transactional SMS.
- **sender**: Sender name (alphanumeric) or phone number.
- **recipient**: Recipient phone number with country code.
- **content**: SMS text message.
- **sms_type**: "transactional" or "marketing".
- **tag**: Optional tag for categorization.

### `brevo_create_contact`
Creates a new contact in Brevo.
- **email**: Contact email address.
- **attributes**: Dictionary of contact attributes (e.g., `{"FNAME": "John"}`).
- **list_ids**: Optional list of integer IDs to add the contact to.
- **update_enabled**: If true, updates existing contact if email match found.

### `brevo_get_contact`
Retrieves contact details by email or ID.
- **identifier**: Email address or numeric contact ID.

### `brevo_update_contact`
Updates an existing contact.
- **identifier**: Email address or numeric contact ID.
- **attributes**: Dictionary of attributes to update.
- **list_ids**: List of IDs to add.
- **unlink_list_ids**: List of IDs to remove.
