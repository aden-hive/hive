#!/usr/bin/env python3
"""
Aden Documentation Chatbot with LLM Integration

Uses the Hive framework's LiteLLMProvider for LLM calls.
Supports Gemini, OpenAI, and Anthropic through the same interface.
"""

import os
import sys
from pathlib import Path

# Load .env file
env_path = Path(__file__).parent.parent.parent / '.env'
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value.strip('"').strip("'")

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'core'))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'tools' / 'src'))

from search import search_docs, find_code_samples, get_intro, get_quickstart, load_index


def get_llm_provider():
    """Get LLM provider using the framework's LiteLLMProvider."""
    try:
        from framework.llm import LiteLLMProvider
        
        # Gemini (use 2.5-flash for better rate limits)
        if os.getenv('GEMINI_API_KEY'):
            return LiteLLMProvider(model='gemini/gemini-2.5-flash')
        
        # OpenAI
        if os.getenv('OPENAI_API_KEY'):
            return LiteLLMProvider(model='gpt-4o-mini')
        
        # Anthropic
        if os.getenv('ANTHROPIC_API_KEY'):
            return LiteLLMProvider(model='claude-3-haiku-20240307')
        
        return None
        
    except ImportError as e:
        print(f"⚠️  Framework not available: {e}")
        return None


def build_context(question: str) -> str:
    """Build context from indexed docs for the question."""
    context_parts = []
    
    # Search for relevant docs
    results = search_docs(question, max_results=3)
    for r in results:
        doc = r['doc']
        context_parts.append(f"### {doc['title']}\n{doc['text'][:800]}\nURL: {doc['url']}\n")
    
    # Find code samples
    codes = find_code_samples(question, max_samples=2)
    if codes:
        context_parts.append("\n### Code Examples:")
        for c in codes:
            context_parts.append(f"\nFrom {c['source_title']}:\n```\n{c['code'][:400]}\n```")
    
    return "\n".join(context_parts)


SYSTEM_PROMPT = """You are the Aden Documentation Assistant, a helpful AI that answers questions about the Aden Agent Framework.

Aden is a platform for building goal-driven AI agents that improve themselves. Key features:
- Define goals through natural language
- Framework generates node graphs with connection code
- Automatic failure capture and agent evolution
- Self-healing and redeployment

When answering:
1. Be concise and helpful
2. Include code examples when relevant
3. Reference documentation URLs when appropriate
4. If you don't know something, say so

Use the provided documentation context to answer questions accurately."""


def ask_with_llm(question: str, llm_provider) -> str:
    """Ask a question using the framework's LLM provider."""
    
    # Build context from docs
    context = build_context(question)
    
    if not context.strip():
        context = get_intro()[:1000]
    
    # Build the prompt
    user_message = f"""Question: {question}

Documentation Context:
{context}

Please provide a helpful, conversational answer based on the documentation above."""

    try:
        response = llm_provider.complete(
            messages=[{"role": "user", "content": user_message}],
            system=SYSTEM_PROMPT,
            max_tokens=1024
        )
        return response.content
    except Exception as e:
        error_msg = str(e)
        # Check for rate limiting
        if '429' in error_msg or 'quota' in error_msg.lower() or 'rate' in error_msg.lower():
            print("\n⚠️  Rate limited - using simple mode")
        else:
            print(f"\n⚠️  LLM error: {error_msg[:80]}")
        return ask_simple(question)


def ask_simple(question: str) -> str:
    """Conversational answer without LLM using indexed docs."""
    q_lower = question.lower()
    
    # Greetings
    if q_lower in ['hi', 'hello', 'hey']:
        return """👋 Hello! I'm the Aden Documentation Assistant.

I can help you with:
• **What is Aden?** - Learn about the platform
• **How to get started?** - Setup and quickstart guide  
• **Show code examples** - See sample code
• **Testing agents** - Learn about testing

What would you like to know?"""

    # About Aden
    if any(w in q_lower for w in ['what is aden', 'about aden', 'introduce', 'overview']):
        intro = get_intro()[:800]
        return f"""**What is Aden?**

Aden is a platform for building **goal-driven AI agents** that improve themselves.

**Key Features:**
• Define goals through natural language
• Framework generates node graphs with connection code
• Automatic failure capture and agent evolution
• Self-healing and redeployment

{intro[:400]}...

📚 Learn more: https://docs.adenhq.com/"""

    # Quickstart
    if any(w in q_lower for w in ['quickstart', 'start', 'setup', 'install', 'begin']):
        codes = find_code_samples("quickstart clone setup", max_samples=1)
        code = codes[0]['code'][:400] if codes else ""
        return f"""**Getting Started with Aden**

**Prerequisites:**
• Python 3.11 or higher
• Anthropic or OpenAI API key

**Quick Setup:**
```bash
{code}
```

**Next Steps:**
1. Clone the repository
2. Run the setup script  
3. Set your API key in environment
4. Run your first agent!

📚 Full guide: https://docs.adenhq.com/getting-started/quickstart"""

    # Code examples
    if any(w in q_lower for w in ['code', 'example', 'sample', 'show']):
        codes = find_code_samples(question, max_samples=2)
        if codes:
            response = "**Code Examples:**\n\n"
            for c in codes:
                response += f"From **{c['source_title']}**:\n```\n{c['code'][:350]}\n```\n\n"
            return response
        return "What kind of code would you like to see? Try: 'agent.json example', 'quickstart code'"

    # Testing  
    if any(w in q_lower for w in ['test', 'testing']):
        results = search_docs("testing agents", max_results=1)
        if results:
            doc = results[0]['doc']
            return f"""**Testing Aden Agents**

Aden includes a goal-based testing framework:
• Define test cases with expected outcomes
• Run automated validation
• Track success criteria

{doc['text'][:400]}...

📚 Testing Guide: https://docs.adenhq.com/building/testing"""
        
    # MCP
    if 'mcp' in q_lower:
        return """**MCP (Model Context Protocol) in Aden**

MCP provides pre-built tools for agents:
• **pdf_read** - Extract text from PDFs
• **web_search** - Search the web
• **csv_read/write** - Handle CSV files

**Start MCP Server:**
```bash
python tools/mcp_server.py --port 4001
```

📚 MCP Guide: https://docs.adenhq.com/mcp-server/introduction"""

    # General search
    results = search_docs(question, max_results=2)
    if results:
        response = f"**Here's what I found for '{question}':**\n\n"
        for r in results:
            doc = r['doc']
            response += f"### {doc['title']}\n{doc['text'][:250]}...\n\n🔗 {doc['url']}\n\n"
        
        codes = find_code_samples(question, max_samples=1)
        if codes:
            response += f"\n**Related Code:**\n```\n{codes[0]['code'][:250]}\n```"
        return response
    
    return """I couldn't find specific information about that. 

Try asking:
• What is Aden?
• How to get started?
• Show me code examples
• How to test agents?"""


def interactive_mode():
    """Run interactive chatbot."""
    print("=" * 60)
    print("🤖 Aden Documentation Chatbot")
    print("=" * 60)
    
    llm = get_llm_provider()
    
    if llm:
        print(f"✓ Using LLM: {llm.model}")
    else:
        print("ℹ️  Running in simple mode (no API key found)")
    
    print("\nAsk me anything about Aden! Type 'quit' to exit.\n")
    
    while True:
        try:
            question = input("\n👤 You: ").strip()
            
            if not question:
                continue
            
            if question.lower() in ('quit', 'exit', 'q'):
                print("\nGoodbye! 👋")
                break
            
            print("\n🤖 Bot: ", end="", flush=True)
            if llm:
                answer = ask_with_llm(question, llm)
            else:
                answer = ask_simple(question)
            print(answer)
            
        except KeyboardInterrupt:
            print("\n\nGoodbye! 👋")
            break
        except EOFError:
            break


def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        # Single question mode
        question = ' '.join(sys.argv[1:])
        llm = get_llm_provider()
        if llm:
            print(ask_with_llm(question, llm))
        else:
            print(ask_simple(question))
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
