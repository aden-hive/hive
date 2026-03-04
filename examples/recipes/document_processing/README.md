# Document Processing Agent

## Goal

Extract structured information (name, date, amount) from unstructured text or documents.

## Nodes

### 1. Input Node

- Accept raw text or document content

### 2. Extraction Node

- Use LLM or parsing logic to extract:
  - name
  - date
  - amount

### 3. Output Node

- Return structured JSON

## Edges

- Input → Extraction → Output

## Tools

- LLM (OpenAI / Anthropic)
- Optional: OCR for PDFs

## Usage notes

- Useful for invoice processing
- Can be extended for contracts, forms, etc.
