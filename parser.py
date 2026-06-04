"""
agents/parser.py

Stage 2: Combined document classification + field extraction.
One Claude API call per document. No two-step classify-then-extract.

This implements the file's biggest efficiency win:
- Classify and extract in a single pass
- Tight schema, small output surface
- Hard anti-hallucination constraints
- Citations required for every extracted value

Output feeds directly into Defender and Prosecutor agents.
"""

from claude_client import call_claude

# ── Prompts (from the file, kept tight) ───────────────────────────────────────

SYSTEM_PROMPT = """You are an insurance claims document parser.

You will receive raw text extracted from ONE PDF document.

Your tasks:
1. Identify the document type
2. Extract structured fields
3. Provide exact source citations for extracted values
4. Detect whether the document is unusable

Rules:
- Extract ONLY information explicitly present in the text
- Never infer missing values
- If uncertain, return null
- Citations must be exact short quotes copied from the document
- Dates must be in YYYY-MM-DD format where possible
- Amounts must be numbers only, no currency symbols or commas (e.g. 8450.00)
- Return ONLY valid JSON
- No markdown
- No explanations
- No extra text
- Output must match schema exactly

Field extraction rules by document type:
- coverage_start_date and coverage_end_date: ONLY extract from insurance_form documents. Never extract from payslips, invoices, or any other type. A payslip pay period is NOT a coverage date.
- invoice_date: the date the invoice was ISSUED, not the treatment date
- treatment_date: the date the patient received treatment or was admitted
- claim_amount: the total amount claimed or billed, not salary or any other amount
- monthly_salary: ONLY extract from payslip documents
- employer_name: ONLY extract from payslip documents
- physician_name: ONLY extract from patient_record, invoice, or treatment_summary
- For payslip documents: set coverage_start_date, coverage_end_date, treatment_date, invoice_date, invoice_number, diagnosis_code, claim_amount all to null

Valid document types:
- invoice
- patient_record
- insurance_form
- payslip
- treatment_summary
- unknown

If the document is corrupted, blank, unrelated, or unreadable:
- set unusable to true
- explain briefly in unusable_reason"""

USER_TEMPLATE = """Parse this insurance claim document.

DOCUMENT TEXT:
---
{raw_text}
---

Return this exact JSON and nothing else:
{{
  "doc_type": "",
  "confidence": 0.0,
  "unusable": false,
  "unusable_reason": null,
  "fields": {{
    "patient_name": null,
    "patient_dob": null,
    "policy_number": null,
    "claim_amount": null,
    "treatment_date": null,
    "invoice_date": null,
    "invoice_number": null,
    "diagnosis_code": null,
    "physician_name": null,
    "employer_name": null,
    "monthly_salary": null,
    "coverage_start_date": null,
    "coverage_end_date": null
  }},
  "citations": {{}},
  "missing_required_fields": []
}}"""

# Fields expected per document type — used to compute missing_required_fields
# if Claude doesn't fill it in correctly
EXPECTED_FIELDS = {
    "invoice":           ["patient_name", "claim_amount", "invoice_date", "invoice_number"],
    "patient_record":    ["patient_name", "patient_dob", "diagnosis_code", "treatment_date"],
    "insurance_form":    ["patient_name", "policy_number", "coverage_start_date", "coverage_end_date"],
    "treatment_summary": ["patient_name", "treatment_date", "diagnosis_code", "physician_name"],
    "payslip":           ["patient_name", "employer_name", "monthly_salary"],
    "unknown":           []
}


def parse_document(raw_text: str, filename: str) -> dict:
    """
    Classify and extract fields from a single document in one API call.

    Returns a document dict that the Defender and Prosecutor agents consume:
    {
        filename, doc_type, confidence, unusable, unusable_reason,
        fields, citations, missing_required_fields, parse_error (if any)
    }
    """
    # Truncate to keep tokens manageable — first 3000 chars is enough
    # for classification + key field extraction on any of our doc types
    truncated = len(raw_text) > 3000
    text_sample = raw_text[:3000] if truncated else raw_text

    result = call_claude(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=USER_TEMPLATE.format(raw_text=text_sample),
        max_tokens=1500
    )

    if result["ok"]:
        data = result["data"]

        doc_type = data.get("doc_type", "unknown")
        fields   = data.get("fields", {})

        # Sanitise numeric fields that might come back as strings
        fields = _sanitise_numerics(fields)

        # Recalculate missing_required_fields as safety net
        # (Claude sometimes gets this wrong)
        expected = EXPECTED_FIELDS.get(doc_type, [])
        missing  = [f for f in expected if not fields.get(f)]

        # Clamp confidence to [0.0, 1.0]
        try:
            conf = float(data.get("confidence", 0.5))
        except Exception:
            conf = 0.5
        conf = max(0.0, min(1.0, conf))

        return {
            "filename":              filename,
            "doc_type":              doc_type,
            "confidence":            conf,
            "unusable":              bool(data.get("unusable", False)),
            "unusable_reason":       data.get("unusable_reason"),
            "fields":                fields,
            "citations":             data.get("citations", {}),
            "missing_required_fields": missing,
            "truncated":             truncated,
            "parse_error":           None
        }

    # Fallback — mark as unusable so downstream agents skip it cleanly
    print(
    f"[PARSE FAIL] file={filename} "
    f"error={result.get('error', 'Unknown')} "
    f"raw={result.get('raw', '')[:200]}",
    flush=True
    )
    
    return {
        "filename":              filename,
        "doc_type":              "unknown",
        "confidence":            0.0,
        "unusable":              True,
        "unusable_reason":       f"Parsing failed: {result.get('error', 'Unknown error')}",
        "fields":                {},
        "citations":             {},
        "missing_required_fields": [],
        "parse_error":           result.get("error")
    }


def _sanitise_numerics(fields: dict) -> dict:
    """Strip currency symbols and commas from numeric fields."""
    for key in ["claim_amount", "monthly_salary"]:
        val = fields.get(key)
        if val is None:
            continue
        if isinstance(val, str):
            cleaned = val.replace(",", "").replace("$", "") \
                         .replace("USD", "").replace("AED", "").strip()
            try:
                fields[key] = float(cleaned)
            except ValueError:
                fields[key] = None
    return fields
