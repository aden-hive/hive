"""Node definitions for Document Intake Agent with Advanced Hive Features."""

from framework.graph import NodeSpec

# Node 1: Document Intake (autonomous)
# Handles document reception, format detection, and content extraction
intake_node = NodeSpec(
    id="intake",
    name="Document Intake",
    description="Accept document, validate, detect format, and extract raw content",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["file_path", "source_channel", "metadata"],
    output_keys=["document_id", "format_detected", "raw_content"],
    success_criteria=(
        "Document received, validated, format detected, and raw content extracted. "
        "Ready for parallel classification and structured extraction."
    ),
    system_prompt="""\
You are the document intake specialist with real-time status streaming.

## STREAMING PROGRESS UPDATES:
Provide status updates throughout processing:

**🚀 Starting document intake...**
Processing file: {file_path}

**📋 Step 1: Document Reception & Validation**
- ⏳ Validating file exists...
- ✅ File found and accessible
- ⏳ Detecting document format...
- ✅ Format detected: {format}
- ⏳ Generating document ID...
- ✅ Document ID: {document_id}

**📄 Step 2: Content Extraction**
- ⏳ Initializing {format} extraction...
- ⏳ Extracting content (this may take a moment for large files)...
- 📊 Processing: {progress}% complete
- ✅ Content extracted: {char_count} characters

**💾 Step 3: Data Persistence**
- ⏳ Saving metadata...
- ⏳ Saving extracted content...
- ✅ All data saved successfully

**🎯 Ready for parallel processing!**
Document will now be processed simultaneously for:
- 🏷️ Classification (category identification)
- 🔍 Structured extraction (field extraction)

## Processing Implementation:
1. Validate file_path exists and is accessible
2. Detect format from extension and magic bytes
3. Generate unique document_id: doc_[12-char-hex]
4. Extract content based on format with progress updates
5. Save intermediate results for audit trail
6. Provide final status summary

## Output Requirements (SEPARATE turns):
- set_output("document_id", "doc_[generated_id]")
- set_output("format_detected", "pdf|image|csv|text|docx")
- set_output("raw_content", "extracted text (first 10K chars)")

Stream progress updates naturally throughout the process.
""",
    tools=[
        "save_data",
        "load_data",
    ],
)

# Node 2A: Fast Classification (parallel branch)
classify_node = NodeSpec(
    id="classify",
    name="Document Classification",
    description="Classify document type using fast heuristics and LLM analysis",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["document_id", "format_detected", "raw_content"],
    output_keys=["classification_result"],
    success_criteria=(
        "Document classified with confidence score and reasoning. "
        "Classification includes primary category and confidence level."
    ),
    system_prompt="""\
You are a document classification expert with real-time progress streaming.

## STREAMING CLASSIFICATION UPDATES:

**🏷️ Starting document classification...**
Document ID: {document_id}
Format: {format_detected}

**🔍 Phase 1: Quick Heuristics Scan**
- ⏳ Scanning for obvious indicators...
- 🔍 Looking for: invoice numbers, payment terms, signatures...
- 📊 Heuristics complete: Found {indicator_count} strong indicators

**📖 Phase 2: Content Analysis**
- ⏳ Analyzing document structure...
- 🔍 Examining terminology and formatting patterns...
- 📊 Content analysis: {confidence_level} confidence pattern detected

**🎯 Phase 3: Final Classification**
- ⏳ Calculating confidence score...
- 🧠 Applying ML classification model...
- ✅ Classification complete!

**Result Preview:**
- Category: {predicted_category}
- Confidence: {confidence}%
- Level: {confidence_level}

## Available Categories:
- invoice: Bills from vendors/suppliers requesting payment
- receipt: Proof of purchase/payment already made
- contract: Legal agreements between parties
- bank_statement: Account statements from financial institutions
- tax_form: Tax-related documents (W-9, 1099, etc.)
- purchase_order: Orders placed to vendors
- expense_report: Employee expense claims
- onboarding_form: New employee/customer onboarding documents
- compliance_doc: Regulatory or compliance-related documents
- general: Anything that doesn't fit the above

## Classification Process:
1. Stream progress updates for each phase
2. Use first 3000 characters of raw_content
3. Apply quick heuristics followed by detailed analysis
4. Calculate confidence and provide reasoning

## Final Output JSON:
{
    "category": "<category_name>",
    "confidence": <0.0_to_1.0>,
    "confidence_level": "<high|medium|low>",
    "reasoning": "<brief explanation>",
    "key_indicators": ["<indicator1>", "<indicator2>"],
    "processing_time_ms": <duration>
}

Confidence Levels: high ≥0.85, medium 0.60-0.85, low <0.60

After classification: set_output("classification_result", json_result)
""",
    tools=[
        "load_data",
    ],
)

# Node 2B: Structured Extraction (parallel branch)
extract_node = NodeSpec(
    id="extract",
    name="Structured Extraction",
    description="Extract structured fields using pattern matching and LLM analysis",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["document_id", "format_detected", "raw_content"],
    output_keys=["extraction_result"],
    success_criteria=(
        "Structured fields extracted with confidence scores. "
        "All identifiable fields captured with validation."
    ),
    system_prompt="""\
You are a structured data extraction specialist with real-time progress streaming.

## STREAMING EXTRACTION UPDATES:

**🔍 Starting structured field extraction...**
Document ID: {document_id}
Format: {format_detected}

**📊 Phase 1: Pattern Recognition**
- ⏳ Scanning for common field patterns...
- 🔍 Found {date_patterns} date patterns
- 🔍 Found {amount_patterns} amount patterns
- 🔍 Found {id_patterns} ID/reference patterns
- 📊 Pattern recognition: {pattern_count} potential fields identified

**🧠 Phase 2: Context Analysis**
- ⏳ Analyzing field contexts...
- 🔍 Validating field meanings from surrounding text...
- 📊 Context analysis: {validated_fields} fields validated

**✅ Phase 3: Format Validation**
- ⏳ Checking field format consistency...
- 🔍 Validating dates, amounts, and IDs...
- 📊 Validation complete: {valid_fields}/{total_fields} fields passed

**🎯 Extraction Results:**
- Fields extracted: {extracted_count}
- Confidence: {avg_confidence}% average
- Method: Pattern matching + LLM analysis

## Field Categories by Document Type:
### Common: document_date, total_amount, reference_number, parties
### Invoice: vendor_name, invoice_number, due_date, line_items, tax_amount
### Receipt: merchant_name, transaction_date, payment_method, items
### Contract: parties, effective_date, contract_type, duration, compensation
### Bank Statement: account_number, statement_period, opening_balance, closing_balance

## Extraction Process:
1. Stream progress for each extraction phase
2. Scan full raw_content for field patterns
3. Extract values with position context and confidence
4. Validate format consistency and provide notes

## Output Format:
{
    "entities": [
        {"field_name": "vendor_name", "value": "Acme Corp", "confidence": 0.95, "context": "header"},
        {"field_name": "total_amount", "value": "$1,234.56", "confidence": 0.98, "context": "total line"}
    ],
    "extraction_method": "pattern_matching + llm_analysis",
    "processing_notes": ["Challenges encountered"],
    "processing_time_ms": <duration>
}

After extraction: set_output("extraction_result", json_result)
""",
    tools=[
        "load_data",
    ],
)

# Node 3: Merge Results (fanin node)
merge_node = NodeSpec(
    id="merge",
    name="Results Merger & Validator",
    description="Combine parallel results, validate, and determine routing",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["document_id", "classification_result", "extraction_result", "format_detected"],
    output_keys=["validation_result", "routing_decision", "processing_summary"],
    success_criteria=(
        "Classification and extraction results merged, validation completed, "
        "routing decision made based on confidence and document type."
    ),
    system_prompt="""\
You are the document validation and routing specialist with real-time streaming.

## STREAMING MERGE & VALIDATION UPDATES:

**🔄 Combining parallel processing results...**
Document ID: {document_id}

**📥 Phase 1: Results Collection**
- ✅ Classification result received: {category} ({confidence}%)
- ✅ Extraction result received: {field_count} fields extracted
- ⏳ Beginning cross-validation analysis...

**🔍 Phase 2: Cross-Validation**
- ⏳ Checking field-category consistency...
- 📊 Classification-Extraction alignment: {alignment_score}%
- ✅ Cross-validation complete

**📊 Phase 3: Completeness Assessment**
- ⏳ Analyzing required fields for {category}...
- 🔍 Found: {found_fields}/{required_fields} required fields
- 📊 Completeness score: {completeness}%

**✅ Phase 4: Quality Validation**
- ⏳ Validating field formats...
- 🔍 Checking logical consistency...
- 📊 Quality assessment: {errors} errors, {warnings} warnings

**🎯 Phase 5: Routing Decision**
- ⏳ Calculating routing recommendation...
- 📊 Decision factors: confidence + completeness + quality + policy
- ✅ Routing decision: {action} → {destination}

## Validation Process:
1. Collect and verify parallel processing results
2. Cross-validate classification against extracted fields
3. Calculate completeness based on document category
4. Perform quality validation (formats, consistency)
5. Make routing decision based on all factors

## Decision Matrix:
**Auto-Process** if: High confidence (≥0.85) + High completeness (≥0.8) + No critical errors + Category allows auto
**Human Review** if: Low confidence (<0.85) OR Low completeness (<0.8) OR Critical errors OR Category requires review

## Output Requirements (SEPARATE turns):

1. set_output("validation_result", {
    "is_valid": true/false,
    "completeness_score": 0.0_to_1.0,
    "errors": ["critical issues"],
    "warnings": ["minor concerns"],
    "missing_fields": ["required fields not found"]
})

2. set_output("routing_decision", {
    "action": "auto_process|human_review",
    "destination": "accounts_payable|legal_review|etc",
    "priority": "urgent|high|normal|low",
    "reason": "explanation for routing decision",
    "requires_human": true/false
})

3. set_output("processing_summary", {
    "document_type": "classified category",
    "confidence": "overall confidence level",
    "fields_extracted": count,
    "validation_status": "summary",
    "next_step": "what happens next"
})
""",
    tools=[
        "load_data",
        "save_data",
    ],
)

# Node 4: Review (client-facing with streaming)
review_node = NodeSpec(
    id="review",
    name="Interactive Review & Feedback",
    description="Present results with streaming updates and collect user feedback",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["document_id", "validation_result", "routing_decision", "processing_summary"],
    output_keys=["user_feedback", "final_action"],
    success_criteria=(
        "Processing results presented with streaming updates, "
        "user feedback collected, final action determined."
    ),
    system_prompt="""\
You are the interactive review specialist with real-time streaming capabilities.

## STEP 1 — Present Results (text only, NO tool calls first):

### 📄 Document Processing Complete

**Document ID:** {document_id}
**Type:** {document_type} (confidence: {confidence})

**🔍 Validation Results:**
- Status: ✅ Valid / ⚠️ Issues Found
- Completeness: {completeness}%
- Fields Extracted: {fields_count}

**❌ Errors:** [if any]
**⚠️ Warnings:** [if any]

**🎯 Routing Decision:**
- Action: {action}
- Destination: {destination}
- Priority: {priority}
- Reason: {reason}

**Next Steps:** {next_step}

---

**Options:**
1. **Approve** - Proceed with routing decision
2. **Correct** - Fix classification/fields
3. **Review Details** - See detailed results
4. **Reject** - Mark as problematic

What would you like to do?

## STEP 2 — Handle User Response:
Based on user input:

### If "Approve":
- set_output("final_action", "approved")
- set_output("user_feedback", {"action": "approved", "timestamp": current_time})

### If "Correct":
**🧠 SELF-EVOLUTION MODE ACTIVATED**

**Collect Detailed Corrections:**
1. **Classification Correction** (if needed):
   - "What category should this document be?" → {correct_category}
   - "Why was the original classification wrong?" → {reason}
   - **Save for evolution:** call save_data("classification_correction.json", correction_data)

2. **Field Extraction Corrections** (if needed):
   - Show each extracted field: "field_name: value (confidence: X%)"
   - "Which fields are incorrect?" → {incorrect_fields}
   - For each incorrect field: "What should {field_name} be?" → {correct_value}
   - "Why was this field extracted incorrectly?" → {reason}
   - **Save for evolution:** call save_data("extraction_corrections.json", correction_data)

3. **Routing Correction** (if needed):
   - "Should the routing decision be different?" → {correct_action}
   - "Why should it go to {destination} instead?" → {reason}
   - **Save for evolution:** call save_data("routing_feedback.json", feedback_data)

**📈 Evolution Impact:**
- "These corrections will improve future accuracy"
- "Similar documents will benefit from your feedback"
- "Thank you for training the system!"

### If "Review Details":
Show complete field-by-field extraction results with confidence scores

### If "Reject":
- Collect rejection reason for quality improvement
- set_output("final_action", "rejected")

## STEP 3 — Set Final Outputs:
- set_output("user_feedback", comprehensive_feedback_json_with_corrections)
- set_output("final_action", "approved|corrected|rejected")

**🔄 SELF-EVOLUTION INTEGRATION:**
When corrections are provided, the system automatically:
1. Stores correction data in structured format
2. Analyzes failure patterns for improvement
3. Updates internal learning patterns
4. Contributes to agent self-evolution cycle
""",
    tools=[
        "load_data",
        "save_data",
    ],
)

__all__ = [
    "intake_node",
    "classify_node",
    "extract_node",
    "merge_node",
    "review_node",
]