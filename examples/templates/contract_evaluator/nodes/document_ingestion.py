"""Document ingestion node - extracts text from PDF/DOCX files."""

from pathlib import Path
from framework.graph.node import Node, NodeContext

# Simple PDF and DOCX extraction libraries
try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

try:
    import docx
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False


async def document_ingestion_node(context: NodeContext) -> dict:
    """
    Extract text and metadata from contract documents.
    
    Supports PDF and DOCX formats. Falls back to plain text if libraries not available.
    
    Input:
        - contract_path: Path to the contract file
        
    Output:
        - full_text: Extracted text content
        - file_type: Type of file (pdf, docx, txt)
        - page_count: Number of pages (if applicable)
        - word_count: Approximate word count
        - success: Whether extraction succeeded
    """
    input_data = context.input_data
    contract_path = input_data.get("contract_path")
    
    if not contract_path:
        return {
            "success": False,
            "error": "No contract_path provided in input"
        }
    
    file_path = Path(contract_path)
    
    if not file_path.exists():
        return {
            "success": False,
            "error": f"File not found: {contract_path}"
        }
    
    file_ext = file_path.suffix.lower()
    
    try:
        # Extract text based on file type
        if file_ext == ".pdf" and HAS_PYPDF2:
            text, page_count = _extract_from_pdf(file_path)
        elif file_ext in [".docx", ".doc"] and HAS_DOCX:
            text, page_count = _extract_from_docx(file_path)
        elif file_ext == ".txt":
            text = file_path.read_text(encoding="utf-8")
            page_count = None
        else:
            # Fallback: try reading as plain text
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            page_count = None
        
        word_count = len(text.split())
        
        return {
            "success": True,
            "full_text": text,
            "file_type": file_ext.lstrip("."),
            "page_count": page_count,
            "word_count": word_count,
            "contract_id": file_path.stem,
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to extract text: {str(e)}"
        }


def _extract_from_pdf(file_path: Path) -> tuple[str, int]:
    """Extract text from PDF file."""
    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        page_count = len(reader.pages)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
    return text, page_count


def _extract_from_docx(file_path: Path) -> tuple[str, int]:
    """Extract text from DOCX file."""
    doc = docx.Document(file_path)
    paragraphs = [para.text for para in doc.paragraphs]
    text = "\n".join(paragraphs)
    # Approximate page count (250 words per page)
    word_count = len(text.split())
    page_count = max(1, word_count // 250)
    return text, page_count


# Create the node instance
intake_node = Node(
    id="document_ingestion",
    fn=document_ingestion_node,
    name="Document Ingestion",
    description="Extracts text from PDF/DOCX contract files",
)
