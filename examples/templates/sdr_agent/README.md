# SDR Agent Template

A production-ready starting point for building autonomous Sales Development Representative (SDR) agents. This template implements a complete lead processing workflow that researches prospects, qualifies them against your criteria, and drafts personalized outreach emails with human-in-the-loop review.

## 🚀 Impact

A typical SDR manually qualifies 20-30 leads/day. This agent can process **100+ leads/day** with consistent scoring criteria, saving **~15 hours/week** of manual research and qualification work. It allows your sales team to focus purely on high-value interactions rather than data gathering.

## 🧠 Workflow

The agent follows a sales-proven logic graph:

1.  **Research**: Deep dive into company news, funding, and prospect role using web search.
2.  **Qualify**: Score the lead against your Ideal Customer Profile (ICP).
3.  **Cross-Check**: If qualified, proceed; otherwise, log the disqualification reason.
4.  **Draft**: Generate a hyper-personalized email based on research insights (not templates).
5.  **Review (HITL)**: A human reviews the draft. If rejected, the agent regenerates it based on feedback.
6.  **Action**: Simulate sending the email and updating the CRM status.

## 🛠️ Usage

### Prerequisites
- Python 3.10+
- Anthropic API Key (or other supported LLM provider)
- (Optional) Brave Search API Key for live web research

### Setup

```bash
# Install dependencies (assuming hive is installed)
pip install -r requirements.txt
```

### Running the Agent

You can run the agent via the CLI for a single prospect:

```bash
python -m examples.templates.sdr_agent '{"prospect_name": "John Doe", "company_name": "Acme Corp", "prospect_role": "CTO"}'
```

## ⚙️ Customization Points

To adapt this template to your specific business process, focus on these key files:

### 1. Lead Scoring Logic (`nodes/__init__.py`)
Modify the `qualify_node` system prompt to reflect your specific ICP.
- **Current**: Generic B2B sizing and role fit.
- **Customize**: Add specific revenue thresholds, technologies used, or geographic requirements.

### 2. Outreach Tone (`nodes/__init__.py`)
Adjust the `outreach_node` prompt to match your brand voice.
- **Current**: Professional but conversational.
- **Customize**: Add examples of your best-performing emails to the prompt (few-shot prompting) to guide the style.

### 3. CRM Integration (`nodes/__init__.py`)
The `send_node` currently mocks a CRM update.
- **Customize**: Replace the mock logic with actual API calls to Salesforce, HubSpot, or Pipedrive using the `tool_registry`.

### 4. Search Tools (`mcp_servers.json`)
The agent uses a local MCP server for web search. You can swap this for internal knowledge base search tools if you want to qualify leads against internal data.

## 🛡️ Human-in-the-Loop (HITL)

Trust is built, not given. This template includes a **Review Node** by default.
- The agent pauses after drafting an email.
- You can approve it (simulates sending) or provide feedback (triggers regeneration).
- Once you trust the agent's output, you can remove the `review-draft` node from `agent.py` edges for fully autonomous operation.
