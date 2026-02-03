#!/usr/bin/env python3
"""
Aden Documentation Chatbot Demo

An interactive chatbot that answers questions about Aden using indexed docs.
"""

import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from search import search_docs, find_code_samples, get_intro, get_quickstart


def format_response(text: str, code: str = None, source: str = None) -> str:
    """Format a chatbot response."""
    response = text
    
    if code:
        response += f"\n\n```\n{code}\n```"
    
    if source:
        response += f"\n\n📚 Source: {source}"
    
    return response


def ask(question: str) -> str:
    """
    Answer a question about Aden documentation.
    
    Args:
        question: User's question
        
    Returns:
        Answer with relevant docs and code samples
    """
    q_lower = question.lower()
    
    # Check for common intents
    if any(w in q_lower for w in ['what is aden', 'introduce', 'about aden', 'overview']):
        intro = get_intro()
        return format_response(
            f"**What is Aden?**\n\n{intro}",
            source="https://docs.adenhq.com/"
        )
    
    if any(w in q_lower for w in ['quickstart', 'get started', 'how to start', 'setup', 'install']):
        quickstart = get_quickstart()
        codes = find_code_samples("quickstart setup clone", max_samples=1)
        code = codes[0]['code'] if codes else None
        return format_response(
            f"**Getting Started**\n\n{quickstart[:800]}...",
            code=code,
            source="https://docs.adenhq.com/getting-started/quickstart"
        )
    
    if any(w in q_lower for w in ['code', 'example', 'sample', 'show me']):
        # Find code samples
        codes = find_code_samples(question, max_samples=2)
        if codes:
            response = "**Code Examples:**\n"
            for c in codes:
                response += f"\nFrom {c['source_title']}:\n```\n{c['code'][:500]}\n```\n"
            return response
        else:
            return "I couldn't find specific code examples for that. Try asking about 'agent.json', 'quickstart', or 'testing'."
    
    # General search
    results = search_docs(question, max_results=2)
    
    if results:
        response = f"**Results for '{question}':**\n\n"
        for r in results:
            doc = r['doc']
            response += f"### {doc['title']}\n"
            response += f"{doc['text'][:400]}...\n\n"
            response += f"🔗 {doc['url']}\n\n"
        
        # Also check for code
        codes = find_code_samples(question, max_samples=1)
        if codes:
            response += f"\n**Related Code:**\n```\n{codes[0]['code'][:300]}\n```"
        
        return response
    else:
        return f"I couldn't find information about '{question}'. Try asking about:\n- What is Aden?\n- How to get started?\n- Show me agent.json example\n- How to test agents?"


def interactive_mode():
    """Run interactive chatbot mode."""
    print("=" * 60)
    print("🤖 Aden Documentation Chatbot")
    print("=" * 60)
    print("\nAsk me anything about Aden! Type 'quit' to exit.\n")
    print("Try: 'What is Aden?', 'How to get started?', 'Show me code examples'\n")
    
    while True:
        try:
            question = input("\n👤 You: ").strip()
            
            if not question:
                continue
            
            if question.lower() in ('quit', 'exit', 'q'):
                print("\nGoodbye! 👋")
                break
            
            answer = ask(question)
            print(f"\n🤖 Bot: {answer}")
            
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
        print(ask(question))
    else:
        # Interactive mode
        interactive_mode()


if __name__ == "__main__":
    main()
