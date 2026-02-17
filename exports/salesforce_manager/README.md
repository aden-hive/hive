# Salesforce Manager Agent

This agent integrates with Salesforce CRM to manage leads, contacts, and opportunities. It can perform searches, create/update records, and run custom SOQL queries.

## Features

- **Lead/Contact Search**: Quickly find records by name or criteria.
- **Record Management**: Create and update Salesforce records.
- **Custom SOQL**: Run any valid SOQL query to retrieve specific datasets.
- **Schema Discovery**: Describe Salesforce objects to understand their structure.

## Usage

### Prerequisites

Ensure you have Salesforce credentials configured in your `.env` file or environment:
- `SALESFORCE_INSTANCE_URL`
- `SALESFORCE_ACCESS_TOKEN`

### Running the Agent

To run the agent in interactive shell mode:
```bash
python -m exports.salesforce_manager shell
```

To run a single task:
```bash
python -m exports.salesforce_manager run --query "Find leads named 'John Smith'"
```

## Architecture

The agent follows a 3-node graph:
1. **Intake**: Clarifies the user's Salesforce task.
2. **Salesforce Manager**: Executes the task using native Salesforce tools.
3. **Output**: Presents the results and handles follow-ups.
