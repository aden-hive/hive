#!/usr/bin/env python3
"""
GitHub Outreach Pipeline Demo

Demonstrates the full GraphExecutor framework: sequential pipeline,
fan-out/fan-in parallel execution, feedback/callback edges, and
client-facing HITL checkpoints — using a realistic GitHub outreach workflow.

Pipeline:
    Intake (HITL) → Scanner → [Profiler || Scorer] → Extractor
      → Review (HITL) ⇄ Extractor (feedback)
        → Campaign Builder → Approval (HITL) ⇄ Campaign Builder (feedback)
          → Sender (terminal)

Features demonstrated:
- Sequential pipeline (Intake → Scanner → ...)
- Fan-out / fan-in (Scanner → [Profiler, Scorer] → Extractor)
- Feedback edges (Review → Extractor, Approval → Campaign Builder)
- Client-facing HITL checkpoints (Intake, Review, Approval)
- SchemaJudge for output validation + native client_facing blocking for HITL
- max_node_visits for feedback loop control

Usage:
    cd /home/timothy/oss/hive/core
    python demos/github_outreach_demo.py

    Then open http://localhost:8768 in your browser.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from collections.abc import Callable
from http import HTTPStatus
from pathlib import Path
from typing import Any

import httpx
import websockets
from pydantic import BaseModel, ValidationError
from websockets.http11 import Request, Response

# Add core, tools, and hive root to path
_CORE_DIR = Path(__file__).resolve().parent.parent
_HIVE_DIR = _CORE_DIR.parent
sys.path.insert(0, str(_CORE_DIR))
sys.path.insert(0, str(_HIVE_DIR / "tools" / "src"))
sys.path.insert(0, str(_HIVE_DIR))

from aden_tools.credentials import CREDENTIAL_SPECS, CredentialStoreAdapter  # noqa: E402
from core.framework.credentials import CredentialStore  # noqa: E402

from framework.credentials.storage import (  # noqa: E402
    CompositeStorage,
    EncryptedFileStorage,
    EnvVarStorage,
)
from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec  # noqa: E402
from framework.graph.event_loop_node import (  # noqa: E402
    EventLoopNode,
    JudgeVerdict,
    LoopConfig,
)
from framework.graph.executor import GraphExecutor  # noqa: E402
from framework.graph.goal import Goal  # noqa: E402
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec  # noqa: E402
from framework.llm.litellm import LiteLLMProvider  # noqa: E402
from framework.runner.tool_registry import ToolRegistry  # noqa: E402
from framework.runtime.core import Runtime  # noqa: E402
from framework.runtime.event_bus import (  # noqa: E402
    AgentEvent,
    EventBus,
    EventType,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("github_outreach_demo")

# -------------------------------------------------------------------------
# Persistent state
# -------------------------------------------------------------------------

STORE_DIR = Path(tempfile.mkdtemp(prefix="hive_outreach_"))
RUNTIME = Runtime(STORE_DIR / "runtime")
LLM = LiteLLMProvider(model="claude-haiku-4-5-20251001")

# -------------------------------------------------------------------------
# Credentials
# -------------------------------------------------------------------------

_env_mapping = {name: spec.env_var for name, spec in CREDENTIAL_SPECS.items()}
_local_storage = CompositeStorage(
    primary=EncryptedFileStorage(),
    fallbacks=[EnvVarStorage(env_mapping=_env_mapping)],
)

if os.environ.get("ADEN_API_KEY"):
    try:
        from framework.credentials.aden import (  # noqa: E402
            AdenCachedStorage,
            AdenClientConfig,
            AdenCredentialClient,
            AdenSyncProvider,
        )

        _client = AdenCredentialClient(AdenClientConfig(base_url="https://api.adenhq.com"))
        _provider = AdenSyncProvider(client=_client)
        _storage = AdenCachedStorage(
            local_storage=_local_storage,
            aden_provider=_provider,
        )
        _cred_store = CredentialStore(storage=_storage, providers=[_provider], auto_refresh=True)
        _synced = _provider.sync_all(_cred_store)
        logger.info("Synced %d credentials from Aden", _synced)
    except Exception as e:
        logger.warning("Aden sync unavailable: %s", e)
        _cred_store = CredentialStore(storage=_local_storage)
else:
    logger.info("ADEN_API_KEY not set, using local credential storage")
    _cred_store = CredentialStore(storage=_local_storage)

CREDENTIALS = CredentialStoreAdapter(_cred_store)


# =========================================================================
# Pydantic Output Models (structural validation for hybrid judges)
# =========================================================================


class IntakeOutput(BaseModel):
    repo_url: str
    project_url: str
    scan_config: str
    min_leads: str  # Minimum number of leads to collect (numeric string)


class GitHubUser(BaseModel):
    username: str
    user_type: str  # stargazer | contributor | issue_author


class ScannerOutput(BaseModel):
    github_users: str  # Filename of JSON file containing list[GitHubUser]


class UserProfile(BaseModel):
    username: str
    name: str | None = None
    bio: str | None = None
    company: str | None = None
    languages: list[str] = []


class ProfilerOutput(BaseModel):
    user_profiles: str  # Filename of JSON file containing list[UserProfile]


class RelevanceScore(BaseModel):
    username: str
    score: float
    reasoning: str


class ScorerOutput(BaseModel):
    relevance_scores: str  # Filename of JSON file containing list[RelevanceScore]


class Contact(BaseModel):
    username: str
    name: str | None = None
    email: str | None = None
    twitter: str | None = None
    relevance_score: float


class ExtractorOutput(BaseModel):
    contact_list: str  # Filename of JSON file containing list[Contact]


class DraftEmail(BaseModel):
    recipient: str
    subject: str
    body: str


class CampaignOutput(BaseModel):
    draft_emails: str  # Filename of JSON file containing list[DraftEmail]


# =========================================================================
# Tool Registration
# =========================================================================

TOOL_REGISTRY = ToolRegistry()

# ---- MCP server tools (GitHub, web search, web scrape, email) ----
# The aden-tools MCP server provides the official tool implementations.
# Tools are auto-discovered via register_mcp_server() and available to
# nodes through their NodeSpec.tools lists.

_MCP_SERVER_PATH = str(_HIVE_DIR / "tools" / "mcp_server.py")

_mcp_tool_count = TOOL_REGISTRY.register_mcp_server(
    {
        "name": "aden-tools",
        "transport": "stdio",
        "command": sys.executable,
        "args": [_MCP_SERVER_PATH, "--stdio"],
        "description": "Aden tools MCP server (GitHub, web search, email, etc.)",
    }
)
logger.info("Registered %d tools from MCP server", _mcp_tool_count)


# ---- Demo-specific tools (context management for large data) ----
# Agents use these to write large intermediate results to disk and pass
# filenames between nodes, keeping the LLM conversation context small.

_DATA_DIR = STORE_DIR / "data"


def load_campaign_template() -> dict:
    """Load the outreach campaign email template with placeholders."""
    return {
        "template": (
            "Subject: {project_name} - Collaboration Opportunity\n\n"
            "Hi {name},\n\n"
            "I noticed your work on {user_repo_highlights} and thought "
            "you might be interested in {project_name}. "
            "{personalized_hook}\n\n"
            "We'd love to have you involved. "
            "Would you be open to a quick chat?\n\n"
            "Best,\nThe {project_name} Team"
        ),
    }


def save_data(filename: str, data: str) -> dict:
    """Save data to a file for later retrieval by this or downstream nodes.

    Use this to store large results (user lists, profiles, scores, emails)
    instead of passing them inline through set_output. Returns a brief
    summary with the filename to reference in set_output calls.

    Args:
        filename: Simple filename like 'github_users.json'. No paths or '..'.
        data: The string data to write (typically JSON).
    """
    if not filename or ".." in filename or "/" in filename:
        return {"error": "Invalid filename. Use simple names like 'users.json'"}
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _DATA_DIR / filename
    path.write_text(data, encoding="utf-8")
    lines = data.count("\n") + 1
    return {
        "success": True,
        "filename": filename,
        "size_bytes": len(data.encode("utf-8")),
        "lines": lines,
        "preview": data[:200] + ("..." if len(data) > 200 else ""),
    }


def load_data(filename: str, offset: int = 0, limit: int = 50) -> dict:
    """Load data from a previously saved file with pagination.

    Always returns a page of lines with metadata about the full file,
    so you know the shape of the data without loading it all into context.

    Args:
        filename: The filename that was used with save_data.
        offset: 0-based line number to start reading from. Default 0.
        limit: Max number of lines to return. Default 50.

    Examples:
        load_data('users.json')                     # first 50 lines
        load_data('users.json', offset=50, limit=50) # next 50 lines
        load_data('users.json', limit=200)           # first 200 lines
    """
    if not filename or ".." in filename or "/" in filename:
        return {"error": "Invalid filename"}
    offset = int(offset)
    limit = int(limit)
    path = _DATA_DIR / filename
    if not path.exists():
        return {"error": f"File not found: {filename}"}
    content = path.read_text(encoding="utf-8")
    size_bytes = len(content.encode("utf-8"))

    # If content is a single long line, try to pretty-print JSON so
    # line-based pagination actually works.  Handles spillover files
    # written before the pretty-print fix in _truncate_tool_result().
    all_lines = content.split("\n")
    if len(all_lines) <= 2 and size_bytes > 500:
        try:
            parsed = json.loads(content)
            content = json.dumps(parsed, indent=2, ensure_ascii=False)
            all_lines = content.split("\n")
        except (json.JSONDecodeError, TypeError, ValueError):
            pass  # Not JSON — keep original lines

    total = len(all_lines)

    start = min(offset, total)
    end = min(start + limit, total)
    sliced = all_lines[start:end]

    return {
        "success": True,
        "filename": filename,
        "content": "\n".join(sliced),
        "total_lines": total,
        "size_bytes": size_bytes,
        "offset": start,
        "lines_returned": len(sliced),
        "has_more": end < total,
    }


def list_data_files() -> dict:
    """List all data files saved during this pipeline run.

    Use this to discover what intermediate results are available
    from previous nodes in the pipeline.
    """
    if not _DATA_DIR.exists():
        return {"files": []}
    files = []
    for f in sorted(_DATA_DIR.iterdir()):
        if f.is_file():
            files.append(
                {
                    "filename": f.name,
                    "size_bytes": f.stat().st_size,
                }
            )
    return {"files": files}


TOOL_REGISTRY.register_function(load_campaign_template)
TOOL_REGISTRY.register_function(save_data)
TOOL_REGISTRY.register_function(load_data)
TOOL_REGISTRY.register_function(list_data_files)

logger.info("Tools registered: %s", ", ".join(TOOL_REGISTRY.get_registered_names()))


# =========================================================================
# Node Specifications
# =========================================================================

NODE_SPECS = {
    "intake": NodeSpec(
        id="intake",
        name="Intake",
        description="Gather repo URL, project URL, and scan configuration from the operator",
        node_type="event_loop",
        client_facing=True,
        input_keys=[],
        output_keys=["repo_url", "project_url", "scan_config", "min_leads"],
        system_prompt=(
            "You are the Intake agent for a GitHub outreach pipeline. "
            "Your job is to collect four pieces of information from the operator:\n\n"
            "1. **repo_url** — The GitHub repository URL to scan for potential contacts "
            "(e.g., https://github.com/anthropics/claude-code)\n"
            "2. **project_url** — The project URL we're promoting "
            "(e.g., https://github.com/our-org/our-project)\n"
            "3. **scan_config** — Scan parameters as a brief description "
            "(e.g., 'stargazers and contributors, last 6 months')\n"
            "4. **min_leads** — Minimum number of leads to collect (a number). "
            "Ask the operator: 'How many leads do you need at minimum?' "
            "If they say something vague like 'as many as possible', default to 50.\n\n"
            "CRITICAL: Once you have all four, you MUST call the set_output tool for EACH "
            "key. Call set_output(key='repo_url', value='...'), then "
            "set_output(key='project_url', value='...'), etc. for all four keys.\n"
            "Do NOT just say 'ready to proceed' or 'handing off' — the pipeline ONLY "
            "advances when you make actual set_output tool calls.\n"
            "For min_leads, set it as a plain number string (e.g., '100').\n"
            "Be conversational but efficient. Ask for missing information if the operator "
            "doesn't provide everything at once."
        ),
    ),
    "scanner": NodeSpec(
        id="scanner",
        name="Scanner",
        description="Scan a GitHub repository to find contributors, issue authors, and stargazers",
        node_type="event_loop",
        input_keys=["repo_url", "scan_config"],
        output_keys=["github_users"],
        tools=[
            "github_get_repo",
            "github_list_issues",
            "github_list_pull_requests",
            "github_list_stargazers",
            "execute_command_tool",
            "save_data",
            "load_data",
            "list_data_files",
        ],
        system_prompt=(
            "You are a GitHub Scanner agent. You receive a repository URL and scan config.\n\n"
            "Parse the repository URL to extract the owner and repo name.\n"
            "Then use the available GitHub tools to discover users:\n"
            "1. Use github_get_repo to get repo metadata (stars, language, description)\n"
            "2. Use github_list_issues to find issue authors (look at each issue's user.login)\n"
            "3. Use github_list_pull_requests to find PR contributors "
            "(look at each PR's user.login)\n"
            "4. Use github_list_stargazers to find stargazers (each entry has a login field)\n\n"
            "PAGINATION — CRITICAL:\n"
            "Each GitHub list tool returns up to 100 items per page. You MUST paginate:\n"
            "  - Always call with limit=100 for maximum results per page.\n"
            "  - If a page returns 100 items, call again with page=2, page=3, etc.\n"
            "  - Stop when a page returns fewer than 100 items (that's the last page).\n"
            "  - Example: github_list_stargazers(owner, repo, page=1, limit=100)\n"
            "            github_list_stargazers(owner, repo, page=2, limit=100)\n\n"
            "SPILLOVER RECOVERY:\n"
            "Tool results larger than 8KB are truncated. When you see a message like\n"
            "  'saved to tool_xxx.txt — Use load_data(filename) to read the full result'\n"
            "you MUST call load_data(filename) to retrieve the full data. The truncated\n"
            "preview only shows a fraction of the users. Use load_data with offset/limit\n"
            "to page through the file: load_data(filename, offset=0, limit=50), then\n"
            "offset=50, offset=100, etc. until has_more is false.\n\n"
            "USER COLLECTION:\n"
            "Collect unique usernames from all sources. Classify each user:\n"
            "- 'contributor' if they authored a pull request\n"
            "- 'issue_author' if they authored an issue\n"
            "- 'stargazer' if they starred the repo\n"
            "If a user appears in multiple categories, use the highest-value type "
            "(contributor > issue_author > stargazer).\n\n"
            "Respect the scan_config for any limits or filtering preferences.\n\n"
            "SHELL TOOL:\n"
            "You have execute_command_tool for running shell commands. Use it for file "
            "management tasks like merging JSON files, deduplicating data, or processing "
            "saved data with jq/python one-liners. Example:\n"
            "  execute_command_tool(command='cat data/file.json | python3 -c \"import sys,json; "
            "d=json.load(sys.stdin); print(len(d))\"')\n\n"
            "CONTEXT MANAGEMENT:\n"
            "Format the result as a JSON array of objects with 'username' and 'user_type'.\n"
            "Use save_data('github_users.json', <json_string>) to write the list to a file.\n"
            "Then call set_output(key='github_users', value='github_users.json')\n"
            "This passes a filename — not the raw data — to downstream nodes, "
            "keeping the conversation context small."
        ),
    ),
    "profiler": NodeSpec(
        id="profiler",
        name="Profiler",
        description="Fetch detailed profiles for each discovered user",
        node_type="event_loop",
        input_keys=["github_users"],
        output_keys=["user_profiles"],
        tools=[
            "github_get_user_profile",
            "github_list_repos",
            "execute_command_tool",
            "load_data",
            "save_data",
        ],
        system_prompt=(
            "You are a GitHub Profiler agent. Your input 'github_users' is a filename.\n\n"
            "WORKFLOW:\n"
            "1. Use load_data to read the user list from the input filename\n"
            "2. For each user, call github_get_user_profile to get their profile, and "
            "github_list_repos(username=<username>) to list their public repos\n"
            "3. Compile profiles into a JSON array with: username, name, bio, company, "
            "languages (from repos)\n"
            "4. Use save_data('user_profiles.json', <json>) to write results to a file\n"
            "5. Call set_output(key='user_profiles', value='user_profiles.json')\n\n"
            "SHELL TOOL:\n"
            "You have execute_command_tool for running shell commands. Use it for file "
            "management tasks like filtering JSON, extracting fields, or merging data. "
            "Example: execute_command_tool(command='python3 -c \"import json; ...')\n\n"
            "CONTEXT MANAGEMENT:\n"
            "Start by loading the user list file. For large lists, use load_data with "
            "offset and limit to page through users in batches "
            "(e.g. load_data('github_users.json', offset=0, limit=20), then offset=20, etc.). "
            "When done, save all profiles to a file and pass the filename — not the raw data."
        ),
    ),
    "scorer": NodeSpec(
        id="scorer",
        name="Scorer",
        description="Score each user's relevance to our project",
        node_type="event_loop",
        input_keys=["github_users", "project_url"],
        output_keys=["relevance_scores"],
        tools=["load_data", "save_data"],
        system_prompt=(
            "You are a Relevance Scorer agent. Your input 'github_users' is a filename "
            "and 'project_url' is a URL string.\n\n"
            "WORKFLOW:\n"
            "1. Use load_data to read the user list from the github_users filename\n"
            "2. For each user, assess relevance to the project based on:\n"
            "   - Their user_type (contributor > issue_author > stargazer)\n"
            "   - Assumed technical overlap with the project\n"
            "3. Output a JSON array of objects with: username, score (0.0-1.0), reasoning\n"
            "4. Use save_data('relevance_scores.json', <json>) to write results\n"
            "5. Call set_output(key='relevance_scores', value='relevance_scores.json')\n\n"
            "Score generously — this is a demo."
        ),
    ),
    "extractor": NodeSpec(
        id="extractor",
        name="Extractor",
        description="Build a curated contact list from profiles and scores",
        node_type="event_loop",
        input_keys=["user_profiles", "relevance_scores"],
        output_keys=["contact_list"],
        tools=[
            "github_get_user_emails",
            "web_search",
            "web_scrape",
            "execute_command_tool",
            "load_data",
            "save_data",
        ],
        max_node_visits=3,
        system_prompt=(
            "You are a Contact Extractor agent. Your inputs 'user_profiles' and "
            "'relevance_scores' are filenames pointing to JSON data files.\n\n"
            "WORKFLOW:\n"
            "1. Use load_data to read both files (profiles and scores). For large files, "
            "use offset and limit to page through them incrementally "
            "(e.g. load_data('file.json', offset=0, limit=30))\n"
            "2. For each user with relevance score >= 0.3, enrich their contact info:\n"
            "   - Use github_get_user_emails(username) to find emails from their "
            "public commits and profile (this is the BEST source for GitHub emails)\n"
            "   - If no email found, try web_search ('{username} github email')\n"
            "   - If results include personal sites, use web_scrape to extract details\n"
            "   - Look for: email addresses, Twitter/X handles, LinkedIn profiles\n"
            "3. Compile a JSON array of contacts with: username, name, email, twitter, "
            "relevance_score\n"
            "4. Use save_data('contact_list.json', <json>) to write results\n"
            "5. Call set_output(key='contact_list', value='contact_list.json')\n\n"
            "SHELL TOOL:\n"
            "You have execute_command_tool for running shell commands. Use it for file "
            "management tasks like merging profiles and scores, deduplicating contacts, "
            "or batch-processing data. Example:\n"
            "  execute_command_tool(command='python3 -c \"import json; profiles=json.load("
            'open(\\"data/user_profiles.json\\")); print(len(profiles))"\')\n\n'
            "Include all users who have at least one contact method."
        ),
    ),
    "review": NodeSpec(
        id="review",
        name="Review",
        description="Human operator reviews and approves the contact list",
        node_type="event_loop",
        client_facing=True,
        input_keys=["contact_list"],
        output_keys=["approved_contacts", "redo_extraction"],
        nullable_output_keys=["approved_contacts", "redo_extraction"],
        max_node_visits=3,
        tools=["load_data", "save_data"],
        system_prompt=(
            "You are the Review agent at a human checkpoint. Your input 'contact_list' "
            "is a filename pointing to a JSON data file.\n\n"
            "WORKFLOW:\n"
            "1. Use load_data to read the contact list from the file\n"
            "2. Present the contacts to the operator in a clear, readable format\n"
            "   Show each contact with: name, username, email, twitter, relevance score\n"
            "3. Ask the operator to either approve or request a redo\n"
            "4. Based on the operator's response, call set_output EXACTLY ONCE:\n\n"
            "   IF APPROVED: save the approved list with save_data, then call:\n"
            "     set_output(key='approved_contacts', value='approved_contacts.json')\n\n"
            "   IF REDO REQUESTED: call:\n"
            "     set_output(key='redo_extraction', value='true')\n\n"
            "CRITICAL RULE: Call set_output EXACTLY ONCE with EXACTLY ONE key.\n"
            "NEVER call set_output twice. NEVER set both keys.\n"
            "The two output keys are mutually exclusive — setting both will cause an error."
        ),
    ),
    "campaign_builder": NodeSpec(
        id="campaign_builder",
        name="Campaign Builder",
        description="Iteratively build personalized outreach emails in batches",
        node_type="event_loop",
        client_facing=True,
        input_keys=["approved_contacts", "project_url"],
        output_keys=["draft_emails"],
        nullable_output_keys=["draft_emails"],
        tools=["load_campaign_template", "load_data", "save_data"],
        max_node_visits=5,
        system_prompt=(
            "You are the Campaign Builder agent. Your input 'approved_contacts' is a "
            "filename and 'project_url' is a URL string.\n\n"
            "ITERATIVE BATCH WORKFLOW:\n"
            "You build draft emails in batches of up to 10 contacts at a time, "
            "presenting each batch to the operator for review before continuing.\n\n"
            "STEP 1 — SETUP:\n"
            "- Use load_data to read the approved contacts from the file\n"
            "- Load the campaign template using load_campaign_template\n"
            "- Count total contacts and plan batches of up to 10\n\n"
            "STEP 2 — DRAFT A BATCH (max 10 emails):\n"
            "- For each contact in the current batch, write a personalized email:\n"
            "  * Fill in their name and relevant details from their profile\n"
            "  * Add a personalized hook based on their interests/contributions\n"
            "  * Format: {recipient, subject, body}\n"
            "- Present the drafted emails to the operator clearly, showing:\n"
            "  * Batch number (e.g. 'Batch 1 of 4')\n"
            "  * Each email with recipient, subject, and body preview\n"
            "  * How many contacts remain\n\n"
            "STEP 3 — ASK THE OPERATOR:\n"
            "After presenting each batch, ask:\n"
            "  'Create more drafts for the next batch, or submit all drafts "
            "for outbound email?'\n\n"
            "  IF 'create more' → go back to STEP 2 for the next batch of contacts\n"
            "  IF 'submit' → go to STEP 4\n\n"
            "STEP 4 — FINALIZE:\n"
            "- Combine ALL drafted batches into a single JSON array\n"
            "- Use save_data('draft_emails.json', <json>) to write them\n"
            "- Call set_output(key='draft_emails', value='draft_emails.json')\n\n"
            "RULES:\n"
            "- Never draft more than 10 emails at once — always pause for operator input\n"
            "- Keep a running total of emails drafted across batches\n"
            "- Make each email feel personal and relevant\n"
            "- Do NOT call set_output until the operator says to submit"
        ),
    ),
    "approval": NodeSpec(
        id="approval",
        name="Approval",
        description="Human operator reviews and approves campaign emails",
        node_type="event_loop",
        client_facing=True,
        input_keys=["draft_emails"],
        output_keys=["approved_emails", "revise_campaigns"],
        nullable_output_keys=["approved_emails", "revise_campaigns"],
        max_node_visits=3,
        tools=["load_data", "save_data"],
        system_prompt=(
            "You are the Approval agent at the final human checkpoint. Your input "
            "'draft_emails' is a filename pointing to a JSON data file.\n\n"
            "WORKFLOW:\n"
            "1. Use load_data to read the draft emails from the file\n"
            "2. Present each email to the operator with: recipient, subject, and body\n"
            "3. Ask the operator to either approve or request revision\n"
            "4. Based on the operator's response, call set_output EXACTLY ONCE:\n\n"
            "   IF APPROVED: save the approved list with save_data, then call:\n"
            "     set_output(key='approved_emails', value='approved_emails.json')\n\n"
            "   IF REVISION REQUESTED: call:\n"
            "     set_output(key='revise_campaigns', value='true')\n\n"
            "CRITICAL RULE: Call set_output EXACTLY ONCE with EXACTLY ONE key.\n"
            "NEVER call set_output twice. NEVER set both keys.\n"
            "The two output keys are mutually exclusive — setting both will cause an error."
        ),
    ),
    "sender": NodeSpec(
        id="sender",
        name="Sender",
        description="Send approved campaign emails",
        node_type="event_loop",
        input_keys=["approved_emails"],
        output_keys=["send_results"],
    ),
}


# =========================================================================
# Edge + Graph Definitions
# =========================================================================

EDGES = [
    EdgeSpec(
        id="intake_to_scanner",
        source="intake",
        target="scanner",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    # Fan-out: scanner → profiler AND scorer (both ON_SUCCESS)
    EdgeSpec(
        id="scanner_to_profiler",
        source="scanner",
        target="profiler",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    EdgeSpec(
        id="scanner_to_scorer",
        source="scanner",
        target="scorer",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    # Fan-in: profiler → extractor AND scorer → extractor
    EdgeSpec(
        id="profiler_to_extractor",
        source="profiler",
        target="extractor",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    EdgeSpec(
        id="scorer_to_extractor",
        source="scorer",
        target="extractor",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    # Extractor → Review
    EdgeSpec(
        id="extractor_to_review",
        source="extractor",
        target="review",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    # Review: forward to campaign_builder OR feedback to extractor
    EdgeSpec(
        id="review_to_campaign",
        source="review",
        target="campaign_builder",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="output.get('approved_contacts') is not None",
        priority=1,
    ),
    EdgeSpec(
        id="review_feedback",
        source="review",
        target="extractor",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="output.get('redo_extraction') is not None",
        priority=-1,
    ),
    # Campaign Builder → Approval
    EdgeSpec(
        id="campaign_to_approval",
        source="campaign_builder",
        target="approval",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    # Approval: forward to sender OR feedback to campaign_builder
    EdgeSpec(
        id="approval_to_sender",
        source="approval",
        target="sender",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="output.get('approved_emails') is not None",
        priority=1,
    ),
    EdgeSpec(
        id="approval_feedback",
        source="approval",
        target="campaign_builder",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="output.get('revise_campaigns') is not None",
        priority=-1,
    ),
]

GRAPH = GraphSpec(
    id="github_outreach_pipeline",
    goal_id="outreach_goal",
    name="GitHub Outreach Pipeline",
    entry_node="intake",
    nodes=list(NODE_SPECS.values()),
    edges=EDGES,
    terminal_nodes=["sender"],
    max_steps=30,
    max_tokens=64000,
)

GOAL = Goal(
    id="outreach_goal",
    name="GitHub Outreach Campaign",
    description=(
        "Scan a GitHub repository to identify potential collaborators, "
        "profile and score them, build a curated contact list, "
        "create personalized outreach emails, and send approved campaigns."
    ),
)


# =========================================================================
# Sender Function (terminal node)
# =========================================================================


def _send_email_via_resend(
    to: str,
    subject: str,
    html: str,
    from_email: str,
) -> dict:
    """Send a single email via the Resend REST API."""
    api_key = CREDENTIALS.get("resend") or os.getenv("RESEND_API_KEY")
    if not api_key:
        return {"error": "Resend API key not configured"}

    # Testing override: redirect all recipients to a single address
    override_to = os.getenv("EMAIL_OVERRIDE_TO")
    if override_to:
        subject = f"[TEST -> {to}] {subject}"
        to = override_to

    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": from_email,
                "to": [to] if isinstance(to, str) else to,
                "subject": subject,
                "html": html,
            },
            timeout=30.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "success": True,
                "id": data.get("id", ""),
            }
        return {
            "error": (f"Resend API ({resp.status_code}): {resp.text[:200]}"),
        }
    except httpx.TimeoutException:
        return {"error": "Email send timed out"}
    except httpx.RequestError as e:
        return {"error": f"Network error: {e}"}


class SenderNode(NodeProtocol):
    """Node wrapper for send_emails function."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        approved = ctx.input_data.get("approved_emails", "")
        result_str = send_emails(approved_emails=approved)
        ctx.memory.write("send_results", result_str)
        return NodeResult(success=True, output={"send_results": result_str})


def send_emails(approved_emails: str = "") -> str:
    """Send approved campaign emails via Resend, or log if unconfigured.

    Returns a JSON string.
    """
    approved = approved_emails
    if not approved:
        return json.dumps({"error": "No approved emails to send"})

    # Load from file if the value is a filename (file-ops pattern)
    if isinstance(approved, str) and not approved.strip().startswith("["):
        data_path = _DATA_DIR / approved
        if data_path.exists():
            approved = data_path.read_text(encoding="utf-8")

    try:
        emails = json.loads(approved) if isinstance(approved, str) else approved
    except (json.JSONDecodeError, TypeError):
        emails = [{"recipient": "unknown", "status": "parse_error"}]

    from_email = os.getenv("EMAIL_FROM", "noreply@example.com")
    has_resend = bool(CREDENTIALS.get("resend") or os.getenv("RESEND_API_KEY"))

    results = []
    for email in emails:
        recipient = email.get("recipient", "unknown")
        subject = email.get("subject", "")
        body = email.get("body", "")
        html_body = "<div style='font-family:sans-serif;'>" + body.replace("\n", "<br>") + "</div>"

        if has_resend:
            result = _send_email_via_resend(
                to=recipient,
                subject=subject,
                html=html_body,
                from_email=from_email,
            )
            sent_ok = result.get("success", False)
            status = "sent" if sent_ok else "failed"
            msg_id = result.get("id", "")
            error = result.get("error", "")
        else:
            status = "logged"
            msg_id = f"mock_{len(results) + 1:03d}"
            error = ""
            logger.info(
                "(mock) Would send to %s: %s",
                recipient,
                subject,
            )

        results.append(
            {
                "recipient": recipient,
                "subject": subject,
                "status": status,
                "message_id": msg_id,
                "error": error,
            }
        )
        if status == "sent":
            logger.info(
                "Sent to %s: %s",
                recipient,
                subject,
            )

    return json.dumps(results)


# =========================================================================
# Judges (SchemaJudge for output validation)
# =========================================================================


class SchemaJudge:
    """Judge that validates event loop output against a Pydantic model.

    For internal (non-client-facing) nodes:
    1. Check if required output keys are set
    2. Validate accumulated values against Pydantic model
    3. Optionally load referenced files and check minimum item counts
    4. RETRY with structural feedback on validation failure
    5. ACCEPT on valid output
    """

    def __init__(
        self,
        output_model: type[BaseModel],
        min_items: dict[str, int | Callable[[], int]] | None = None,
        data_dir: Path | None = None,
    ):
        self._model = output_model
        self._min_items = min_items or {}
        self._data_dir = data_dir

    async def evaluate(self, context: dict) -> JudgeVerdict:
        accumulator = context.get("output_accumulator", {})
        missing = context.get("missing_keys", [])

        if missing:
            return JudgeVerdict(
                action="RETRY",
                feedback=f"Missing output keys: {missing}. Use set_output to provide them.",
            )

        # Try to validate against schema
        try:
            parsed = {}
            for key, value in accumulator.items():
                if value is None:
                    continue
                if isinstance(value, str):
                    stripped = value.strip()
                    if stripped and stripped[0] in ("{", "["):
                        try:
                            parsed[key] = json.loads(value)
                        except json.JSONDecodeError:
                            parsed[key] = value
                    else:
                        parsed[key] = value
                else:
                    parsed[key] = value
            self._model.model_validate(parsed)
        except ValidationError as e:
            errors = "; ".join(
                f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()
            )
            return JudgeVerdict(
                action="RETRY",
                feedback=f"Output schema validation failed: {errors}. Fix and re-set outputs.",
            )

        # Check minimum item counts for file-based outputs
        for key, min_count_or_fn in self._min_items.items():
            min_count = min_count_or_fn() if callable(min_count_or_fn) else min_count_or_fn
            value = accumulator.get(key)
            if not value or not self._data_dir:
                continue
            fpath = self._data_dir / value
            if not fpath.exists():
                return JudgeVerdict(
                    action="RETRY",
                    feedback=f"Output file '{value}' not found. Use save_data to create it.",
                )
            try:
                content = fpath.read_text(encoding="utf-8")
                data = json.loads(content)
                if isinstance(data, list) and len(data) < min_count:
                    return JudgeVerdict(
                        action="RETRY",
                        feedback=(
                            f"Insufficient results: '{value}' contains {len(data)} items "
                            f"but at least {min_count} are required. "
                            f"Use pagination (page=1, page=2, ...) on the GitHub tools "
                            f"and load_data on spillover files to collect more users."
                        ),
                    )
            except (json.JSONDecodeError, OSError):
                pass  # File exists but can't be parsed — let it through

        return JudgeVerdict(action="ACCEPT")


# =========================================================================
# HTML Page (embedded)
# =========================================================================

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GitHub Outreach Pipeline</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'SF Mono', 'Fira Code', monospace;
    background: #0d1117; color: #c9d1d9;
    height: 100vh; display: flex; flex-direction: column;
  }
  header {
    background: #161b22; padding: 10px 20px;
    border-bottom: 1px solid #30363d;
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  }
  header h1 { font-size: 14px; color: #58a6ff; font-weight: 600; }
  .badge {
    font-size: 10px; padding: 2px 7px; border-radius: 10px;
    background: #21262d; color: #484f58;
  }
  .badge.active { font-weight: 600; background: #1a3a5c; color: #58a6ff; }
  .badge.done { background: #1a4b2e; color: #3fb950; }
  .badge.waiting { background: #1c1c1c; color: #6e7681; }
  .badge.client { border: 1px solid #58a6ff33; }
  .main { flex: 1; display: flex; overflow: hidden; }
  .chat {
    flex: 65; overflow-y: auto; padding: 12px; min-width: 0;
    border-right: 1px solid #30363d;
  }
  .graph-panel {
    flex: 35; display: flex; flex-direction: column;
    padding: 12px; min-width: 260px; background: #0d1117;
  }
  .graph-title {
    font-size: 11px; color: #8b949e; font-weight: 600;
    margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px;
  }
  .graph-svg { flex: 1; width: 100%; }
  .graph-legend {
    font-size: 9px; color: #484f58; margin-top: 6px; line-height: 1.8;
  }
  .legend-dot {
    display: inline-block; width: 7px; height: 7px;
    border-radius: 50%; margin-right: 3px; vertical-align: middle;
  }
  .msg {
    margin: 3px 0; padding: 7px 10px; border-radius: 5px;
    line-height: 1.5; white-space: pre-wrap; word-wrap: break-word;
    font-size: 12px; border-left: 3px solid transparent;
  }
  .msg.user { background: #1a3a5c; color: #58a6ff; border-left-color: #58a6ff; }
  .msg.assistant { background: #161b22; color: #c9d1d9; }
  .msg.event {
    background: transparent; color: #8b949e; font-size: 10px;
    padding: 2px 10px;
  }
  .msg.event.tool { border-left-color: #d29922; }
  .msg.event.done { color: #3fb950; }
  .msg.event.feedback { border-left-color: #f85149; color: #f85149; }
  .msg .node-tag {
    font-size: 9px; font-weight: 700; margin-right: 5px;
    text-transform: uppercase; letter-spacing: 0.5px;
  }
  /* Node colors */
  .node-intake .node-tag { color: #58a6ff; }
  .node-scanner .node-tag { color: #d29922; }
  .node-profiler .node-tag { color: #bc8cff; }
  .node-scorer .node-tag { color: #bc8cff; }
  .node-extractor .node-tag { color: #d29922; }
  .node-review .node-tag { color: #58a6ff; }
  .node-campaign_builder .node-tag { color: #58a6ff; }
  .node-approval .node-tag { color: #58a6ff; }
  .node-sender .node-tag { color: #3fb950; }
  .result-banner {
    margin: 12px 0; padding: 14px; border-radius: 8px;
    background: #0a2614; border: 1px solid #3fb950;
  }
  .result-banner h3 {
    color: #3fb950; font-size: 12px; margin-bottom: 8px; text-align: center;
  }
  .result-banner .report {
    color: #c9d1d9; font-size: 11px; line-height: 1.5;
    max-height: 300px; overflow-y: auto; white-space: pre-wrap;
  }
  .result-banner .tokens {
    color: #484f58; font-size: 9px; text-align: center; margin-top: 6px;
  }
  .input-bar {
    padding: 10px 16px; background: #161b22;
    border-top: 1px solid #30363d; display: flex; gap: 8px;
  }
  .input-bar input {
    flex: 1; background: #0d1117; border: 1px solid #30363d;
    color: #c9d1d9; padding: 8px 12px; border-radius: 6px;
    font-family: inherit; font-size: 12px; outline: none;
  }
  .input-bar input:focus { border-color: #58a6ff; }
  .input-bar input:disabled { color: #484f58; }
  .input-bar button {
    background: #238636; color: #fff; border: none;
    padding: 8px 16px; border-radius: 6px; cursor: pointer;
    font-family: inherit; font-weight: 600; font-size: 12px;
  }
  .input-bar button:hover { background: #2ea043; }
  .input-bar button:disabled {
    background: #21262d; color: #484f58; cursor: not-allowed;
  }
  #status-text {
    font-size: 10px; color: #8b949e; margin-left: auto;
  }
  /* SVG graph styles */
  .graph-node rect { transition: stroke-width 0.2s, stroke 0.2s; }
  .graph-node.active rect { stroke-width: 3; stroke: #58a6ff; }
  .graph-node.done rect { stroke-width: 2; stroke: #3fb950; }
  @keyframes waitingDash { to { stroke-dashoffset: -24; } }
  .graph-node.waiting rect {
    stroke: #484f58; stroke-width: 2;
    stroke-dasharray: 8 4;
    animation: waitingDash 1.2s linear infinite;
  }
  @keyframes edgePulse {
    0% { stroke-opacity: 1; stroke-width: 3; }
    100% { stroke-opacity: 0.3; stroke-width: 1.5; }
  }
  svg line.flash, svg path.flash {
    stroke: #58a6ff !important;
    animation: edgePulse 0.8s ease-out forwards;
  }
  /* Badge spinner animations */
  .badge.waiting::before {
    content: ''; display: inline-block;
    width: 8px; height: 8px;
    border: 1.5px solid #30363d; border-top-color: #6e7681;
    border-radius: 50%; vertical-align: middle; margin-right: 4px;
    animation: badgeSpin 0.7s linear infinite;
  }
  @keyframes badgeSpin { to { transform: rotate(360deg); } }
  .badge.active::before {
    content: ''; display: inline-block;
    width: 6px; height: 6px; background: #58a6ff;
    border-radius: 50%; vertical-align: middle; margin-right: 4px;
    animation: badgePulse 1s ease-in-out infinite;
  }
  @keyframes badgePulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.8); }
  }
  /* Activity cards for internal nodes */
  .activity-card {
    margin: 4px 0; padding: 6px 12px; border-radius: 6px;
    font-size: 11px; display: flex; align-items: center; gap: 8px;
    background: #161b22; border-left: 3px solid #30363d;
    transition: opacity 0.3s, border-color 0.3s;
  }
  .activity-card.active { border-left-color: #58a6ff; }
  .activity-card.done { border-left-color: #3fb950; opacity: 0.7; }
  .activity-card .card-label {
    font-weight: 700; font-size: 9px; letter-spacing: 0.5px;
    min-width: 70px;
  }
  .activity-card .card-action { flex: 1; color: #8b949e; }
  .activity-card .card-time {
    color: #484f58; font-size: 10px; min-width: 30px; text-align: right;
  }
  .activity-card.node-scanner .card-label { color: #d29922; }
  .activity-card.node-profiler .card-label { color: #bc8cff; }
  .activity-card.node-scorer .card-label { color: #bc8cff; }
  .activity-card.node-extractor .card-label { color: #d29922; }
  .activity-card.node-campaign_builder .card-label { color: #58a6ff; }
</style>
</head>
<body>
  <header>
    <h1>GitHub Outreach Pipeline</h1>
    <span id="badge-intake" class="badge client">Intake</span>
    <span id="badge-scanner" class="badge">Scanner</span>
    <span id="badge-profiler" class="badge">Profiler</span>
    <span id="badge-scorer" class="badge">Scorer</span>
    <span id="badge-extractor" class="badge">Extractor</span>
    <span id="badge-review" class="badge client">Review</span>
    <span id="badge-campaign_builder" class="badge">Campaign</span>
    <span id="badge-approval" class="badge client">Approval</span>
    <span id="badge-sender" class="badge">Sender</span>
    <span id="status-text">Ready</span>
    <span id="progress-info" style="font-size:10px;color:#484f58;margin-left:4px"></span>
  </header>

  <div class="main">
    <div id="chat" class="chat"></div>
    <div class="graph-panel">
      <div class="graph-title">Pipeline Graph</div>
      <svg class="graph-svg" viewBox="0 0 340 640" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <marker id="arrow" markerWidth="7" markerHeight="5" refX="6" refY="2.5" orient="auto">
            <polygon points="0 0, 7 2.5, 0 5" fill="#484f58"/>
          </marker>
          <marker id="arrow-red" markerWidth="7" markerHeight="5" refX="6" refY="2.5" orient="auto">
            <polygon points="0 0, 7 2.5, 0 5" fill="#f85149"/>
          </marker>
        </defs>

        <!-- Forward edges -->
        <line id="edge-intake-scanner" x1="170" y1="42" x2="170" y2="68" stroke="#30363d" stroke-width="1.2" marker-end="url(#arrow)"/>
        <line id="edge-scanner-profiler" x1="135" y1="102" x2="85" y2="128" stroke="#30363d" stroke-width="1.2" marker-end="url(#arrow)"/>
        <line id="edge-scanner-scorer" x1="205" y1="102" x2="255" y2="128" stroke="#30363d" stroke-width="1.2" marker-end="url(#arrow)"/>
        <line id="edge-profiler-extractor" x1="85" y1="162" x2="135" y2="188" stroke="#30363d" stroke-width="1.2" marker-end="url(#arrow)"/>
        <line id="edge-scorer-extractor" x1="255" y1="162" x2="205" y2="188" stroke="#30363d" stroke-width="1.2" marker-end="url(#arrow)"/>
        <line id="edge-extractor-review" x1="170" y1="222" x2="170" y2="248" stroke="#30363d" stroke-width="1.2" marker-end="url(#arrow)"/>
        <line id="edge-review-campaign_builder" x1="170" y1="282" x2="170" y2="368" stroke="#30363d" stroke-width="1.2" marker-end="url(#arrow)"/>
        <line id="edge-campaign_builder-approval" x1="170" y1="402" x2="170" y2="428" stroke="#30363d" stroke-width="1.2" marker-end="url(#arrow)"/>
        <line id="edge-approval-sender" x1="170" y1="462" x2="170" y2="548" stroke="#30363d" stroke-width="1.2" marker-end="url(#arrow)"/>

        <!-- Feedback edges (curved, red dashed) -->
        <path id="edge-review-feedback" d="M 130 270 Q 40 330 130 200" stroke="#f8514966" stroke-width="1" fill="none" stroke-dasharray="4 3" marker-end="url(#arrow-red)"/>
        <path id="edge-approval-feedback" d="M 130 450 Q 40 510 130 380" stroke="#f8514966" stroke-width="1" fill="none" stroke-dasharray="4 3" marker-end="url(#arrow-red)"/>

        <!-- Nodes -->
        <g id="gnode-intake" class="graph-node">
          <rect x="110" y="10" width="120" height="32" rx="6" fill="#161b22" stroke="#58a6ff" stroke-width="1.5"/>
          <text x="170" y="31" fill="#58a6ff" text-anchor="middle" font-size="11" font-weight="600" font-family="SF Mono,monospace">Intake</text>
        </g>
        <g id="gnode-scanner" class="graph-node">
          <rect x="110" y="70" width="120" height="32" rx="6" fill="#161b22" stroke="#30363d" stroke-width="1.5"/>
          <text x="170" y="91" fill="#d29922" text-anchor="middle" font-size="11" font-weight="600" font-family="SF Mono,monospace">Scanner</text>
        </g>
        <g id="gnode-profiler" class="graph-node">
          <rect x="20" y="130" width="110" height="32" rx="6" fill="#161b22" stroke="#30363d" stroke-width="1.5"/>
          <text x="75" y="151" fill="#bc8cff" text-anchor="middle" font-size="10" font-weight="600" font-family="SF Mono,monospace">Profiler</text>
        </g>
        <g id="gnode-scorer" class="graph-node">
          <rect x="210" y="130" width="110" height="32" rx="6" fill="#161b22" stroke="#30363d" stroke-width="1.5"/>
          <text x="265" y="151" fill="#bc8cff" text-anchor="middle" font-size="10" font-weight="600" font-family="SF Mono,monospace">Scorer</text>
        </g>
        <g id="gnode-extractor" class="graph-node">
          <rect x="110" y="190" width="120" height="32" rx="6" fill="#161b22" stroke="#30363d" stroke-width="1.5"/>
          <text x="170" y="211" fill="#d29922" text-anchor="middle" font-size="11" font-weight="600" font-family="SF Mono,monospace">Extractor</text>
        </g>
        <g id="gnode-review" class="graph-node">
          <rect x="110" y="250" width="120" height="32" rx="6" fill="#161b22" stroke="#58a6ff" stroke-width="1.5"/>
          <text x="170" y="271" fill="#58a6ff" text-anchor="middle" font-size="11" font-weight="600" font-family="SF Mono,monospace">Review</text>
        </g>
        <g id="gnode-campaign_builder" class="graph-node">
          <rect x="100" y="370" width="140" height="32" rx="6" fill="#161b22" stroke="#30363d" stroke-width="1.5"/>
          <text x="170" y="391" fill="#d29922" text-anchor="middle" font-size="10" font-weight="600" font-family="SF Mono,monospace">Campaign Builder</text>
        </g>
        <g id="gnode-approval" class="graph-node">
          <rect x="110" y="430" width="120" height="32" rx="6" fill="#161b22" stroke="#58a6ff" stroke-width="1.5"/>
          <text x="170" y="451" fill="#58a6ff" text-anchor="middle" font-size="11" font-weight="600" font-family="SF Mono,monospace">Approval</text>
        </g>
        <g id="gnode-sender" class="graph-node">
          <rect x="110" y="550" width="120" height="32" rx="6" fill="#161b22" stroke="#3fb950" stroke-width="1.5"/>
          <text x="170" y="571" fill="#3fb950" text-anchor="middle" font-size="11" font-weight="600" font-family="SF Mono,monospace">Sender</text>
        </g>
        <!-- Status text below each node -->
        <text id="status-intake" x="170" y="55" fill="#484f58" text-anchor="middle"
              font-size="8" font-family="SF Mono,monospace"></text>
        <text id="status-scanner" x="170" y="113" fill="#484f58" text-anchor="middle"
              font-size="8" font-family="SF Mono,monospace"></text>
        <text id="status-profiler" x="75" y="173" fill="#484f58" text-anchor="middle"
              font-size="8" font-family="SF Mono,monospace"></text>
        <text id="status-scorer" x="265" y="173" fill="#484f58" text-anchor="middle"
              font-size="8" font-family="SF Mono,monospace"></text>
        <text id="status-extractor" x="170" y="233" fill="#484f58" text-anchor="middle"
              font-size="8" font-family="SF Mono,monospace"></text>
        <text id="status-review" x="170" y="295" fill="#484f58" text-anchor="middle"
              font-size="8" font-family="SF Mono,monospace"></text>
        <text id="status-campaign_builder" x="170" y="415" fill="#484f58" text-anchor="middle"
              font-size="8" font-family="SF Mono,monospace"></text>
        <text id="status-approval" x="170" y="475" fill="#484f58" text-anchor="middle"
              font-size="8" font-family="SF Mono,monospace"></text>
        <text id="status-sender" x="170" y="593" fill="#484f58" text-anchor="middle"
              font-size="8" font-family="SF Mono,monospace"></text>
      </svg>
      <div class="graph-legend">
        <span class="legend-dot" style="background:#58a6ff"></span>Client-facing (HITL)
        <span class="legend-dot" style="background:#d29922;margin-left:6px"></span>Internal
        <span class="legend-dot" style="background:#bc8cff;margin-left:6px"></span>Parallel
        <span class="legend-dot" style="background:#3fb950;margin-left:6px"></span>Terminal
      </div>
    </div>
  </div>

  <div class="input-bar">
    <input id="input" type="text"
           placeholder="Tell the Intake agent what repo to scan..." autofocus />
    <button id="send" onclick="sendMsg()">Send</button>
  </div>

<script>
const chat = document.getElementById('chat');
const sendBtn = document.getElementById('send');
const inputEl = document.getElementById('input');
const statusText = document.getElementById('status-text');

const nodeNames = {
  intake: 'Intake', scanner: 'Scanner', profiler: 'Profiler',
  scorer: 'Scorer', extractor: 'Extractor', review: 'Review',
  campaign_builder: 'Campaign', approval: 'Approval', sender: 'Sender'
};
const allNodes = Object.keys(nodeNames);

let ws = null;
let started = false;
let inputEnabled = true;
const assistantEls = {};
const activityCards = {};
const cardTimers = {};
let lastCompletedNode = null;
let pipelineStartTime = null;
let progressInterval = null;
let totalIterations = 0;

const EDGE_MAP = {
  'intake->scanner': 'edge-intake-scanner',
  'scanner->profiler': 'edge-scanner-profiler',
  'scanner->scorer': 'edge-scanner-scorer',
  'profiler->extractor': 'edge-profiler-extractor',
  'scorer->extractor': 'edge-scorer-extractor',
  'extractor->review': 'edge-extractor-review',
  'review->campaign_builder': 'edge-review-campaign_builder',
  'review->extractor': 'edge-review-feedback',
  'campaign_builder->approval': 'edge-campaign_builder-approval',
  'approval->sender': 'edge-approval-sender',
  'approval->campaign_builder': 'edge-approval-feedback',
};

const spinChars = ['\u280b','\u2819','\u2839','\u2838','\u283c',
                   '\u2834','\u2826','\u2827','\u2807','\u280f'];
const spinTimers = {};

inputEl.addEventListener('keydown', e => { if (e.key === 'Enter') sendMsg(); });

function setStatus(text) { statusText.textContent = text; }

function setNodeState(nid, state) {
  const g = document.getElementById('gnode-' + nid);
  const b = document.getElementById('badge-' + nid);
  if (g) { g.classList.remove('active','done','waiting'); if (state) g.classList.add(state); }
  if (b) { b.classList.remove('active','done','waiting'); if (state) b.classList.add(state); }
}

function addMsg(html, cls) {
  const el = document.createElement('div');
  el.className = 'msg ' + cls;
  el.innerHTML = html;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

function addNodeMsg(nid, text, cls) {
  const tag = '<span class="node-tag">' + (nodeNames[nid]||nid) + '</span>';
  const el = addMsg(tag, 'assistant node-' + nid + ' ' + (cls||''));
  const span = document.createElement('span');
  span.className = 'text-content';
  span.textContent = text;
  el.appendChild(span);
  return el;
}

function addEventMsg(nid, text, cls) {
  const prefix = nid ? ('[' + (nodeNames[nid]||nid) + '] ') : '';
  return addMsg(prefix + text, 'event ' + (cls||''));
}

function enableInput(placeholder) {
  inputEnabled = true;
  inputEl.disabled = false;
  sendBtn.disabled = false;
  if (placeholder) inputEl.placeholder = placeholder;
  inputEl.focus();
}

function disableInput(placeholder) {
  inputEnabled = false;
  inputEl.disabled = true;
  sendBtn.disabled = true;
  if (placeholder) inputEl.placeholder = placeholder;
}

// --- SVG status text with braille spinner ---

function setNodeStatus(nid, text) {
  const s = document.getElementById('status-' + nid);
  if (!s) return;
  if (spinTimers[nid]) { clearInterval(spinTimers[nid]); delete spinTimers[nid]; }
  if (!text || text === 'idle') {
    s.textContent = ''; s.setAttribute('fill', '#484f58'); return;
  }
  if (text.startsWith('\u2713')) {
    s.textContent = text; s.setAttribute('fill', '#3fb950'); return;
  }
  let f = 0;
  s.textContent = spinChars[0] + ' ' + text;
  s.setAttribute('fill', '#8b949e');
  spinTimers[nid] = setInterval(() => {
    f = (f + 1) % spinChars.length;
    s.textContent = spinChars[f] + ' ' + text;
  }, 80);
}

// --- Edge flash ---

function flashEdge(from, to) {
  const key = from + '->' + to;
  const id = EDGE_MAP[key];
  if (!id) return;
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('flash');
  void el.offsetWidth;
  el.classList.add('flash');
  setTimeout(() => el.classList.remove('flash'), 900);
}

// --- Activity cards for internal nodes ---

function getOrCreateActivityCard(nid) {
  if (activityCards[nid]) return activityCards[nid];
  const card = document.createElement('div');
  card.className = 'activity-card active node-' + nid;
  card.id = 'card-' + nid;
  const lbl = (nodeNames[nid] || nid).toUpperCase();
  card.innerHTML = '<span class="card-label">' + lbl +
    '</span><span class="card-action">thinking...</span>' +
    '<span class="card-time">0s</span>';
  chat.appendChild(card);
  chat.scrollTop = chat.scrollHeight;
  activityCards[nid] = card;
  const start = Date.now();
  cardTimers[nid] = setInterval(() => {
    const elapsed = Math.round((Date.now() - start) / 1000);
    const t = card.querySelector('.card-time');
    if (t) t.textContent = elapsed + 's';
  }, 1000);
  return card;
}

function updateActivityCard(nid, action) {
  const card = getOrCreateActivityCard(nid);
  const el = card.querySelector('.card-action');
  if (el) el.textContent = action;
}

function completeActivityCard(nid, iterations) {
  const card = activityCards[nid];
  if (!card) return;
  if (cardTimers[nid]) { clearInterval(cardTimers[nid]); delete cardTimers[nid]; }
  card.classList.remove('active');
  card.classList.add('done');
  const el = card.querySelector('.card-action');
  if (el) el.textContent = 'done (' + (iterations || '?') + ' iters)';
  activityCards[nid] = null;
}

// --- Progress indicator ---

function updateProgress() {
  const el = document.getElementById('progress-info');
  if (!el || !pipelineStartTime) return;
  const elapsed = Math.round((Date.now() - pipelineStartTime) / 1000);
  el.textContent = '[iter ' + totalIterations + ' | ' + elapsed + 's]';
}

function startProgress() {
  pipelineStartTime = Date.now();
  totalIterations = 0;
  updateProgress();
  progressInterval = setInterval(updateProgress, 1000);
}

function stopProgress() {
  if (progressInterval) { clearInterval(progressInterval); progressInterval = null; }
  const el = document.getElementById('progress-info');
  if (el) el.textContent = '';
}

function connect() {
  ws = new WebSocket('ws://' + location.host + '/ws');
  ws.onopen = () => {
    setStatus('Connected');
    enableInput('Tell the Intake agent what repo to scan...');
  };
  ws.onmessage = handleEvent;
  ws.onerror = () => setStatus('Connection error');
  ws.onclose = () => {
    setStatus('Reconnecting...');
    disableInput('Reconnecting...');
    setTimeout(connect, 2000);
  };
}

// Node spec metadata for client-facing detection
const NODE_SPECS = {
  intake: {client_facing: true}, scanner: {client_facing: false},
  profiler: {client_facing: false}, scorer: {client_facing: false},
  extractor: {client_facing: false}, review: {client_facing: true},
  campaign_builder: {client_facing: true}, approval: {client_facing: true},
  sender: {client_facing: false}
};

function handleEvent(msg) {
  const evt = JSON.parse(msg.data);
  const nid = evt.node_id || '';
  const isClientFacing = NODE_SPECS[nid] && NODE_SPECS[nid].client_facing;

  // --- Node lifecycle ---
  if (evt.type === 'node_loop_started') {
    setNodeState(nid, 'active');
    setNodeStatus(nid, 'thinking');
    setStatus('Running: ' + (nodeNames[nid]||nid));
    if (lastCompletedNode) flashEdge(lastCompletedNode, nid);
    if (!isClientFacing) getOrCreateActivityCard(nid);
    if (!pipelineStartTime) startProgress();
  }
  else if (evt.type === 'node_loop_iteration') {
    setNodeState(nid, 'active');
    totalIterations++;
    updateProgress();
  }
  else if (evt.type === 'node_loop_completed') {
    if (assistantEls[nid]) {
      var tc = assistantEls[nid].querySelector('.text-content');
      if (tc && !tc.textContent) assistantEls[nid].remove();
      assistantEls[nid] = null;
    }
    setNodeState(nid, 'done');
    setNodeStatus(nid, '\u2713 done');
    if (!isClientFacing) completeActivityCard(nid, evt.iterations);
    lastCompletedNode = nid;
  }
  else if (evt.type === 'node_started') {
    setNodeState(nid, 'active');
    setNodeStatus(nid, 'running');
    setStatus('Running: ' + (nodeNames[nid]||nid));
    if (lastCompletedNode) flashEdge(lastCompletedNode, nid);
  }

  // --- Awaiting user input (HITL) ---
  else if (evt.type === 'awaiting_input') {
    setNodeState(evt.node_id, 'waiting');
    setNodeStatus(evt.node_id, 'waiting');
    setStatus('Waiting: ' + (nodeNames[evt.node_id]||evt.node_id));
    enableInput('Message to ' + (nodeNames[evt.node_id]||evt.node_id) + '...');
  }

  // --- LLM streaming ---
  else if (evt.type === 'llm_text_delta') {
    setNodeState(nid, 'active');
    if (isClientFacing) {
      if (!assistantEls[nid]) {
        assistantEls[nid] = addNodeMsg(nid, '');
      }
      var tc = assistantEls[nid].querySelector('.text-content');
      if (tc) tc.textContent += evt.content;
      chat.scrollTop = chat.scrollHeight;
    } else {
      setNodeStatus(nid, 'streaming');
      updateActivityCard(nid, 'thinking...');
    }
  }
  else if (evt.type === 'client_output_delta') {
    setNodeState(nid, 'active');
    if (!assistantEls[nid]) {
      assistantEls[nid] = addNodeMsg(nid, '');
    }
    var tc = assistantEls[nid].querySelector('.text-content');
    if (tc) tc.textContent += (evt.content || '');
    chat.scrollTop = chat.scrollHeight;
  }

  // --- Tool calls ---
  else if (evt.type === 'tool_call_started') {
    setNodeState(nid, 'active');
    if (assistantEls[nid]) {
      var tc = assistantEls[nid].querySelector('.text-content');
      if (tc && !tc.textContent) assistantEls[nid].remove();
      assistantEls[nid] = null;
    }
    if (evt.tool_name !== 'set_output') {
      setNodeStatus(nid, 'tool:' + evt.tool_name);
      if (!isClientFacing) updateActivityCard(nid, 'calling ' + evt.tool_name + '...');
      var info = evt.tool_name + '(' + JSON.stringify(evt.tool_input||{}).slice(0,80) + ')';
      addEventMsg(nid, 'TOOL ' + info, 'tool');
    }
  }
  else if (evt.type === 'tool_call_completed') {
    if (evt.tool_name === 'set_output') {
      addEventMsg(nid, 'set_output: ' + (evt.output_key||''), 'done');
    } else {
      setNodeStatus(nid, 'thinking');
      if (!isClientFacing) updateActivityCard(nid, 'processing...');
      var preview = (evt.result || '').slice(0, 150);
      addEventMsg(nid, 'RESULT: ' + preview, 'tool');
    }
    assistantEls[nid] = null;
  }

  // --- Feedback edge fired ---
  else if (evt.type === 'feedback_edge') {
    addEventMsg(evt.from_node, 'feedback \u2192 ' + (nodeNames[evt.to_node]||evt.to_node), 'feedback');
    flashEdge(evt.from_node, evt.to_node);
  }

  // --- Pipeline complete ---
  else if (evt.type === 'pipeline_done') {
    setStatus('Pipeline Complete');
    stopProgress();
    allNodes.forEach(n => { setNodeState(n, 'done'); setNodeStatus(n, '\u2713 done'); });
    Object.keys(spinTimers).forEach(k => { clearInterval(spinTimers[k]); delete spinTimers[k]; });
    Object.keys(cardTimers).forEach(k => { clearInterval(cardTimers[k]); delete cardTimers[k]; });
    for (var k in assistantEls) {
      if (assistantEls[k]) {
        var tc = assistantEls[k].querySelector('.text-content');
        if (tc && !tc.textContent) assistantEls[k].remove();
        assistantEls[k] = null;
      }
    }
    var banner = document.createElement('div');
    banner.className = 'result-banner';
    var h3 = document.createElement('h3');
    h3.textContent = 'Pipeline Complete';
    banner.appendChild(h3);
    if (evt.send_results) {
      var report = document.createElement('div');
      report.className = 'report';
      report.textContent = typeof evt.send_results === 'string'
        ? evt.send_results : JSON.stringify(evt.send_results, null, 2);
      banner.appendChild(report);
    }
    if (evt.total_tokens) {
      var tok = document.createElement('div');
      tok.className = 'tokens';
      tok.textContent = 'Total tokens: ' + evt.total_tokens.toLocaleString()
        + ' | Steps: ' + (evt.steps||'?')
        + ' | Path: ' + (evt.path||[]).join(' \u2192 ');
      banner.appendChild(tok);
    }
    chat.appendChild(banner);
    chat.scrollTop = chat.scrollHeight;
    disableInput('Pipeline complete. Refresh to restart.');
  }
  else if (evt.type === 'error') {
    setStatus('Error');
    stopProgress();
    addMsg('ERROR: ' + (evt.message || ''), 'event feedback');
    enableInput('Error occurred. Try again...');
  }
}

function sendMsg() {
  const text = inputEl.value.trim();
  if (!text || !ws || ws.readyState !== 1 || !inputEnabled) return;
  addMsg(text, 'user');

  if (!started) {
    started = true;
    setStatus('Starting pipeline...');
    disableInput('Processing...');
    ws.send(JSON.stringify({type: 'start', message: text}));
  } else {
    ws.send(JSON.stringify({type: 'message', message: text}));
    disableInput('Processing...');
  }
  inputEl.value = '';
}

connect();
</script>
</body>
</html>"""


# =========================================================================
# WebSocket Handler — Pipeline Orchestrator
# =========================================================================


async def handle_ws(websocket):
    """Handle WebSocket connections for the outreach pipeline demo.

    Uses a single recv() for the start message instead of ``async for``
    so the websocket's recv lock is released before _run_pipeline creates
    its own reader task. (Two concurrent recv calls raise ConcurrencyError.)
    """
    try:
        raw = await websocket.recv()
        try:
            msg = json.loads(raw)
        except Exception:
            return

        if msg.get("type") != "start":
            return

        try:
            await _run_pipeline(websocket, msg.get("message", ""))
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket closed during pipeline")
        except Exception as e:
            logger.exception("Pipeline error")
            try:
                await websocket.send(json.dumps({"type": "error", "message": str(e)}))
            except Exception:
                pass
    except websockets.exceptions.ConnectionClosed:
        pass


async def _run_pipeline(websocket, initial_message: str):
    """Execute the GitHub outreach pipeline through GraphExecutor."""
    bus = EventBus()

    # State for routing user messages to active client-facing node
    active_node: EventLoopNode | None = None
    pending_messages: list[str] = []

    # --- Shared pipeline config (updated by Intake, read by judges) ---

    pipeline_config: dict[str, Any] = {"min_leads": 50}  # default

    # --- Build judges ---
    # Client-facing nodes (intake, review, approval) have client_facing=True
    # in their NodeSpec — EventLoopNode blocks for user input natively.
    # Only nodes that need output schema validation get a judge.

    # Intake needs schema validation for its structured outputs
    client_judges: dict[str, SchemaJudge] = {
        "intake": SchemaJudge(IntakeOutput),
    }
    # review & approval: no judge — implicit judge checks output keys,
    # and client_facing blocking is handled by the node itself.

    # Internal: SchemaJudge (validates output structure)
    schema_judges: dict[str, SchemaJudge] = {
        "scanner": SchemaJudge(
            ScannerOutput,
            min_items={"github_users": lambda: pipeline_config["min_leads"]},
            data_dir=_DATA_DIR,
        ),
        "profiler": SchemaJudge(ProfilerOutput),
        "scorer": SchemaJudge(ScorerOutput),
        "extractor": SchemaJudge(ExtractorOutput),
        # campaign_builder is now client_facing — implicit judge + native
        # blocking handle termination (same pattern as review/approval).
    }

    all_judges: dict = {**client_judges, **schema_judges}

    # --- Build EventLoopNode for each event_loop node ---

    tool_executor = TOOL_REGISTRY.get_executor()
    all_tools = list(TOOL_REGISTRY.get_tools().values())
    nodes: dict[str, EventLoopNode] = {}

    for nid, spec in NODE_SPECS.items():
        if spec.node_type != "event_loop":
            continue
        judge = all_judges.get(nid)
        node = EventLoopNode(
            event_bus=bus,
            judge=judge,
            config=LoopConfig(
                max_iterations=30,
                max_tool_calls_per_turn=15,
                max_history_tokens=64000,
                max_tool_result_chars=8_000,
                spillover_dir=str(_DATA_DIR),
            ),
            conversation_store=None,
            tool_executor=tool_executor if spec.tools else None,
        )
        nodes[nid] = node

    # --- Build GraphExecutor and register all nodes ---

    executor = GraphExecutor(
        runtime=RUNTIME,
        llm=LLM,
        tools=all_tools,
        tool_executor=tool_executor,
        enable_parallel_execution=True,
    )
    for nid, impl in nodes.items():
        executor.register_node(nid, impl)
    executor.register_node("sender", SenderNode())

    # --- Event forwarding: bus → WebSocket ---

    async def forward_event(event: AgentEvent):
        try:
            payload = {"type": event.type.value, **event.data}
            if event.node_id:
                payload["node_id"] = event.node_id

            # Remap CUSTOM events to their custom_type
            if event.type == EventType.CUSTOM and "custom_type" in event.data:
                payload["type"] = event.data["custom_type"]

            # Remap CLIENT_INPUT_REQUESTED to awaiting_input for JS compatibility
            if event.type == EventType.CLIENT_INPUT_REQUESTED:
                payload["type"] = "awaiting_input"

            await websocket.send(json.dumps(payload))
        except Exception:
            pass

    bus.subscribe(
        event_types=[
            EventType.NODE_LOOP_STARTED,
            EventType.NODE_LOOP_ITERATION,
            EventType.NODE_LOOP_COMPLETED,
            EventType.LLM_TEXT_DELTA,
            EventType.TOOL_CALL_STARTED,
            EventType.TOOL_CALL_COMPLETED,
            EventType.CLIENT_OUTPUT_DELTA,
            EventType.CLIENT_INPUT_REQUESTED,
            EventType.NODE_STALLED,
            EventType.CUSTOM,
        ],
        handler=forward_event,
    )

    # --- Track active client-facing node for message routing ---
    # EventLoopNode publishes CLIENT_INPUT_REQUESTED when a client_facing
    # node blocks for user input (native blocking, no judge needed).

    CLIENT_FACING_NODES = {"intake", "review", "approval"}

    async def on_awaiting_input(event: AgentEvent):
        nonlocal active_node
        nid = event.node_id or ""
        if nid not in CLIENT_FACING_NODES:
            return
        active_node = nodes.get(nid)
        logger.info("Active HITL node: %s", nid)
        # Deliver any pending messages
        while pending_messages:
            msg_text = pending_messages.pop(0)
            if active_node:
                await active_node.inject_event(msg_text)

    bus.subscribe(event_types=[EventType.CLIENT_INPUT_REQUESTED], handler=on_awaiting_input)

    # --- Capture min_leads from Intake's set_output tool call ---

    async def on_tool_started(event: AgentEvent):
        if event.node_id != "intake":
            return
        if event.data.get("tool_name") != "set_output":
            return
        tool_input = event.data.get("tool_input", {})
        if tool_input.get("key") != "min_leads":
            return
        raw = tool_input.get("value", "")
        try:
            val = int(raw)
            if val > 0:
                pipeline_config["min_leads"] = val
                logger.info("Scanner min_leads set to %d (from user)", val)
        except (ValueError, TypeError):
            logger.info(
                "No valid min_leads from user, using default %d",
                pipeline_config["min_leads"],
            )

    bus.subscribe(event_types=[EventType.TOOL_CALL_STARTED], handler=on_tool_started)

    # --- Inject initial user message into intake node ---

    if initial_message:
        await nodes["intake"].inject_event(initial_message)

    # --- Run pipeline as background task ---

    pipeline_task = asyncio.create_task(executor.execute(GRAPH, GOAL, input_data={}))

    # --- WS message loop: route incoming messages to active node ---

    async def ws_reader():
        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                text = msg.get("message", "")
                if not text:
                    continue

                # Forward to browser as user bubble
                await websocket.send(
                    json.dumps(
                        {
                            "type": "user_message",
                            "content": text,
                        }
                    )
                )

                if active_node:
                    await active_node.inject_event(text)
                else:
                    pending_messages.append(text)
        except websockets.exceptions.ConnectionClosed:
            pass

    reader_task = asyncio.create_task(ws_reader())

    # --- Wait for pipeline to complete ---

    try:
        result = await asyncio.wait_for(pipeline_task, timeout=1800)
    except TimeoutError:
        for nid in CLIENT_FACING_NODES:
            if nid in nodes:
                nodes[nid].signal_shutdown()
        reader_task.cancel()
        await websocket.send(
            json.dumps({"type": "error", "message": "Pipeline timed out (10 min)"})
        )
        return
    except Exception as e:
        reader_task.cancel()
        await websocket.send(json.dumps({"type": "error", "message": str(e)}))
        return

    reader_task.cancel()

    # --- Send final result ---

    send_results = result.output.get("send_results", "")
    await websocket.send(
        json.dumps(
            {
                "type": "pipeline_done",
                "success": result.success,
                "send_results": send_results,
                "total_tokens": result.total_tokens,
                "steps": result.steps_executed,
                "path": result.path,
                "node_visit_counts": result.node_visit_counts,
                "error": result.error,
            }
        )
    )

    logger.info(
        "Pipeline complete: success=%s, steps=%d, tokens=%d, path=%s, error=%s",
        result.success,
        result.steps_executed,
        result.total_tokens,
        " -> ".join(result.path),
        result.error,
    )


# =========================================================================
# HTTP Handler
# =========================================================================


async def process_request(connection, request: Request):
    """Serve HTML on GET /, upgrade to WebSocket on /ws."""
    if request.path == "/ws":
        return None
    return Response(
        HTTPStatus.OK,
        "OK",
        websockets.Headers({"Content-Type": "text/html; charset=utf-8"}),
        HTML_PAGE.encode(),
    )


# =========================================================================
# Main
# =========================================================================


async def main():
    port = 8768
    async with websockets.serve(
        handle_ws,
        "0.0.0.0",
        port,
        process_request=process_request,
    ):
        logger.info(f"GitHub Outreach Pipeline demo running at http://localhost:{port}")
        logger.info("Open in your browser to start the pipeline.")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
