# Quick Contributor Guide - Real Issues to Help Grow the Project

## Step 1: Install Python

**Windows Installation:**
1. Download Python 3.11+ from: https://www.python.org/downloads/
2. **IMPORTANT:** Check "Add Python to PATH" during installation
3. Verify: Open PowerShell and run `python --version`

## Step 2: Real Issues That Help the Project Grow

### 🐛 Bug Fixes (High Impact)

1. **Remove LLM Dependency from MCP Server** (`issues/remove-llm-dependency-from-mcp-server.md`)
   - **Why it matters:** Breaks for users without Anthropic API key
   - **Impact:** Makes the framework work for more users
   - **File:** `core/framework/mcp/agent_builder_server.py`
   - **Difficulty:** Medium

### 🚀 Features from Roadmap (High Value)

2. **Web Search Tool** (ROADMAP.md line 62)
   - **Why it matters:** Essential for agents that need real-time information
   - **Impact:** Enables more powerful agent capabilities
   - **Location:** `tools/src/aden_tools/tools/web_search_tool/`
   - **Status:** Partially done, needs completion
   - **Difficulty:** Medium

3. **Web Scraper Tool** (ROADMAP.md line 63)
   - **Why it matters:** Agents need to extract data from websites
   - **Impact:** Enables data collection agents
   - **Location:** `tools/src/aden_tools/tools/web_scrape_tool/`
   - **Status:** Partially done, needs completion
   - **Difficulty:** Medium

4. **Audit Trail Tool** (ROADMAP.md line 61)
   - **Why it matters:** Track agent decisions for debugging and compliance
   - **Impact:** Better observability and trust
   - **Difficulty:** Medium-Hard

5. **Sample Agents** (ROADMAP.md lines 94-96)
   - Knowledge Agent
   - Blog Writer Agent
   - SDR Agent
   - **Why it matters:** Shows users what's possible, attracts more users
   - **Impact:** Demonstrates framework capabilities
   - **Difficulty:** Medium (you can learn while building)

6. **Pydantic Validation for LLM Outputs** (ROADMAP.md line 78)
   - **Why it matters:** Ensures agents return structured, valid data
   - **Impact:** More reliable agents
   - **Difficulty:** Medium

## Step 3: How to Contribute

1. **Fork & Clone:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/hive.git
   cd hive
   ```

2. **Set up environment:**
   ```bash
   ./scripts/setup-python.sh
   ```

3. **Pick an issue:**
   - Comment on the GitHub issue: "I'd like to work on this!"
   - Wait for assignment (24 hours max)

4. **Create a branch:**
   ```bash
   git checkout -b fix/your-feature-name
   ```

5. **Make changes & test:**
   ```bash
   # Run tests
   cd core && python -m pytest
   cd ../tools && python -m pytest
   ```

6. **Submit PR:**
   - Push your branch
   - Create Pull Request on GitHub
   - Follow PR template

## Recommended First Contribution

**Start with: Remove LLM Dependency from MCP Server**

This is a real bug that:
- Has clear instructions in `issues/remove-llm-dependency-from-mcp-server.md`
- Helps the project work for more users
- Shows you can fix real problems
- Is well-documented with exact file locations

## Learning Resources

- Python basics: https://www.python.org/about/gettingstarted/
- Project structure: See `DEVELOPER.md`
- Code style: See `CONTRIBUTING.md`

## Need Help?

- Discord: https://discord.com/invite/MXE49hrKDk
- GitHub Issues: https://github.com/adenhq/hive/issues
