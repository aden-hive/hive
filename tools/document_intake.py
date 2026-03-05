"""
Universal Document Intake Processor

Accepts any business document (invoices, contracts, receipts, bank statements, forms),
extracts structured data, classifies the document type, validates completeness,
and routes to appropriate workflow with confidence-based human-in-the-loop.
"""

import os
import re
import uuid
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json

# Import our schemas
from schemas import (
    ProcessedDocument, DocumentClassification, ExtractedEntity, 
    ProcessingMetrics, DocumentType, ProcessingStatus, ConfidenceLevel
)


class DocumentIntakeProcessor:
    """
    Main processor for document intake pipeline.
    Handles format detection, content extraction, classification, and routing.
    """
    
    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        # Supported file extensions and their handlers
        self.supported_formats = {
            '.pdf': 'pdf',
            '.jpg': 'image', '.jpeg': 'image', '.png': 'image', '.tiff': 'image',
            '.csv': 'csv',
            '.txt': 'text',
            '.docx': 'docx',
            '.xlsx': 'excel'
        }
        
        # Document type patterns for classification
        self.invoice_patterns = [
            r'invoice\s*#?\s*[A-Z0-9\-]+',
            r'bill\s+to\s*:', 
            r'payment\s+terms',
            r'total\s+amount',
            r'subtotal'
        ]
        
        self.contract_patterns = [
            r'agreement\s+date',
            r'party\s+[A-Za-z]+',
            r'term\s+and\s+termination',
            r'confidentiality',
            r'governing\s+law'
        ]
        
        self.receipt_patterns = [
            r'receipt\s*#?',
            r'thank\s+you\s+for\s+your\s+(purchase|payment)',
            r'cashier',
            r'total\s+paid',
            r'payment\s+method'
        ]
        
        self.bank_patterns = [
            r'account\s+statement',
            r'balance\s+forward',
            r'transaction\s+history',
            r'ending\s+balance',
            r'credit\s+limit'
        ]

    def process_document(self, file_path: str) -> ProcessedDocument:
        """
        Main processing pipeline for any document.
        """
        start_time = datetime.now()
        
        # Step 1: Validate and detect format
        print("📋 Step 1: Document Reception & Validation")
        print(f"- ⏳ Validating file exists...")
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Document not found: {file_path}")
            
        print("- ✅ File found and accessible")
        print("- ⏳ Detecting document format...")
        
        format_detected = self._detect_format(file_path)
        print(f"- ✅ Format detected: {format_detected}")
        
        # Step 2: Generate document ID
        print("- ⏳ Generating document ID...")
        document_id = self._generate_document_id()
        print(f"- ✅ Document ID: {document_id}")
        
        # Step 3: Extract content
        print("\n📄 Step 2: Content Extraction")
        print(f"- ⏳ Initializing {format_detected} extraction...")
        print("- ⏳ Extracting content (this may take a moment for large files)...")
        
        raw_content = self._extract_content(file_path, format_detected)
        char_count = len(raw_content)
        print(f"- ✅ Content extracted: {char_count} characters")
        
        # Step 4: Classify document
        print("\n🔍 Step 3: Document Classification")
        classification = self._classify_document(raw_content)
        print(f"- ✅ Classification: {classification.category.value} (confidence: {classification.confidence:.2f})")
        
        # Step 5: Extract entities based on document type
        print("\n📊 Step 4: Entity Extraction")
        extracted_entities = self._extract_entities(raw_content, classification.category)
        print(f"- ✅ Extracted {len(extracted_entities)} entities")
        
        # Step 6: Validate and make routing decision
        print("\n🎯 Step 5: Validation & Routing")
        validation_errors = self._validate_extraction(extracted_entities, classification.category)
        routing_info = self._make_routing_decision(classification, validation_errors)
        
        print(f"- ✅ Routing to: {routing_info['destination']}")
        print(f"- ✅ Human review needed: {routing_info['needs_review']}")
        
        # Step 7: Create final result
        end_time = datetime.now()
        processing_time = int((end_time - start_time).total_seconds() * 1000)
        
        metrics = ProcessingMetrics(
            start_time=start_time,
            end_time=end_time,
            processing_time_ms=processing_time,
            extraction_confidence_avg=self._calculate_avg_confidence(extracted_entities),
            validation_passed=len(validation_errors) == 0,
            routing_decision=routing_info['destination']
        )
        
        file_size = os.path.getsize(file_path)
        
        result = ProcessedDocument(
            document_id=document_id,
            original_filename=os.path.basename(file_path),
            file_path=file_path,
            file_size_bytes=file_size,
            format_detected=format_detected,
            processing_status=ProcessingStatus.COMPLETED,
            classification=classification,
            extracted_entities=extracted_entities,
            raw_content=raw_content[:10000],  # Limit raw content in output
            confidence_level=classification.confidence_level,
            validation_errors=validation_errors,
            metrics=metrics,
            routing_destination=routing_info['destination'],
            requires_human_review=routing_info['needs_review'],
            processing_history=[
                {"step": "format_detection", "status": "completed", "timestamp": start_time.isoformat()},
                {"step": "content_extraction", "status": "completed", "timestamp": start_time.isoformat()},
                {"step": "classification", "status": "completed", "timestamp": start_time.isoformat()},
                {"step": "entity_extraction", "status": "completed", "timestamp": start_time.isoformat()},
                {"step": "validation", "status": "completed", "timestamp": start_time.isoformat()},
            ]
        )
        
        print("\n✅ Document processing completed!")
        print(f"📊 Processing time: {processing_time}ms")
        print(f"🎯 Confidence level: {classification.confidence_level.value}")
        print(f"🔄 Routing to: {routing_info['destination']}")
        
        return result

    def _detect_format(self, file_path: str) -> str:
        """Detect document format from extension and content."""
        path = Path(file_path)
        ext = path.suffix.lower()
        
        # Check if we support this format
        if ext in self.supported_formats:
            return self.supported_formats[ext]
        
        # Try to detect from mimetype
        mimetype, _ = mimetypes.guess_type(file_path)
        if mimetype:
            if 'pdf' in mimetype:
                return 'pdf'
            elif 'image' in mimetype:
                return 'image'
            elif 'text' in mimetype:
                return 'text'
            elif 'csv' in mimetype:
                return 'csv'
                
        # Default to text for unknown formats
        return 'text'

    def _generate_document_id(self) -> str:
        """Generate unique document ID."""
        return f"doc_{uuid.uuid4().hex[:12]}"

    def _extract_content(self, file_path: str, format_type: str) -> str:
        """Extract text content from document based on format."""
        # For demo purposes, we'll use simple text extraction
        # In production, you'd use specialized libraries:
        # - PDF: PyPDF2, pdfplumber
        # - Images: Tesseract OCR
        # - DOCX: python-docx
        # - Excel: openpyxl
        
        if format_type == 'text':
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        elif format_type == 'csv':
            # For CSV, return as formatted text
            import csv
            content = []
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    content.append(' | '.join(row))
            return '\n'.join(content)
        else:
            # For other formats, return placeholder text for demo
            # In production, implement proper extraction
            return f"[Content from {format_type} file - would be extracted using appropriate library]"

    def _classify_document(self, content: str) -> DocumentClassification:
        """Classify document type based on content analysis."""
        import time
        start_time = time.time()
        
        content_lower = content.lower()
        scores = {}
        
        # Calculate scores for each document type
        scores['invoice'] = self._calculate_pattern_score(content_lower, self.invoice_patterns)
        scores['contract'] = self._calculate_pattern_score(content_lower, self.contract_patterns)
        scores['receipt'] = self._calculate_pattern_score(content_lower, self.receipt_patterns)
        scores['bank_statement'] = self._calculate_pattern_score(content_lower, self.bank_patterns)
        
        # Find highest scoring category
        best_category = max(scores, key=scores.get)
        best_score = scores[best_category]
        
        # Normalize confidence (0-1 range)
        confidence = min(best_score / 100, 1.0)  # Cap at 100 points = 1.0 confidence
        
        # Determine confidence level
        if confidence >= 0.85:
            confidence_level = ConfidenceLevel.HIGH
        elif confidence >= 0.7:
            confidence_level = ConfidenceLevel.MEDIUM
        else:
            confidence_level = ConfidenceLevel.LOW
            
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        return DocumentClassification(
            category=DocumentType(best_category),
            confidence=confidence,
            confidence_level=confidence_level,
            reasoning=f"Detected {best_category} patterns with {confidence:.2f} confidence",
            key_indicators=[f"{best_category}_patterns"],
            processing_time_ms=processing_time_ms
        )

    def _calculate_pattern_score(self, content: str, patterns: List[str]) -> float:
        """Calculate pattern matching score."""
        score = 0
        for pattern in patterns:
            matches = len(re.findall(pattern, content, re.IGNORECASE))
            score += matches * 25  # Each match is worth 25 points
        return score

    def _extract_entities(self, content: str, doc_type: DocumentType) -> List[ExtractedEntity]:
        """Extract entities based on document type."""
        entities = []
        
        if doc_type == DocumentType.INVOICE:
            entities.extend(self._extract_invoice_entities(content))
        elif doc_type == DocumentType.CONTRACT:
            entities.extend(self._extract_contract_entities(content))
        elif doc_type == DocumentType.RECEIPT:
            entities.extend(self._extract_receipt_entities(content))
        elif doc_type == DocumentType.BANK_STATEMENT:
            entities.extend(self._extract_bank_entities(content))
        else:
            # Generic extraction
            entities.extend(self._extract_generic_entities(content))
            
        return entities

    def _extract_invoice_entities(self, content: str) -> List[ExtractedEntity]:
        """Extract invoice-specific entities."""
        entities = []
        
        # Invoice number
        invoice_match = re.search(r'invoice\s*#?\s*([A-Z0-9\-]+)', content, re.IGNORECASE)
        if invoice_match:
            entities.append(ExtractedEntity(
                field_name="invoice_number",
                value=invoice_match.group(1),
                confidence=0.95,
                context="header",
                validation_status="needs_check"
            ))
        
        # Date
        date_match = re.search(r'date\s*:?\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})', content, re.IGNORECASE)
        if date_match:
            entities.append(ExtractedEntity(
                field_name="invoice_date",
                value=date_match.group(1),
                confidence=0.90,
                context="header",
                validation_status="needs_check"
            ))
        
        # Total amount
        total_match = re.search(r'total\s+due\s*:?\s*\$?([0-9,]+\.?\d*)', content, re.IGNORECASE)
        if total_match:
            entities.append(ExtractedEntity(
                field_name="total_amount",
                value=float(total_match.group(1).replace(',', '')),
                confidence=0.85,
                context="footer",
                validation_status="needs_check"
            ))
        
        # Payment terms
        terms_match = re.search(r'payment\s+terms\s*:?\s*(\w+)', content, re.IGNORECASE)
        if terms_match:
            entities.append(ExtractedEntity(
                field_name="payment_terms",
                value=terms_match.group(1),
                confidence=0.80,
                context="footer",
                validation_status="needs_check"
            ))
            
        return entities

    def _extract_contract_entities(self, content: str) -> List[ExtractedEntity]:
        """Extract contract-specific entities."""
        entities = []
        
        # Agreement date
        date_match = re.search(r'agreement\s+date\s*:?\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})', content, re.IGNORECASE)
        if date_match:
            entities.append(ExtractedEntity(
                field_name="agreement_date",
                value=date_match.group(1),
                confidence=0.85,
                context="header",
                validation_status="needs_check"
            ))
            
        return entities

    def _extract_receipt_entities(self, content: str) -> List[ExtractedEntity]:
        """Extract receipt-specific entities."""
        entities = []
        
        # Receipt number
        receipt_match = re.search(r'receipt\s*#?\s*([A-Z0-9\-]+)', content, re.IGNORECASE)
        if receipt_match:
            entities.append(ExtractedEntity(
                field_name="receipt_number",
                value=receipt_match.group(1),
                confidence=0.90,
                context="header",
                validation_status="needs_check"
            ))
            
        return entities

    def _extract_bank_entities(self, content: str) -> List[ExtractedEntity]:
        """Extract bank statement entities."""
        entities = []
        
        # Account number (masked)
        account_match = re.search(r'account\s+number\s*:?\s*(\*+\d{4})', content, re.IGNORECASE)
        if account_match:
            entities.append(ExtractedEntity(
                field_name="account_number",
                value=account_match.group(1),
                confidence=0.95,
                context="header",
                validation_status="needs_check"
            ))
            
        return entities

    def _extract_generic_entities(self, content: str) -> List[ExtractedEntity]:
        """Extract generic entities."""
        entities = []
        
        # Document type
        entities.append(ExtractedEntity(
            field_name="document_type",
            value="unknown",
            confidence=0.50,
            context="document_structure",
            validation_status="needs_check"
        ))
        
        return entities

    def _validate_extraction(self, entities: List[ExtractedEntity], doc_type: DocumentType) -> List[str]:
        """Validate extracted entities for completeness."""
        errors = []
        
        # Required fields by document type
        required_fields = {
            DocumentType.INVOICE: ["invoice_number", "total_amount"],
            DocumentType.CONTRACT: ["agreement_date"],
            DocumentType.RECEIPT: ["receipt_number"],
            DocumentType.BANK_STATEMENT: ["account_number"]
        }
        
        if doc_type in required_fields:
            entity_fields = [e.field_name for e in entities]
            for required in required_fields[doc_type]:
                if required not in entity_fields:
                    errors.append(f"Missing required field: {required}")
                    
        return errors

    def _make_routing_decision(self, classification: DocumentClassification, validation_errors: List[str]) -> Dict:
        """Make routing decision based on confidence and validation."""
        confidence = classification.confidence
        confidence_level = classification.confidence_level
        
        # High confidence + no validation errors = auto process
        if confidence_level == ConfidenceLevel.HIGH and len(validation_errors) == 0:
            return {
                "destination": "automated_processing",
                "needs_review": False
            }
        
        # Medium confidence or minor validation issues = review queue
        elif confidence_level == ConfidenceLevel.MEDIUM or len(validation_errors) <= 2:
            return {
                "destination": "review_queue",
                "needs_review": True
            }
        
        # Low confidence or major validation issues = human review required
        else:
            return {
                "destination": "human_review",
                "needs_review": True
            }

    def _calculate_avg_confidence(self, entities: List[ExtractedEntity]) -> float:
        """Calculate average confidence from extracted entities."""
        if not entities:
            return 0.0
        return sum(e.confidence for e in entities) / len(entities)


def process_document(file_path: str) -> ProcessedDocument:
    """
    Convenience function to process a document.
    """
    processor = DocumentIntakeProcessor()
    return processor.process_document(file_path)