# AI Insurance Claim Verification System

An AI-powered platform that automates the insurance claim verification workflow from document intake to review recommendation.

The system processes claim documents, extracts and validates information, identifies inconsistencies and potential fraud indicators, and generates evidence-backed recommendations for human reviewers. Routine claims can be handled automatically, allowing reviewers to focus on suspicious or escalated cases.

To improve reliability, the platform uses a multi-agent architecture built on Gemini 2.5 Flash. Specialized agents independently extract information, build approval arguments, and identify risks before deterministic Python-based validation rules produce the final recommendation.

---

## Key Features

* Automated insurance claim verification workflow
* Multi-agent claim analysis using Gemini 2.5 Flash
* Support for multiple insurance document types
* Citation-grounded information extraction
* Fraud and inconsistency detection
* Deterministic rule-based validation
* Human review workflow for escalated claims
* Real-time processing updates using Server-Sent Events (SSE)
* Reviewer dashboard with decision recording
* Cloud deployment using Railway and Supabase

---

## System Architecture

```text
                    Claim Documents
                           │
                           ▼
                ┌────────────────────┐
                │ PDF Text Extraction│
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │   Parser Agent     │
                │ Gemini 2.5 Flash   │
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │ Hard Rule Checks   │
                │      Python        │
                └──────┬───────┬─────┘
                       │       │
                       ▼       ▼

              ┌────────────┐ ┌────────────┐
              │  Defender  │ │ Prosecutor │
              │   Agent    │ │   Agent    │
              └─────┬──────┘ └─────┬──────┘
                    │              │
                    └──────┬───────┘
                           ▼

                ┌────────────────────┐
                │  Recommendation    │
                │    Synthesis        │
                └─────────┬──────────┘
                          │
                          ▼

                ┌────────────────────┐
                │ Reviewer Dashboard │
                └────────────────────┘
```

---

## Workflow

### 1. Document Upload

Users upload claim-related documents through the web interface.

Supported document categories include:

* Medical invoices
* Patient records
* Insurance forms
* Payslips
* Treatment summaries

---

### 2. Document Parsing

The Parser Agent analyzes each uploaded document and:

* Identifies document type
* Extracts structured fields
* Generates supporting citations
* Detects unusable or incomplete documents

Every extracted field is linked back to evidence found in the original document.

Example:

```json
{
  "patient_name": "John Smith",
  "citation": "Patient Name: John Smith"
}
```

This allows reviewers to verify where extracted information originated.

---

### 3. Deterministic Validation

Before claim evaluation, rule-based checks are applied using Python.

Examples include:

* Missing required information
* Policy requirement checks
* Validation constraints
* Escalation conditions

Business-critical decisions are not delegated entirely to the language model.

---

### 4. Defender Agent

The Defender Agent builds the strongest evidence-based case for approving a claim.

Responsibilities:

* Find supporting evidence
* Correlate information across documents
* Highlight approval factors
* Assess claim completeness

---

### 5. Prosecutor Agent

The Prosecutor Agent attempts to challenge the claim.

Responsibilities:

* Detect inconsistencies
* Identify missing information
* Flag policy violations
* Surface potential fraud indicators

---

### 6. Recommendation Generation

The system combines:

* Parser output
* Defender findings
* Prosecutor findings
* Rule-based validation results

to produce a final recommendation.

Claims requiring additional review are escalated to human reviewers.

---

### 7. Human Review

Reviewers can:

* Inspect extracted evidence
* Review approval and risk arguments
* Examine policy violations
* Record final decisions

This ensures human oversight for higher-risk claims.

---

## Design Principles

### Multi-Agent Analysis

Instead of relying on a single prompt, the system assigns different responsibilities to specialized agents.

This creates a structured debate between approval-focused and risk-focused perspectives before a recommendation is produced.

### Citation-Grounded Extraction

All extracted information is linked to evidence from the original documents.

This improves transparency and reduces the risk of unsupported outputs.

### Deterministic Business Rules

Critical policy checks are implemented in Python rather than AI prompts.

This ensures consistent and auditable behavior.

### Human-in-the-Loop Review

Routine claims can be processed automatically, while suspicious cases are escalated for human review.

This reduces reviewer workload while maintaining oversight where it matters most.

---

## Technology Stack

### Backend

* Python
* Flask
* Gemini 2.5 Flash
* Server-Sent Events (SSE)

### Data Storage

* Supabase Postgres
* Supabase Storage

### Document Processing

* pdfplumber

### Deployment

* Railway

---

## Future Improvements

* Additional document types
* Advanced fraud detection models
* Historical claim pattern analysis
* Reviewer feedback learning loop
* Batch claim processing
* Explainability dashboards

---

## Goal

The goal of this project is to reduce the manual effort involved in insurance claim verification while maintaining transparency, auditability, and human oversight for high-risk decisions.
