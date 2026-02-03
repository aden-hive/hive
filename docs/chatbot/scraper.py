#!/usr/bin/env python3
"""
Documentation Scraper - Scrapes docs.adenhq.com for chatbot indexing.
"""

import json
import re
import urllib.request
from pathlib import Path
from html.parser import HTMLParser


class HTMLTextExtractor(HTMLParser):
    """Extract text and code from HTML."""
    
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.code_blocks = []
        self.in_code = False
        self.current_code = []
        self.skip_tags = {'script', 'style', 'nav', 'footer', 'header'}
        self.current_skip = 0
        
    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self.current_skip += 1
        if tag in ('code', 'pre'):
            self.in_code = True
            
    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.current_skip -= 1
        if tag in ('code', 'pre') and self.in_code:
            self.in_code = False
            code = ''.join(self.current_code).strip()
            if code and len(code) > 10:  # Skip tiny snippets
                self.code_blocks.append(code)
            self.current_code = []
            
    def handle_data(self, data):
        if self.current_skip > 0:
            return
        if self.in_code:
            self.current_code.append(data)
        else:
            text = data.strip()
            if text:
                self.text_parts.append(text)


def fetch_page(url: str) -> str:
    """Fetch HTML content from URL."""
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Docs Chatbot Scraper)'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return ""


def extract_content(html: str) -> dict:
    """Extract text and code from HTML."""
    parser = HTMLTextExtractor()
    parser.feed(html)
    
    text = ' '.join(parser.text_parts)
    # Clean up text
    text = re.sub(r'\s+', ' ', text)
    
    return {
        'text': text[:5000],  # Limit text size
        'code_samples': parser.code_blocks[:10]  # Limit code samples
    }


def scrape_docs() -> list[dict]:
    """Scrape all documentation pages."""
    
    # Documentation pages to scrape
    pages = [
        {"url": "https://docs.adenhq.com/", "title": "Introduction", "section": "intro"},
        {"url": "https://docs.adenhq.com/getting-started/quickstart", "title": "Quickstart", "section": "getting-started"},
        {"url": "https://docs.adenhq.com/concepts/overview", "title": "Core Concepts", "section": "concepts"},
        {"url": "https://docs.adenhq.com/building/first-agent", "title": "Build First Agent", "section": "building"},
        {"url": "https://docs.adenhq.com/building/testing", "title": "Testing Framework", "section": "building"},
        {"url": "https://docs.adenhq.com/mcp-server/introduction", "title": "MCP Tools", "section": "mcp"},
    ]
    
    docs = []
    
    for page in pages:
        print(f"Scraping: {page['title']}...")
        html = fetch_page(page['url'])
        
        if html:
            content = extract_content(html)
            docs.append({
                'url': page['url'],
                'title': page['title'],
                'section': page['section'],
                'text': content['text'],
                'code_samples': content['code_samples']
            })
            print(f"  ✓ {len(content['text'])} chars, {len(content['code_samples'])} code samples")
        else:
            print(f"  ✗ Failed to fetch")
    
    return docs


def save_index(docs: list[dict], output_path: str = None):
    """Save scraped docs to JSON file."""
    if output_path is None:
        output_path = Path(__file__).parent / "data" / "docs_index.json"
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(docs, f, indent=2, ensure_ascii=False)
    
    print(f"\n✓ Saved {len(docs)} pages to {output_path}")


def main():
    """Run the scraper."""
    print("=" * 50)
    print("Aden Documentation Scraper")
    print("=" * 50 + "\n")
    
    docs = scrape_docs()
    save_index(docs)
    
    print("\nDone!")


if __name__ == "__main__":
    main()
