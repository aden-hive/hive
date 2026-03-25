# Twilio Tool

SMS and WhatsApp messaging via the Twilio REST API.

## Supported Actions

- **twilio_send_sms** – Send an SMS message
- **twilio_send_whatsapp** – Send a WhatsApp message
- **twilio_list_messages** / **twilio_get_message** / **twilio_delete_message** – Message management
- **twilio_list_phone_numbers** – List phone numbers on the account
- **twilio_list_calls** – List recent voice calls

## Setup

1. Get your Account SID and Auth Token from the [Twilio Console](https://console.twilio.com/).

2. Set the required environment variables:
   ```bash
   export TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   export TWILIO_AUTH_TOKEN=your-auth-token
   export TWILIO_PHONE_NUMBER=+15551234567   # your Twilio phone number
   ```

## Use Case

Example: "Send an SMS alert to the on-call engineer when a production incident is detected, then log the message SID for tracking."
