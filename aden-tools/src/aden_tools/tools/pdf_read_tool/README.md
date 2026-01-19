# PDF Read Tool

Read and extract text content from PDF files.

## Description

Returns text content with page markers and optional metadata. Use for reading PDFs, reports, documents, or any PDF file.

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `file_path` | str | Yes | - | Path to the PDF file to read (absolute or relative) |
| `pages` | str | No | `None` | Page range - 'all'/None for all, '5' for single, '1-10' for range, '1,3,5' for specific |
| `max_pages` | int | No | `100` | Maximum pages to process (1-1000, for memory safety) |
| `include_metadata` | bool | No | `True` | Include PDF metadata (author, title, creation date, etc.) |

## Environment Variables

This tool does not require any environment variables.

## Error Handling

Returns error dicts for common issues:
- `PDF file not found: <path>` - File does not exist
- `Not a file: <path>` - Path points to a directory
- `Not a PDF file (expected .pdf): <path>` - Wrong file extension
- `Cannot read encrypted PDF. Password required.` - PDF is password-protected
- `Page <num> out of range. PDF has <total> pages.` - Invalid page number
- `Invalid page format: '<pages>'` - Malformed page range string
- `Permission denied: <path>` - No read access to file

## Notes

- Page numbers in the `pages` argument are 1-indexed (first page is 1, not 0)
- Text is extracted with page markers: `--- Page N ---`
- Metadata includes: title, author, subject, creator, producer, created, modified
