# Recipes

A recipe describes an agent's design — the goal, nodes, prompts, edge logic, and tools — without providing runnable code. Think of it as a blueprint: it tells you *how* to build the agent, but you do the building.

## What's in a recipe

Each recipe is a markdown file (or folder with a markdown file) containing:

- **Goal**: What the agent accomplishes, including success criteria and constraints
- **Nodes**: Each step in the workflow, with the system prompt, node type, and input/output keys
- **Edges**: How nodes connect, including conditions and routing logic
- **Tools**: What external tools or MCP servers the agent needs
- **Usage notes**: Tips, gotchas, and suggested variations

## How to use a recipe

1. Read through the recipe to understand the design
2. Create a new agent using the standard export structure (see [templates/](../templates/) for a scaffold)
3. Translate the recipe's goal, nodes, and edges into code
4. Wire in the tools described
5. Test and iterate

## Available recipes

### Sales & Marketing
| Recipe | Description |
|--------|-------------|
| [social_media_management](social_media_management/) | Schedule posts, reply to comments, monitor trends |
| [newsletter_production](newsletter_production/) | Transform voice memos and ideas into polished emails |
| [ad_campaign_monitoring](ad_campaign_monitoring/) | Monitor ad spend and flag CPA spikes |
| [crm_hygiene](crm_hygiene/) | Ensure every lead has follow-up dates and status |

### Customer Success
| Recipe | Description |
|--------|-------------|
| [inquiry_triaging](inquiry_triaging/) | Sort tire kickers from hot leads |
| [onboarding_assistance](onboarding_assistance/) | Guide new clients through setup and welcome kits |

### Operations Automation
| Recipe | Description |
|--------|-------------|
| [inbox_management](inbox_management/) | Clear spam and surface emails that need your brain |
| [invoicing_collections](invoicing_collections/) | Send invoices and chase overdue payments |
| [data_keeper](data_keeper/) | Pull data from multiple sources into unified reports |
| [calendar_coordination](calendar_coordination/) | Protect Deep Work time and book travel |

### Technical & Product Maintenance
| Recipe | Description |
|--------|-------------|
| [quality_assurance](quality_assurance/) | Test features and links before they go live |
| [documentation](documentation/) | Turn messy processes into clean SOPs |
| [basic_troubleshooting](basic_troubleshooting/) | Handle Level 1 tech support |
| [issue_triaging](issue_triaging/) | Categorize and route bug reports by severity |