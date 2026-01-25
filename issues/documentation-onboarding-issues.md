Issue 1: Platform-Specific Documentation Fails on Windows (Cross-Platform Support Missing)
Summary
The documentation exclusively uses Unix/Linux command syntax, making the project inaccessible to Windows users. Environment variable setting and path separators differ between platforms, causing immediate failure for Windows/PowerShell users following the quick start guide.

Affected Documentation
README.md - Quick Start section, installation commands

DEVELOPER.md - Development setup and running agents

CONTRIBUTING.md - Testing and development workflow

Problem
When Windows users follow the documented commands, they encounter:

powershell
# Documented command:
PYTHONPATH=core:exports python -m support_ticket_agent validate

# Windows error:
PYTHONPATH=core:exports : The term 'PYTHONPATH=core:exports' is not recognized...
Root Cause:

Unix uses : as PATH separator; Windows uses ;

Unix uses VAR=value command syntax; Windows requires $env:VAR=value (PowerShell) or set VAR=value (CMD)

No platform-agnostic alternatives provided

Impact
Blocks 45% of developers (Windows market share)

Increases onboarding friction significantly

Limits project adoption to Unix-only environments

Wastes user time figuring out platform translations

Proposed Solutions
Option A: Platform-agnostic Python approach (Recommended)

python
# scripts/run_agent.py
import sys
import os
sys.path.insert(0, 'core')
sys.path.insert(0, 'exports')
from framework.runner import AgentRunner
# Run agent...
Option B: Platform-specific documentation
Add separate sections for:

Unix/Linux/Mac (current)

Windows PowerShell

Windows Command Prompt

Git Bash on Windows

Option C: Environment wrapper script

bash
# scripts/run.sh / scripts/run.ps1 / scripts/run.bat
# Automatically detects platform and sets variables correctly
Implementation Details
markdown
**Unix/Linux/Mac:**
```bash
PYTHONPATH=core:exports python -m agent_name
Windows PowerShell:

powershell
$env:PYTHONPATH="core;exports"
python -m agent_name
Windows Command Prompt:

cmd
set PYTHONPATH=core;exports
python -m agent_name
Git Bash (Windows):

bash
export PYTHONPATH=core:exports
python -m agent_name
text

---

## **Issue 2: Missing `exports/` Directory Blocks All Examples and Testing**

### **Summary**
The `exports/` directory, referenced throughout documentation as containing example agents, doesn't exist in the repository. This prevents users from running any examples to verify their setup or learn from working agents.

### **Affected Documentation**
- `README.md` - "Run your agent" examples
- `DEVELOPER.md` - Agent development and testing sections
- `CONTRIBUTING.md` - Testing guidelines

### **Problem**
```bash
# Following documentation:
$ ls exports/
ls: cannot access 'exports/': No such file or directory

$ PYTHONPATH=core:exports python -m support_ticket_agent validate
ModuleNotFoundError: No module named 'support_ticket_agent'
Root Cause:

Repository structure shows exports/ in documentation but not in actual repo

Example agents are either:

Intentionally excluded (to keep repo lightweight)

Meant to be generated but documentation doesn't explain how

Missing from version control

Impact
Zero working examples for new users

Cannot verify setup - users don't know if installation worked

Increased support burden as users get stuck immediately

Poor onboarding experience - "hello world" doesn't work

Proposed Solutions
Option A: Include minimal example agents (Recommended)
Add 2-3 simple agents to exports/:

hello_world_agent - Basic validation agent

support_ticket_agent - Documented example

echo_agent - Simple echo/parrot agent for testing

Option B: Generate-on-first-use approach
Create scripts/generate-examples.py that:

Creates exports/ directory if missing

Generates minimal working agents

Updates documentation to run this script first

Option C: Documentation-only fix
Update documentation to:

Explain exports/ is for user-created agents

Provide command to create first agent

Update examples to use your_agent_name placeholder

Implementation Details
markdown
**Suggested example agent structure:**
exports/
├── hello_world_agent/
│ ├── init.py
│ ├── main.py
│ ├── agent.json
│ └── README.md
└── support_ticket_agent/
├── init.py
├── main.py
├── agent.json
├── tools.py
└── tests/

text

**agent.json content for hello_world_agent:**
```json
{
  "goal": {
    "goal_id": "hello_world",
    "name": "Hello World Agent",
    "description": "Simple agent that echoes input",
    "success_criteria": "Returns formatted greeting"
  },
  "nodes": [
    {
      "node_id": "echo",
      "name": "Echo Node",
      "node_type": "function",
      "function": "exports.hello_world_agent.tools.echo_function",
      "input_keys": ["name"],
      "output_keys": ["greeting"]
    }
  ]
}
text

---

## **Issue 3: Confusing Documentation Mixes Claude Code IDE and Terminal Commands**

### **Summary**
Documentation uses `claude>` prefix for Claude Code IDE commands without clear distinction from terminal commands, causing users to incorrectly run IDE commands in their terminal.

### **Affected Documentation**
- `README.md` - "Build Your First Agent" section
- `DEVELOPER.md` - "Building Agents" section
- `.claude/skills/` - Skill documentation

### **Problem**
```bash
# User tries documented command:
$ claude> /building-agents
bash: /building-agents: Permission denied

# Or:
$ claude> /testing-agent
bash: /testing-agent: Permission denied
Root Cause:

claude> is Claude Code IDE prompt, not terminal command

Documentation doesn't distinguish IDE vs terminal contexts

No alternative terminal commands provided for users without Claude Code

Impact
User confusion about where to run commands

Wasted time debugging why commands fail

Assumption of broken setup when it's just wrong context

Accessibility issue for users without Claude Code IDE

Proposed Solutions
Option A: Clear context labeling (Recommended)

markdown
**In Claude Code IDE:**
claude> /building-agents

text

**In terminal:**
```bash
# Alternative approach without Claude Code:
python scripts/build_agent.py --goal "Build customer support agent"
text

**Option B: Terminal-equivalent commands**
Provide parallel documentation:
- Claude Code IDE workflow
- Terminal/script-based workflow

**Option C: Installation check and guidance**
Add note: "These commands require Claude Code IDE. Download from [link]. For terminal alternatives, see [section]."

### **Implementation Details**
```markdown
**Documentation improvements:**

1. **Add header note:**
Note: Commands prefixed with claude> are for the Claude Code IDE.
For terminal usage, see "Command Line Interface" section below.

text

2. **Create CLI alternatives:**
```bash
# Instead of: claude> /building-agents
python -m framework.cli build-agent --goal "Your goal here"

# Instead of: claude> /testing-agent
python -m framework.cli test-agent --agent exports/your_agent
Context boxes:

markdown
::: tip Claude Code IDE
Run this in Claude Code:
claude> /building-agents

text
:::

::: tip Terminal
Run this in your terminal:
```bash
./scripts/build_agent.py "Your goal here"
:::

text
Issue 4: Inconsistent Path Handling Across Documentation
Summary
Documentation shows inconsistent Python path and module import patterns, mixing relative paths, absolute paths, and environment variables without clear guidance.

Affected Documentation
README.md - Multiple PYTHONPATH examples

DEVELOPER.md - Development and testing commands

CONTRIBUTING.md - Contribution workflow

Problem
bash
# Various patterns shown:
PYTHONPATH=core:exports python -m agent_name
cd core && python -m pytest
PYTHONPATH=. python -m framework.runner
Root Cause:

No consistent pattern for running agents/tests

Mixed use of PYTHONPATH vs cd into directories

No explanation of why certain patterns are needed

Platform-dependent issues not addressed

Impact
Inconsistent user experience - different commands for same task

Hidden dependencies on current directory

Copy-paste failures when users are in wrong directory

Debugging difficulty due to unclear path requirements

Proposed Solutions
Option A: Standardize on one approach (Recommended)
Choose either:

Always use PYTHONPATH with project root as base

Always cd into appropriate directory first

Create wrapper scripts for all operations

Option B: Comprehensive path guide
Add "Understanding Paths and Imports" section explaining:

Project structure

Python module resolution

When to use PYTHONPATH vs cd

Platform differences

Option C: Makefile/script abstraction

makefile
# Makefile
run-agent:
	PYTHONPATH=core:exports python -m $(agent)

test:
	cd core && python -m pytest

validate-agent:
	PYTHONPATH=core:exports python -m $(agent) validate
Implementation Details
markdown
**Recommended standardization:**

```bash
# Pattern 1: From project root with PYTHONPATH (Preferred)
PYTHONPATH=core:exports python -m agent_name run --input '{}'

# Pattern 2: From agent directory
cd exports/agent_name
python -m agent_name run --input '{}'

# Pattern 3: Using helper script
./scripts/run_agent.sh agent_name --input '{}'

**Add to documentation:**
Working Directory Patterns
==========================

This project supports multiple working directory patterns. Choose one:

Project Root Pattern (Recommended):

bash
# Always run from hive/ directory
PYTHONPATH=core:exports python -m agent_name
Agent Directory Pattern:

bash
cd exports/agent_name
python -m agent_name
Script Pattern:

bash
./scripts/run_agent.py agent_name