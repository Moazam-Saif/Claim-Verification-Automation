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
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

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
CLAIM_REVIEW_QUEUE = []


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text_list(items):
    values = []
    for item in items or []:
        if isinstance(item, dict):
            text = item.get('reason') or item.get('issue') or item.get('action') or item.get('why')
            if text:
                values.append(text)
        elif item:
            values.append(str(item))
    return values


def _build_user_result(triage_card: dict, claim_id: str) -> dict:
    verdict = triage_card.get('verdict')
    reasoning = triage_card.get('verdict_reasoning') or 'Manual review required.'

    if verdict == 'RECOMMEND_APPROVE':
        status = 'approved'
        headline = 'Your claim is approved.'
        reason = 'The uploaded documents were consistent and did not trigger any blocking checks.'
    elif verdict == 'RECOMMEND_REJECT':
        status = 'rejected'
        headline = 'Your claim is rejected.'
        reason = reasoning
    else:
        status = 'pending_manual_approval'
        headline = 'Your claim is pending manual approval.'
        reason = reasoning

    return {
        'claim_id': claim_id,
        'status': status,
        'headline': headline,
        'reason': reason,
    }


def _build_admin_record(claim_id: str, claimant_name: str, claimant_email: str,
                        triage_card: dict, defender: dict, prosecutor: dict,
                        parsed_docs: list, skipped: list, documents: list) -> dict:
    verdict = triage_card.get('verdict')
    user_result = _build_user_result(triage_card, claim_id)
    pending_manual = verdict == 'MANUAL_REVIEW'

    return {
        'claim_id': claim_id,
        'submitted_at': _utc_now_iso(),
        'claimant_name': claimant_name or 'Unknown',
        'claimant_email': claimant_email or 'Unknown',
        'documents': documents,
        'parsed_documents': [
            {
                'filename': doc.get('filename'),
                'pages': doc.get('pages'),
                'classification': doc.get('classification'),
                'unusable': doc.get('unusable', False),
            }
            for doc in parsed_docs
        ],
        'skipped_documents': skipped,
        'verdict': verdict,
        'user_result': user_result,
        'why_not_auto_approved': triage_card.get('verdict_reasoning') or triage_card.get('escalation_reason') or 'Manual review required.',
        'verified_things': _text_list(defender.get('approval_factors')),
        'unverified_things': _text_list(prosecutor.get('flags')),
        'next_steps': [
            item.get('action') if isinstance(item, dict) else str(item)
            for item in triage_card.get('human_checklist', [])
            if item
        ],
        'claim_summary': triage_card.get('flag_summary', {}),
        'documents_processed': triage_card.get('documents_processed', []),
        'pending_manual': pending_manual,
        'drive_view_url': None,
    }


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
    skipped = []
    claimant_name = request.form.get('claimant_name', '').strip()
    claimant_email = request.form.get('claimant_email', '').strip()

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
        claim_id = uuid4().hex[:12]
        admin_record = _build_admin_record(
            claim_id=claim_id,
            claimant_name=claimant_name,
            claimant_email=claimant_email,
            triage_card=triage_card,
            defender=defender_output,
            prosecutor=prosecutor_output,
            parsed_docs=parsed_docs,
            skipped=skipped,
            documents=[doc.get('filename') for doc in parsed_docs],
        )

        if admin_record['pending_manual']:
            CLAIM_REVIEW_QUEUE.append(admin_record)

        user_result = _build_user_result(triage_card, claim_id)

        yield _sse_event({
            "stage": "complete",
            "claim_id": claim_id,
            "user_result": user_result
        })

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/render-user-result', methods=['POST'])
def render_user_result():
    """Render the user-facing claim status card."""
    payload = request.get_json(force=True)
    user_result = payload.get('user_result', {}) if isinstance(payload, dict) else {}
    return render_template('user_result.html', user_result=user_result)


@app.route('/admin')
def admin_dashboard():
    """Render the manual review queue for admins."""
    pending_claims = [claim for claim in CLAIM_REVIEW_QUEUE if claim.get('pending_manual')]
    return render_template('admin.html', claims=pending_claims)


@app.route('/health')
def health():
    """Simple health check for deployment monitoring."""
    return jsonify({"status": "ok", "model": os.environ.get("GEMINI_MODEL", os.environ.get("ANTHROPIC_MODEL", "gemini-2.5-flash"))})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        print("WARNING: GOOGLE_API_KEY / GEMINI_API_KEY not set. Set it in your .env file.")
    app.run(debug=True, port=5000)
