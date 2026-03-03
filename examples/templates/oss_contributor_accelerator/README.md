# OSS Contributor Accelerator Template

A systematic approach to identifying and executing high-impact open source contributions through a structured 4-node flow.

## What it does

This template helps contributors move from "I want to contribute" to "I can ship a meaningful PR with a clear plan" by:

1. **Intake** - Collects contributor profile, skills, and target repository context
2. **Issue Scout** - Discovers and ranks high-leverage issues matching the contributor's abilities
3. **Selection** - Helps the contributor strategically pick 1-3 target issues
4. **Contribution Pack** - Generates an execution-ready `contribution_brief.md` with implementation steps, testing strategy, and PR templates

## Why this matters

- **Shortens the contribution path** from intention to execution
- **Improves contributor onboarding** with structured guidance
- **Increases output quality** through strategic issue selection
- **Builds contributor confidence** with clear implementation plans

## Flow Overview

```
intake → issue-scout → selection → contribution-pack
   ↓           ↓            ↓              ↓
Profile    Ranked      Selected     Contribution
& Goals    Issues       Issues        Brief
```

## Usage

### Option 1: Build from template (recommended)

Use the `/hive-create` skill and select "OSS Contributor Accelerator" to customize and export your own agent.

### Option 2: Manual copy

```bash
# 1. Copy to your exports directory
cp -r examples/templates/oss_contributor_accelerator exports/my_oss_accelerator

# 2. Update module references in __main__.py and __init__.py

# 3. Customize goal, nodes, edges, and prompts as needed

# 4. Run it
uv run python -m exports.my_oss_accelerator --input '{"initial_request": "I want to contribute to React"}'
```

## Example Input

```json
{
  "initial_request": "I want to contribute to React. I'm intermediate in JavaScript and TypeScript, can dedicate 5-10 hours per week, and I'm interested in documentation and bug fixes."
}
```

## Expected Output

The agent generates a `contribution_brief.md` file containing:

- **Executive Summary** - Overview of selected contributions
- **Issue Analysis** - Deep dive into each selected issue
- **Implementation Plans** - Step-by-step implementation strategies
- **Testing Strategies** - Comprehensive testing approaches
- **PR Templates** - Draft pull request descriptions
- **Timeline** - Realistic milestones and deliverables

## Customization Tips

- **Adjust skill level assessment** in the intake node for your target audience
- **Modify ranking criteria** in the issue-scout to match your contribution priorities
- **Add domain-specific tools** if targeting specialized repositories
- **Customize the brief template** to match your project's documentation standards

## Success Metrics

- Profile completeness: 100%
- Issue relevance score: ≥8/10
- Strategic selection score: ≥8/10
- Brief completeness: 100%

## Contributing to this Template

This template follows the standard Hive template structure. When making improvements:

1. Maintain the 4-node flow structure
2. Keep success criteria measurable
3. Ensure prompts are clear and actionable
4. Test with real OSS repositories

## License

This template is part of the Hive framework and follows the same license terms.
