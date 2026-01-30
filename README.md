# Hive Agent System - Production Ready 🚀

**Multi-platform AI agent with 43 integrated tools for automation**

---

## Quick Start (30 seconds)

### Option 1: Windows Batch Script
```cmd
cd c:\Users\M.S.Seshashayanan\Desktop\Aden\hive
start_hive.bat
```

### Option 2: Python Quick Start
```cmd
cd c:\Users\M.S.Seshashayanan\Desktop\Aden\hive
python quick_start.py
```

### Option 3: Full Interactive CLI
```cmd
cd c:\Users\M.S.Seshashayanan\Desktop\Aden\hive
python hive_cli.py
```

---

## What You Can Do

### ✅ Features
- ✅ **Create Support Tickets** - Automated ticket management
- ✅ **Slack Integration** - Team messaging and notifications
- ✅ **CRM Management** - Create, search, update contacts
- ✅ **Jira Integration** - Project sync and issue tracking
- ✅ **Salesforce Integration** - CRM sync and opportunity management
- ✅ **Database Storage** - SQLite with 43 tools
- ✅ **Notifications** - Email/SMS/Slack alerts
- ✅ **Status Monitoring** - Real-time system health

---

## Available Commands

### Quick Start Menu
```
1. Create Ticket       - Interactive ticket creation
2. Check Status        - View all integration statuses
3. Search Contacts     - Find CRM contacts
4. Test Slack          - Verify Slack connection
5. Test Jira           - Verify Jira connection
0. Exit
```

### Full CLI Menu
```
1. Create a Support Ticket     - With Slack notification option
2. Send a Notification         - Email/SMS/Slack
3. Manage CRM Contact          - Create/Search/Update
4. Sync with Jira              - List projects & sync issues
5. Send Slack Message          - Direct messaging
6. Check System Status         - Full health check
7. Run Custom Agent Task       - LLM-powered automation
0. Exit
```

---

## Example Usage

### Create a Ticket
```
$ python quick_start.py
Choose: 1
Title: Production System Down
Description: Critical error affecting users
Priority: high

[OK] Created: TICKET-0001
[OK] Status: open
[OK] Priority: high
```

### Check System Status
```
Choose: 2

--- SYSTEM STATUS ---
Slack:      [OK] Connected to workspace
Jira:       [OK] 3 projects synced
Salesforce: [OK] 127 contacts available
Tickets:    [OK] 5 total (2 open, 3 closed)
Database:   [OK] SQLite active
```

### Search Contacts
```
Choose: 3
Search: john@acme.com

Found 1:
  - John Smith (john@acme.com) - Acme Corp
```

### Multi-Agent Pipeline
```
$ python examples/example.py

EASY EXAMPLE:   [OK] Ticket created (TICKET-0001)
MEDIUM EXAMPLE: [OK] Multi-agent routing (3/3 success)
HARD EXAMPLE:   [OK] Async pipeline (cache hits: 1, success: 4/5)
```

---

## Environment Setup

### Required Variables (.env file)
```bash
# LLM (for agent automation)
CEREBRAS_API_KEY=your_key_here

# Slack
SLACK_ACCESS_TOKEN=xoxe.xoxp-...

# Jira
JIRA_URL=https://yourorg.atlassian.net
JIRA_EMAIL=your.email@example.com
JIRA_API_TOKEN=your_token_here

# Salesforce
SALESFORCE_USERNAME=your_username
SALESFORCE_PASSWORD=your_password
SALESFORCE_SECURITY_TOKEN=your_token
```

### Clear Proxy (if needed)
```cmd
set HTTP_PROXY=
set HTTPS_PROXY=
```

---

## Architecture

### 43 Tools Available

**Core Tools (12)**
- File operations, web search, PDF reading, command execution

**Action/Command Tools (14)**
- Notifications, CRM (6 tools), Tickets (6 tools)

**Jira Integration (7)**
- Connection test, projects, issues, create, update, sync

**Slack Integration (4)**
- Connection test, channels, messaging, rich messages

**Salesforce Integration (6)**
- Connection test, query, contacts, opportunities, sync

### Database
- **Type**: SQLite (local development)
- **Location**: `tools/data/aden_tools.db`
- **Upgrade Path**: PostgreSQL for production

---

## Files Structure

```
hive/
├── start_hive.bat              # Windows launcher
├── quick_start.py              # Simplified CLI ⭐
├── hive_cli.py                 # Full interactive CLI
├── autonomous_agent.py         # Auto issue resolution
├── examples/
│   └── example.py              # Easy/Medium/Hard examples
├── PRODUCTION_READY.md         # Deployment guide
├── .env                        # API credentials
├── tools/
│   ├── src/
│   │   ├── aden_tools/
│   │   │   ├── tools/          # 43 tools
│   │   │   └── db/             # Database layer
│   │   └── multi_platform_demo.py
│   └── data/
│       └── aden_tools.db       # SQLite database
└── core/
    └── src/framework/          # LLM & graph execution
```

---

## Troubleshooting

### Proxy Error
**Error**: `URL can't contain control characters`
**Fix**:
```cmd
set HTTP_PROXY=
set HTTPS_PROXY=
```

### Import Error
**Error**: `ModuleNotFoundError`
**Fix**: Make sure you're in the `hive` directory:
```cmd
cd c:\Users\M.S.Seshashayanan\Desktop\Aden\hive
```

---

## Production Deployment

### Pre-flight Checklist
- [ ] `.env` file configured with all credentials
- [ ] Proxy environment variables cleared
- [ ] Python 3.11+ installed
- [ ] All dependencies installed (`pip install -r requirements.txt`)
- [ ] Database initialized (auto-created on first run)

### Run Examples
```cmd
# Comprehensive examples (Easy/Medium/Hard)
python examples/example.py

# Multi-platform demo
python tools\src\multi_platform_demo.py
```

### Deploy
```cmd
# Start the interactive CLI
python quick_start.py

# Or run autonomous agent
python autonomous_agent.py
```

---

## Success Metrics

✅ **43 tools** registered and tested  
✅ **Slack** integration ready  
✅ **Jira** integration ready  
✅ **Salesforce** integration ready  
✅ **Database** working with SQLite  
✅ **Examples** Easy/Medium/Hard  
✅ **CLI** interactive and user-friendly  

---

**Ready for Production** 🎉

Run `python quick_start.py` to get started!
