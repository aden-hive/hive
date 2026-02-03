#!/usr/bin/env python3
"""
Documentation Search - Search indexed docs for relevant content.
"""

import json
import re
from pathlib import Path


def load_index(index_path: str = None) -> list[dict]:
    """Load the docs index from JSON file."""
    if index_path is None:
        index_path = Path(__file__).parent / "data" / "docs_index.json"
    
    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("Index not found. Run scraper.py first.")
        return []


def search_docs(query: str, max_results: int = 3) -> list[dict]:
    """
    Search indexed docs for matching content.
    
    Returns list of matching docs with relevance score.
    """
    docs = load_index()
    if not docs:
        return []
    
    query_words = set(query.lower().split())
    results = []
    
    for doc in docs:
        # Calculate simple relevance score
        text_lower = doc['text'].lower()
        title_lower = doc['title'].lower()
        
        # Count keyword matches
        score = 0
        for word in query_words:
            if word in title_lower:
                score += 10  # Title matches are more important
            score += text_lower.count(word)
        
        if score > 0:
            results.append({
                'doc': doc,
                'score': score
            })
    
    # Sort by score (highest first)
    results.sort(key=lambda x: x['score'], reverse=True)
    
    return results[:max_results]


def find_code_samples(query: str, max_samples: int = 3) -> list[dict]:
    """
    Find code samples matching the query.
    
    Returns list of code samples with their source docs.
    """
    docs = load_index()
    if not docs:
        return []
    
    query_words = set(query.lower().split())
    samples = []
    
    for doc in docs:
        for code in doc.get('code_samples', []):
            code_lower = code.lower()
            
            # Check if query words appear in code
            matches = sum(1 for word in query_words if word in code_lower)
            
            if matches > 0:
                samples.append({
                    'code': code,
                    'source_title': doc['title'],
                    'source_url': doc['url'],
                    'matches': matches
                })
    
    # Sort by matches
    samples.sort(key=lambda x: x['matches'], reverse=True)
    
    return samples[:max_samples]


def get_intro() -> str:
    """Get the Aden introduction text."""
    docs = load_index()
    for doc in docs:
        if doc.get('section') == 'intro':
            return doc.get('text', '')[:1000]
    return "Aden is a platform for building goal-driven AI agents."


def get_quickstart() -> str:
    """Get quickstart steps."""
    docs = load_index()
    for doc in docs:
        if doc.get('section') == 'getting-started':
            return doc.get('text', '')[:1500]
    return "Visit https://docs.adenhq.com/getting-started/quickstart"


def main():
    """Test search functionality."""
    print("=" * 50)
    print("Documentation Search Test")
    print("=" * 50 + "\n")
    
    # Test searches
    queries = [
        "how to create agent",
        "quickstart setup",
        "agent.json",
        "testing"
    ]
    
    for query in queries:
        print(f"\nQuery: '{query}'")
        print("-" * 40)
        
        results = search_docs(query)
        if results:
            for r in results:
                print(f"  [{r['score']}] {r['doc']['title']}")
                print(f"      {r['doc']['text'][:100]}...")
        else:
            print("  No results found")
        
        # Also show code samples
        codes = find_code_samples(query, max_samples=1)
        if codes:
            print(f"\n  Code sample from {codes[0]['source_title']}:")
            print(f"  ```\n  {codes[0]['code'][:200]}...\n  ```")


if __name__ == "__main__":
    main()
