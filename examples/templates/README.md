# Templates

A template is a working agent scaffold that follows the standard Hive export structure. Copy it, rename it, customize the goal/nodes/edges, and run it.

## Quick Start

```bash
# List all available templates
hive template list

# List templates by category
hive template list --category research
# Search for templates
hive template list --search "email"
# Show details for a specific template
hive template show job_hunter
# Copy a template to your exports directory
hive template copy job_hunter
# List available categories
hive template categories
# List all tags
hive template tags
```

## What's in a Template

Each template is a complete agent package:
```
template_name/
├── __init__.py       # Package exports
├── __main__.py       # CLI entry point
├── agent.py          # Goal, edges, graph spec, agent class
├── agent.json        # Agent definition (used by build-from-template)
├── template.json     # Template metadata (category, tags, author)
├── config.py         # Runtime configuration
├── nodes/
│   └── __init__.py   # Node definitions (NodeSpec instances)
└── README.md         # What this template demonstrates
```
### Template Metadata (template.json)

The `template.json` file contains metadata for the template library:
```json
{
  "name": "Job Hunter",
  "description": "Analyze resumes and find matching job opportunities.",
  "category": "productivity",
  "tags": ["career", "job-search", "resume", "automation"],
  "author": "Hive Team",
  "version": "1.0.0"
}
```

## Categories
| Category | Description |
|----------|-------------|
| `sales` | Sales and lead generation agents |
| `support` | Customer support and issue triage |
| `ops` | Operations and infrastructure |
| `research` | Research and information gathering |
| `growth` | Growth and marketing automation |
| `productivity` | Personal and team productivity tools |
| `development` | Development and DevOps tools |
| `hr` | Human resources and employee management |
| `finance` | Finance and accounting automation |
| `marketing` | Marketing and campaign management |
| `general` | General-purpose agents |

## Available Templates
| Template | Category | Description |
|----------|----------|-------------|
| [deep_research_agent](deep_research_agent/) | Research | Interactive research agent that searches diverse sources, evaluates findings with user checkpoints, and produces a cited HTML report |
| [local_business_extractor](local_business_extractor/) | Sales | Finds local businesses on Google Maps, scrapes contact details, and syncs to Google Sheets |
| [tech_news_reporter](tech_news_reporter/) | Research | Researches the latest technology and AI news from the web and produces a well-organized report |
| [job_hunter](job_hunter/) | Productivity | Analyzes resumes, finds matching job opportunities, generates customized application materials |
| [support_debugger](support_debugger/) | Support | Helps debug and resolve customer support issues |
| [meeting_scheduler](meeting_scheduler/) | Productivity | Automates meeting scheduling by coordinating calendars and sending invitations |
| [email_reply_agent](email_reply_agent/) | Productivity | Automatically drafts replies to emails based on context and user preferences |
| [hr_onboarding_orchestrator](hr_onboarding_orchestrator/) | HR | Orchestrates employee onboarding process by coordinating tasks, documentation, and communications |
| [mcp_toolsmith](mcp_toolsmith/) | Development | Helps create and manage MCP tools for extending agent capabilities |
| [hacker_news_briefing](hacker_news_briefing/) | Research | Curates and summarizes top stories from Hacker News for daily briefings |
| [interview_prep_assistant](interview_prep_assistant/) | Productivity | Helps prepare for job interviews by researching companies and generating practice questions |
| [dependency_vulnerability_auditor](dependency_vulnerability_auditor/) | Development | Scans project dependencies for known security vulnerabilities and suggests updates |
| [twitter_news_agent](twitter_news_agent/) | Research | Monitors Twitter for news and trends, curating relevant content for users |
| [vulnerability_assessment](vulnerability_assessment/) | Development | Performs security vulnerability assessments on systems and applications |
| [invoice_ap_agent](invoice_ap_agent/) | Finance | Automates accounts payable processes including invoice processing and payment scheduling |
| [marketing_ops_traffic_controller](marketing_ops_traffic_controller/) | Marketing | Manages and routes marketing operations tasks, coordinating campaigns and content distribution |
| [sales_call_news_researcher](sales_call_news_researcher/) | Sales | Researches prospects before sales calls, gathering relevant news and insights |
| [content_research_swarm](content_research_swarm/) | Research | Multi-agent system that researches and curates content from multiple sources |
| [competitive_intel_agent](competitive_intel_agent/) | Research | Gathers and analyzes competitive intelligence from various sources |
| [agent_qa_pipeline](agent_qa_pipeline/) | Development | Automated quality assurance pipeline for testing and validating agents |
| [contract_intelligence_agent](contract_intelligence_agent/) | Finance | Analyzes contracts to extract key terms, risks, and compliance requirements |
| [financial_ledger_agent](financial_ledger_agent/) | Finance | Automates financial ledger management and transaction reconciliation |
| [issue_triage_agent](issue_triage_agent/) | Support | Automatically triages and categorizes issues from various sources for efficient handling |
| [oss_lead_intelligence](oss_lead_intelligence/) | Sales | Identifies and qualifies open-source leads for business development opportunities |
| [email_inbox_management](email_inbox_management/) | Productivity | Automates email inbox organization, filtering, and response prioritization |

## Programmatic Access

You from framework.templates import TemplateRegistry, get_template_registry

    registry = get_template_registry()
    
    # Discover all templates
    templates = registry.discover_templates()
    
    # Filter by category
    from framework.templates import TemplateCategory
    research_templates = registry.list_by_category(TemplateCategory.RESEARCH)
    
    # Search templates
    results = registry.search("email")
    
    # Get a specific template
    template = registry.get_template("job_hunter")
```
