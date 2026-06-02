"""
app.py

Flask application — main entry point and pipeline orchestrator.

Pipeline (v2 merged architecture):
    Upload PDFs
        → Stage 2: parse_document()        per doc  (classify + extract, 1 AI call)
        → Stage 3a: run_defender()          1 AI call across all docs
        → Stage 3b: run_prosecutor()        1 AI call across all docs
        → Hard rules: run_hard_rules()      pure Python, no AI
        → merge_hard_rule_flags()           merge into prosecutor output
        → Stage 4: synthesise()             pure Python, no AI
        → Return triage card JSON to frontend
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from dotenv import load_dotenv

from pdf_reader import extract_text
from validators import run_hard_rules, POLICY_RULES
from parser import parse_document
from defender import run_defender
from prosecutor import run_prosecutor, merge_hard_rule_flags
from synthesiser import synthesise

load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB total upload limit

ALLOWED_EXTENSIONS = {"pdf"}
MAX_FILES = 10


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/process-claim', methods=['POST'])
def process_claim():
    """
    Main pipeline endpoint.
    Accepts multipart form upload of PDF files.
    Returns a triage card JSON object.
    """

    # ── Input validation ──────────────────────────────────────────────────────
    files = request.files.getlist('documents')

    if not files or all(f.filename == '' for f in files):
        return jsonify({"error": "No files uploaded."}), 400

    if len(files) > MAX_FILES:
        return jsonify({"error": f"Maximum {MAX_FILES} documents per claim."}), 400

    non_pdf = [f.filename for f in files if not allowed_file(f.filename)]
    if non_pdf:
        return jsonify({"error": f"Only PDF files accepted. Rejected: {', '.join(non_pdf)}"}), 400

    # ── Stage 1: Extract text from all PDFs ───────────────────────────────────
    raw_docs = []
    skipped  = []

    for f in files:
        extraction = extract_text(f)
        if extraction["success"]:
            raw_docs.append({
                "filename": f.filename,
                "text":     extraction["text"],
                "pages":    extraction["page_count"]
            })
        else:
            skipped.append({
                "filename": f.filename,
                "reason":   extraction["reason"]
            })

    if not raw_docs:
        return jsonify({
            "error": "Could not extract text from any uploaded files.",
            "detail": "All files appear to be scanned image PDFs or are corrupted. "
                      "Please upload text-layer PDFs.",
            "skipped": skipped
        }), 422

    def generate():
        yield _sse_event({
            "stage": "parsing",
            "message": f"Reading {len(raw_docs)} document(s)..."
        })

        # Stage 2: Parse documents in parallel because each document is independent.
        with ThreadPoolExecutor() as executor:
            parsed_docs = list(executor.map(
                lambda doc: parse_document(doc["text"], doc["filename"]),
                raw_docs
            ))

        # Check we have at least one usable document.
        usable = [d for d in parsed_docs if not d.get("unusable")]
        if not usable:
            yield _sse_event({
                "stage": "error",
                "error": "No documents could be classified. Manual review required.",
                "documents": parsed_docs
            })
            return

        yield _sse_event({
            "stage": "analysing",
            "message": "Running approval analysis..."
        })

        # Stage 3: Defender and prosecutor do not depend on each other.
        with ThreadPoolExecutor(max_workers=2) as executor:
            def_future = executor.submit(run_defender, parsed_docs, POLICY_RULES)
            pros_future = executor.submit(run_prosecutor, parsed_docs, POLICY_RULES)
            defender_output = def_future.result()
            prosecutor_output = pros_future.result()

        # Hard rule validation (deterministic, non-AI).
        hard_flags = run_hard_rules(parsed_docs)
        prosecutor_output = merge_hard_rule_flags(prosecutor_output, hard_flags)

        # Stage 4: Python synthesis — no AI.
        triage_card = synthesise(defender_output, prosecutor_output, parsed_docs)

        yield _sse_event({
            "stage": "complete",
            "triage_card": triage_card,
            "defender": defender_output,
            "prosecutor": prosecutor_output,
            "documents": parsed_docs,
            "skipped": skipped
        })

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/render-triage', methods=['POST'])
def render_triage():
    """Render the triage summary HTML from the triage payload posted by the frontend."""
    payload = request.get_json(force=True)
    triage = payload.get('triage_card', {}) if isinstance(payload, dict) else {}
    defender = payload.get('defender', {}) if isinstance(payload, dict) else {}
    prosecutor = payload.get('prosecutor', {}) if isinstance(payload, dict) else {}
    documents = payload.get('documents', []) if isinstance(payload, dict) else []

    # Build a combined text for simple heuristics
    combined = json.dumps([triage, defender, prosecutor])

    # Primary reason: prefer an explicit summary, else fallback
    primary_reason = triage.get('summary') or triage.get('reason') or (
        'See flagged issues in the summary below.' if combined else 'No summary available.'
    )

    # Secondary reasons heuristics
    secs = []
    if 'invoice' in combined.lower():
        secs.append('Possible pre-treatment billing')
    if 'physician' in combined.lower() or 'network' in combined.lower():
        secs.append('Attending physician appears out-of-network')
    if 'dob' in combined.lower() or 'date of birth' in combined.lower():
        secs.append('DOB mismatch across documents')
    secondary_reasons = '; '.join(secs) if secs else '—'

    # Evidence flags: try to extract simple key=value pairs from provided documents
    evidence_flags = []
    for d in documents:
        if isinstance(d, dict):
            fname = d.get('filename') or d.get('name') or str(d)
            # attempt to include a few common fields if present
            parts = []
            for k in ('invoice_date', 'treatment_date', 'dob', 'amount'):
                if k in d:
                    parts.append(f"{k} = {d[k]}")
            if parts:
                evidence_flags.append(f"{fname}: {'; '.join(parts)}")
            else:
                evidence_flags.append(fname)
        else:
            evidence_flags.append(str(d))

    # Steps: build 3 short actionable items based on flags
    steps = []
    if any('invoice' in f.lower() for f in evidence_flags):
        steps.append({'title': 'Contact provider billing to confirm invoice date.', 'eta': '3–6 min', 'impact': 'high'})
    if any('dob' in f.lower() for f in evidence_flags):
        steps.append({'title': "Verify patient's DOB against ID on file.", 'eta': '2–4 min', 'impact': 'medium'})
    if any('physician' in f.lower() or 'network' in combined.lower() for f in evidence_flags):
        steps.append({'title': 'Check out-of-network benefits and co-pay.', 'eta': '4–8 min', 'impact': 'low'})
    if not steps:
        steps = [{'title': 'Review flagged items and resolve outstanding inconsistencies.', 'eta': '5–10 min', 'impact': 'medium'}]

    claim_ref = triage.get('claim_ref') or triage.get('id') or '—'
    est_review_time = triage.get('estimated_review_time') or '7 min'
    confidence_value = triage.get('confidence')
    if confidence_value is None:
        # try prosecutor or defender
        confidence_value = prosecutor.get('confidence') if isinstance(prosecutor, dict) else None
    confidence_text = 'Low'
    if isinstance(confidence_value, (int, float)):
        confidence_value = f"{confidence_value:.2f}"
        if float(confidence_value) >= 0.7:
            confidence_text = 'High'
        elif float(confidence_value) >= 0.4:
            confidence_text = 'Medium'
        else:
            confidence_text = 'Low'
    else:
        confidence_value = '--'

    return render_template('verification_info.html',
                           primary_reason=primary_reason,
                           secondary_reasons=secondary_reasons,
                           evidence_flags=evidence_flags,
                           steps=steps,
                           documents=[(d.get('filename') if isinstance(d, dict) else str(d)) for d in documents],
                           claim_ref=claim_ref,
                           est_review_time=est_review_time,
                           confidence_text=confidence_text,
                           confidence_value=confidence_value)


@app.route('/health')
def health():
    """Simple health check for deployment monitoring."""
    return jsonify({"status": "ok", "model": os.environ.get("GEMINI_MODEL", os.environ.get("ANTHROPIC_MODEL", "gemini-2.5-flash"))})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        print("WARNING: GOOGLE_API_KEY / GEMINI_API_KEY not set. Set it in your .env file.")
    app.run(debug=True, port=5000)
