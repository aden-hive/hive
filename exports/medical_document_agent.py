"""
Medical Document Intelligence Agent
====================================
A 4-node Hive pipeline that processes unstructured medical documents,
extracts key clinical information using NLP, validates with a human checkpoint,
and outputs structured insurance claim data.

Contribution by: Aishwarya Patwatkar
GitHub: github.com/AishwaryaPatwatkar

Pipeline Flow:
  intake → nlp_extraction → human_validation → structured_output

Use Case:
  Automates insurance claim pre-processing from raw medical documents
  (discharge summaries, prescriptions, lab reports) — reducing manual
  processing time and errors.
"""

import re
import json
from datetime import datetime
from typing import Optional


# ─────────────────────────────────────────────
# NODE 1: Document Intake
# Accepts raw medical document text or file path
# ─────────────────────────────────────────────
def intake_node(inputs: dict) -> dict:
    """
    Accepts a medical document as raw text or a .txt/.pdf file path.
    Normalises whitespace and detects document type.

    Inputs:
        document_text (str): Raw text of the medical document
        document_type (str, optional): 'discharge_summary' | 'prescription' |
                                       'lab_report' | 'auto' (default: 'auto')

    Outputs:
        cleaned_text (str): Normalised document text
        detected_type (str): Detected document category
        char_count (int): Length of document
        intake_timestamp (str): ISO timestamp of intake
    """
    raw_text: str = inputs.get("document_text", "")
    doc_type: str = inputs.get("document_type", "auto")

    if not raw_text.strip():
        raise ValueError("document_text cannot be empty.")

    # Normalise whitespace
    cleaned = re.sub(r'\s+', ' ', raw_text).strip()

    # Auto-detect document type from keywords
    if doc_type == "auto":
        lower = cleaned.lower()
        if any(k in lower for k in ["discharge", "admitted", "ward", "hospital stay"]):
            doc_type = "discharge_summary"
        elif any(k in lower for k in ["rx", "prescribed", "tablet", "capsule", "dosage"]):
            doc_type = "prescription"
        elif any(k in lower for k in ["result", "report", "lab", "test", "wbc", "rbc", "hemoglobin"]):
            doc_type = "lab_report"
        else:
            doc_type = "general_medical"

    return {
        "cleaned_text": cleaned,
        "detected_type": doc_type,
        "char_count": len(cleaned),
        "intake_timestamp": datetime.utcnow().isoformat()
    }


# ─────────────────────────────────────────────
# NODE 2: NLP Extraction
# Extracts structured clinical fields via regex + keyword heuristics
# Can be swapped for a fine-tuned NER model (spaCy / HuggingFace)
# ─────────────────────────────────────────────
def nlp_extraction_node(inputs: dict) -> dict:
    """
    Extracts key clinical fields from cleaned medical document text.

    Inputs:
        cleaned_text (str): Output from intake_node
        detected_type (str): Document category

    Outputs:
        patient_name (str)
        patient_age (str)
        diagnosis (list[str])
        medications (list[str])
        procedures (list[str])
        icd_codes (list[str]): ICD-10 codes if present
        date_of_service (str)
        treating_physician (str)
        hospital_name (str)
        extraction_confidence (str): 'high' | 'medium' | 'low'
    """
    text: str = inputs.get("cleaned_text", "")
    doc_type: str = inputs.get("detected_type", "general_medical")

    def find_pattern(pattern: str, text: str, default: str = "Not found") -> str:
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else default

    def find_list(keywords: list, text: str) -> list:
        found = []
        for kw in keywords:
            pattern = rf'{kw}[:\s]+([A-Za-z0-9\s,\-]+?)(?:\.|,|\n|;)'
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                items = [i.strip() for i in match.group(1).split(',') if i.strip()]
                found.extend(items)
        return list(set(found)) if found else ["Not detected"]

    # Extract ICD-10 codes (format: A00.0 – Z99.9)
    icd_pattern = r'\b([A-Z]\d{2}\.?\d{0,2})\b'
    icd_codes = list(set(re.findall(icd_pattern, text))) or ["Not found"]

    # Extract date patterns
    date_pattern = r'\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{4}-\d{2}-\d{2})\b'
    dates = re.findall(date_pattern, text)
    date_of_service = dates[0] if dates else "Not found"

    # Confidence scoring
    found_fields = sum([
        find_pattern(r'patient[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)', text) != "Not found",
        find_pattern(r'age[:\s]+(\d+)', text) != "Not found",
        icd_codes != ["Not found"],
        date_of_service != "Not found",
        find_pattern(r'(?:dr\.?|doctor)[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)', text) != "Not found",
    ])
    confidence = "high" if found_fields >= 4 else "medium" if found_fields >= 2 else "low"

    return {
        "patient_name": find_pattern(
            r'patient(?:\s+name)?[:\s]+([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)', text
        ),
        "patient_age": find_pattern(r'age[:\s]+(\d+)', text),
        "diagnosis": find_list(["diagnosis", "diagnosed with", "impression", "condition"], text),
        "medications": find_list(["medication", "prescribed", "drug", "medicine", "rx"], text),
        "procedures": find_list(["procedure", "surgery", "operation", "treatment performed"], text),
        "icd_codes": icd_codes,
        "date_of_service": date_of_service,
        "treating_physician": find_pattern(
            r'(?:dr\.?|doctor|physician)[:\s]+([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)', text
        ),
        "hospital_name": find_pattern(
            r'(?:hospital|clinic|medical center)[:\s]+([A-Za-z\s]+?)(?:\.|,|\n)', text
        ),
        "extraction_confidence": confidence
    }


# ─────────────────────────────────────────────
# NODE 3: Human-in-the-Loop Validation
# Pauses for clinician/admin review before claim submission
# Implements Hive's built-in intervention node pattern
# ─────────────────────────────────────────────
def human_validation_node(inputs: dict) -> dict:
    """
    Presents extracted fields to a human reviewer.
    In production Hive deployments, this triggers an intervention node
    that pauses execution and awaits human approval via the Hive TUI/API.

    Inputs:
        All outputs from nlp_extraction_node

    Outputs:
        validated (bool): Whether human approved
        corrections (dict): Any field corrections made by reviewer
        reviewer_notes (str): Free-text notes
        validated_data (dict): Final merged data after corrections
    """
    extracted = {k: v for k, v in inputs.items()}

    # ── In live Hive deployment this block is replaced by ──
    # ── the framework's intervention point mechanism       ──
    # ── Human sees a structured form and approves/edits   ──

    print("\n" + "="*60)
    print("  ⚕️  HUMAN VALIDATION CHECKPOINT")
    print("="*60)
    print("  Please review the extracted medical data below:")
    print()
    for field, value in extracted.items():
        if field != "extraction_confidence":
            display = ', '.join(value) if isinstance(value, list) else value
            print(f"  {field.replace('_', ' ').title():<25}: {display}")
    print()
    print(f"  Extraction Confidence: {extracted.get('extraction_confidence', 'N/A').upper()}")
    print("="*60)

    # Simulate approval (in real Hive this is async human input)
    # The agent pauses here until the reviewer submits via Hive's UI
    human_approved = True       # ← replaced by Hive intervention response
    corrections = {}            # ← reviewer field edits
    reviewer_notes = "Auto-approved in simulation mode."

    # Merge corrections into extracted data
    validated_data = {**extracted, **corrections}

    return {
        "validated": human_approved,
        "corrections": corrections,
        "reviewer_notes": reviewer_notes,
        "validated_data": validated_data
    }


# ─────────────────────────────────────────────
# NODE 4: Structured Output Generation
# Produces a clean insurance claim JSON ready for submission
# ─────────────────────────────────────────────
def structured_output_node(inputs: dict) -> dict:
    """
    Converts validated medical data into a structured insurance claim payload.
    Output is JSON-serialisable and ready for downstream API submission.

    Inputs:
        validated (bool)
        validated_data (dict)
        reviewer_notes (str)

    Outputs:
        claim_payload (dict): Structured insurance claim
        claim_id (str): Auto-generated unique claim reference
        output_timestamp (str): ISO timestamp
        status (str): 'ready_for_submission' | 'rejected_by_reviewer'
    """
    import uuid

    validated: bool = inputs.get("validated", False)
    data: dict = inputs.get("validated_data", {})
    notes: str = inputs.get("reviewer_notes", "")

    if not validated:
        return {
            "status": "rejected_by_reviewer",
            "claim_payload": None,
            "claim_id": None,
            "output_timestamp": datetime.utcnow().isoformat()
        }

    claim_payload = {
        "claim_reference": f"CLM-{uuid.uuid4().hex[:8].upper()}",
        "submission_date": datetime.utcnow().isoformat(),
        "patient": {
            "name": data.get("patient_name", "Unknown"),
            "age": data.get("patient_age", "Unknown"),
        },
        "clinical": {
            "diagnosis": data.get("diagnosis", []),
            "icd_10_codes": data.get("icd_codes", []),
            "procedures": data.get("procedures", []),
            "medications": data.get("medications", []),
            "date_of_service": data.get("date_of_service", "Unknown"),
        },
        "provider": {
            "physician": data.get("treating_physician", "Unknown"),
            "facility": data.get("hospital_name", "Unknown"),
        },
        "metadata": {
            "extraction_confidence": data.get("extraction_confidence", "low"),
            "reviewer_notes": notes,
            "pipeline": "medical_document_intelligence_agent_v1"
        }
    }

    return {
        "status": "ready_for_submission",
        "claim_payload": claim_payload,
        "claim_id": claim_payload["claim_reference"],
        "output_timestamp": datetime.utcnow().isoformat()
    }


# ─────────────────────────────────────────────
# PIPELINE RUNNER
# Chains all 4 nodes — mirrors Hive's node graph execution
# ─────────────────────────────────────────────
def run_pipeline(document_text: str, document_type: str = "auto") -> dict:
    """
    Executes the full 4-node Medical Document Intelligence pipeline.

    Args:
        document_text (str): Raw medical document content
        document_type (str): Optional document type hint

    Returns:
        dict: Final structured claim output
    """
    print("\n🚀 Starting Medical Document Intelligence Agent...\n")

    # Node 1
    print("📄 [Node 1/4] Document Intake...")
    intake_output = intake_node({
        "document_text": document_text,
        "document_type": document_type
    })
    print(f"   ✓ Detected type: {intake_output['detected_type']} | {intake_output['char_count']} chars\n")

    # Node 2
    print("🧠 [Node 2/4] NLP Extraction...")
    extraction_output = nlp_extraction_node(intake_output)
    print(f"   ✓ Confidence: {extraction_output['extraction_confidence'].upper()}")
    print(f"   ✓ ICD codes found: {extraction_output['icd_codes']}\n")

    # Node 3
    print("👤 [Node 3/4] Human Validation Checkpoint...")
    validation_output = human_validation_node(extraction_output)
    status = "APPROVED ✓" if validation_output["validated"] else "REJECTED ✗"
    print(f"   ✓ Reviewer decision: {status}\n")

    # Node 4
    print("📋 [Node 4/4] Generating Structured Output...")
    final_output = structured_output_node(validation_output)
    print(f"   ✓ Status: {final_output['status']}")
    print(f"   ✓ Claim ID: {final_output['claim_id']}\n")

    print("="*60)
    print("  ✅ Pipeline Complete!")
    print("="*60)
    print(json.dumps(final_output["claim_payload"], indent=2))

    return final_output


# ─────────────────────────────────────────────
# EXAMPLE USAGE
# ─────────────────────────────────────────────
if __name__ == "__main__":
    sample_document = """
    Patient Name: Priya Sharma
    Age: 34
    Hospital: Apollo Medical Center
    Date of Admission: 12/01/2025
    Date of Discharge: 15/01/2025

    Treating Physician: Dr. Rajesh Mehta

    Diagnosis: Type 2 Diabetes Mellitus with peripheral neuropathy
    ICD-10 Codes: E11.40, G63.2

    Procedures: HbA1c blood test, nerve conduction study

    Medications prescribed:
    - Metformin 500mg tablet, twice daily
    - Pregabalin 75mg capsule, once daily

    Lab Results: Fasting glucose 210 mg/dL, HbA1c 8.4%

    Discharge Condition: Stable. Follow-up in 4 weeks.
    """

    result = run_pipeline(sample_document)
