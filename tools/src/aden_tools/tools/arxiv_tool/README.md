# arXiv Tool

This tool enables agents to perform rigorous literature reviews by retrieving structured metadata and downloading PDFs from arXiv.

## Tools

### search_papers
Searches for papers by keyword or specific ID.
- **Args**: `query` (str), `max_results` (int)
- **Returns**: List of papers with Title, Summary, and `paper_id`.

### download_paper
Downloads a PDF for a specific `paper_id` to a temporary directory.
- **Returns**: The local file path for ingestion by `pdf_read_tool`.

## Environment Variables
None required (Public API).