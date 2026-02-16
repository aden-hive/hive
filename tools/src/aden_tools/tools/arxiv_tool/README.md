# ArXiv Toolkit

Native integration with ArXiv Public API for Hive agents.

## Overview
The ArXiv toolkit enables agents to perform rigorous scientific research and literature reviews by searching for scholarly papers and downloading their PDFs for analysis.

## Requirements
- `arxiv` Python library
- No authentication required (Public API)

## Configuration
This tool utilizes public endpoints and does not require an API key or token. However, it respects the official rate limit of a 3-second delay between requests.

## Available Tools

### Search & Discovery
- `arxiv_search_papers`: Search for papers by keywords, authors, or specific IDs. Supports filtering by relevance.

### Document Retrieval
- `arxiv_download_paper`: Downloads the full PDF of a paper to a local directory (defaults to temp). Returns the file path for ingestion by other tools like `pdf_read_tool`.

## Usage Examples

### Searching for AI Agent Research
```python
arxiv_search_papers(query='AI Agents', max_results=3)
```

### Downloading a specific paper
```python
arxiv_download_paper(paper_id='1706.03762')
```

## Setup Instructions
No setup required. ArXiv is an open-access repository.
