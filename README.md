# AI Insurance Claim Verification System

LIVE URL: https://web-production-4392e.up.railway.app/
A Flask web application that automates insurance claim verification using a multi-agent pipeline built on Gemini 2.5 Flash. Documents are uploaded, parsed, and independently evaluated by an approval-focused agent and a risk-focused agent before deterministic Python rules produce a final verdict. Routine claims are auto-approved; suspicious ones are escalated to a human review queue.

---

## How the Pipeline Works

```
Upload PDFs
    │
    ▼
pdf_reader.py          Extract text from each PDF (pdfplumber)
    │
    ▼
supabase_storage.py    Upload raw bytes to Supabase Storage
    │
    ▼
parser.py              Classify doc type + extract structured fields (1 AI call per doc)
    │
    ├──────────────────────────────────────┐
    ▼                                      ▼
defender.py                          prosecutor.py
Build strongest approval case        Find all inconsistencies & fraud indicators
(1 AI call across all docs)          (1 AI call across all docs)
    │                                      │
    └──────────────────┬───────────────────┘
                       │
                       ▼
validators.py          Deterministic hard rule checks (pure Python, no AI)
                       Flags merged into prosecutor output
                       │
                       ▼
synthesiser.py         Pure Python verdict + confidence score + human checklist
                       → RECOMMEND_APPROVE | MANUAL_REVIEW | RECOMMEND_REJECT
                       │
                       ▼
                 SSE stream → frontend
```

Results stream to the browser via Server-Sent Events. The frontend renders a status card on completion. Claims that reach `MANUAL_REVIEW` appear in the admin review queue.

---

## Project Structure

Only the files that matter for understanding the code:

```
app.py                  Entry point. Flask routes + pipeline orchestration.
                        Reads file bytes once, coordinates all pipeline stages,
                        streams SSE events back to the browser.

parser.py               Stage 2. One Gemini call per document: classify doc type
                        and extract structured fields with citations. Sanitises
                        numeric fields and recalculates missing required fields.

defender.py             Stage 3a. One Gemini call across all docs. Builds the
                        strongest evidence-based case for approving the claim.

prosecutor.py           Stage 3b. One Gemini call across all docs. Finds
                        inconsistencies, policy violations, and fraud indicators.
                        Also contains merge_hard_rule_flags() which combines
                        deterministic flags into the prosecutor output.

validators.py           Hard rule checks. Pure Python, no AI. Runs seven checks:
                        missing required docs, amount exceeds limit, treatment
                        outside coverage window, invoice before treatment date,
                        patient name mismatch, out-of-network physician.
                        Flag IDs (HR001–HR007) are referenced by synthesiser.py
                        for weighted confidence scoring.

synthesiser.py          Stage 4. Pure Python. Applies escalation rules, computes
                        a weighted confidence score, builds the human checklist,
                        and produces the final triage card JSON. No AI call.

claude_client.py        Gemini API wrapper (via Vertex AI). Despite the name,
                        calls Gemini 2.5 Flash — not Claude. Handles auth from
                        GCP_SERVICE_ACCOUNT_JSON env var, JSON response parsing,
                        and retries with exponential backoff.

db.py                   Database layer. psycopg2 + Supabase Postgres. Manages
                        claimants, claims, verdict storage, worker decisions.

supabase_storage.py     Uploads PDFs to Supabase Storage. Generates 7-day signed
                        URLs. Accepts raw bytes (not file streams) to avoid the
                        stream-exhaustion bug after pdf_reader consumes the stream.

pdf_reader.py           Extracts and cleans text from PDF bytes using pdfplumber.
                        Returns a structured result with success flag, text, page
                        count, and failure reason.

schema.sql              Postgres schema. Two tables: claimants and claims.
                        Includes the ALTER statement that migrated from
                        drive_folder_id to storage_files_json.

templates/
├── index.html          Claim submission form. Two-panel layout. Handles file
│                       upload, SSE event parsing, and renders the result card
│                       inline in a modal (no page navigation needed).
├── admin.html          Manual review queue. Card grid with confidence rings,
│                       risk-tier colour coding, per-claim modals showing flags,
│                       verified factors, document links, and the approve/reject/
│                       escalate decision form.
└── user_result.html    Standalone result page. Rendered server-side via
                        /render-user-result. Superseded in practice by the
                        inline modal in index.html; kept for direct URL access.

Procfile                Gunicorn config for Railway deployment.
                        1 worker, 4 threads, 120s timeout (required for long
                        AI pipeline runs).
```

**Not worth looking at:**
- `generate_claim_docs.py` — generates sample PDFs for testing using reportlab; not part of the live system
- `drive_client.py` — Google Drive upload client, fully replaced by `supabase_storage.py`; no longer called anywhere

---

## Key Design Decisions

**Why three separate AI calls instead of one?**
Parser, Defender, and Prosecutor each have narrow, focused prompts. A single prompt asking for classification, approval arguments, and risk flags simultaneously produces less reliable output. The separation also means each agent can be replaced or tuned independently.

**Why does the synthesiser have no AI call?**
Verdicts are business-critical decisions. `synthesiser.py` applies explicit escalation rules (e.g. any HIGH flag → `MANUAL_REVIEW`, fraud pattern + HIGH → `RECOMMEND_REJECT`) and computes confidence from a weighted deduction table keyed to specific flag IDs. This makes outcomes auditable and deterministic.

**Why is the file bytes read order important?**
`pdf_reader.extract_text_from_bytes()` consumes the file stream. `app.py` reads raw bytes once into `raw_docs["file_bytes"]` before calling the reader, so the same bytes can later be passed to `supabase_storage.upload_claim_files()` without re-reading a spent stream.

**Why does `claude_client.py` call Gemini?**
The module was originally written for Claude and later migrated to Gemini 2.5 Flash via the Vertex AI Gemini SDK. The filename is a leftover from the migration.

---

## Verdict Logic (synthesiser.py)

Rules are applied in priority order:

| Condition | Verdict |
|---|---|
| Any HIGH flag with a `fraud_pattern` | `RECOMMEND_REJECT` |
| Any HIGH flag | `MANUAL_REVIEW` |
| 2+ MEDIUM flags | `MANUAL_REVIEW` |
| Defender has `unable_to_defend` items | `MANUAL_REVIEW` |
| Defender confidence < 0.5 and any flag exists | `MANUAL_REVIEW` |
| Either AI agent errored | `MANUAL_REVIEW` |
| None of the above | `RECOMMEND_APPROVE` |

---

## Hard Rules (validators.py)

| ID | Severity | Check |
|---|---|---|
| HR001 | HIGH | Required document type missing (`invoice`, `insurance_form`) |
| HR002 | HIGH | Claim amount exceeds USD 50,000 policy maximum |
| HR003 | HIGH | Treatment date before coverage start date |
| HR004 | HIGH | Treatment date after policy expiry |
| HR005 | MEDIUM | Invoice date before treatment date (pre-treatment billing pattern) |
| HR006 | HIGH | Patient name mismatch across documents (< 80% string similarity) |
| HR007 | LOW | Attending physician not on approved provider network |

---

## Supported Document Types

The parser recognises five document types:

| Type | Key fields extracted |
|---|---|
| `invoice` | `patient_name`, `claim_amount`, `invoice_date`, `invoice_number` |
| `patient_record` | `patient_name`, `patient_dob`, `diagnosis_code`, `treatment_date` |
| `insurance_form` | `patient_name`, `policy_number`, `coverage_start_date`, `coverage_end_date` |
| `treatment_summary` | `patient_name`, `treatment_date`, `diagnosis_code`, `physician_name` |
| `payslip` | `patient_name`, `employer_name`, `monthly_salary` |

Coverage dates are only extracted from `insurance_form` documents. A payslip pay period is never treated as a coverage date.

---

## Routes

| Route | Method | Description |
|---|---|---|
| `/` | GET | Claim submission form (`index.html`) |
| `/process-claim` | POST | Main pipeline endpoint. Accepts multipart PDF upload, returns SSE stream |
| `/review-dashboard` | GET | Admin review queue — shows all `MANUAL_REVIEW` claims without a worker decision |
| `/worker-action` | POST | Record reviewer decision (`approved`, `rejected`, `escalated`) |
| `/render-user-result` | POST | Server-side render of `user_result.html` (superseded by inline modal) |
| `/health` | GET | Health check — returns model name and status |

---

## Environment Variables

```bash
GCP_SERVICE_ACCOUNT_JSON    # Full GCP service account JSON string (not a file path)
GOOGLE_CLOUD_LOCATION       # Vertex AI region, default: us-central1
GEMINI_MODEL                # Model name, default: gemini-2.5-flash
SUPABASE_URL                # Supabase project URL
SUPABASE_SERVICE_KEY        # Supabase service role key (not anon key)
DATABASE_URL                # Postgres connection string (from Supabase)
```

---

## Database Schema

Two tables. See `schema.sql` for the full definition.

**`claimants`** — `id`, `full_name`, `email`, `phone`, `national_id`, `created_at`

**`claims`** — `id`, `claimant_id`, `status` (enum), `verdict`, `submitted_at`, `reviewed_at`, `worker_decision`, `worker_notes`, `result_json` (full pipeline output), `documents_json`, `storage_files_json` (Supabase upload results with signed URLs), `error_log`

---

## Getting Started

**Prerequisites:** Python 3.11+, a Supabase project, a GCP project with Vertex AI enabled

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create .env with the required variables (see above)

# 3. Run schema.sql in your Supabase SQL editor

# 4. Create a private Storage bucket named "claims" in Supabase dashboard

# 5. Run locally
python app.py
# → http://localhost:5000

# 6. Generate sample test documents (optional)
python generate_claim_docs.py
# → outputs to sample_claim_docs/ (gitignored)
```

### Deploy to Railway

The `Procfile` is already configured:
```
web: gunicorn app:app --timeout 120 --workers 1 --worker-class gthread --threads 4
```
Set all environment variables in the Railway dashboard. The 120s timeout is required for pipeline runs with multiple documents.
