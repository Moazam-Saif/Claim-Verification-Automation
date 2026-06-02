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
from db import (
    create_claim,
    create_claimant,
    get_all_claims,
    save_error,
    save_result,
    set_claim_status,
)

load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB total upload limit

ALLOWED_EXTENSIONS = {"pdf"}
MAX_FILES = 10


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


def _build_admin_view(claim: dict) -> dict:
    result_json = claim.get('result_json') or {}
    triage_card = result_json.get('triage_card') if isinstance(result_json, dict) else {}
    if not isinstance(triage_card, dict):
        triage_card = {}

    documents_source = claim.get('documents_json') or triage_card.get('documents_processed') or []
    documents = []
    for item in documents_source:
        if isinstance(item, dict):
            documents.append(item.get('filename') or item.get('name') or 'Unnamed PDF')
        else:
            documents.append(str(item))

    drive_folder_id = claim.get('drive_folder_id')
    drive_view_url = f"https://drive.google.com/drive/folders/{drive_folder_id}" if drive_folder_id else None

    next_steps = []
    for step in triage_card.get('human_checklist', []):
        if isinstance(step, dict) and step.get('action'):
            next_steps.append(step.get('action'))

    verified_things = triage_card.get('key_approval_factors') or _text_list((result_json.get('defender') or {}).get('approval_factors'))
    unverified_things = triage_card.get('key_risk_factors') or _text_list((result_json.get('prosecutor') or {}).get('flags'))

    return {
        'claim_id': claim.get('id'),
        'claimant_name': claim.get('full_name') or 'Unknown',
        'claimant_email': claim.get('email') or 'Unknown',
        'submitted_at': claim.get('submitted_at'),
        'status': claim.get('status'),
        'verdict': claim.get('verdict'),
        'why_not_auto_approved': triage_card.get('verdict_reasoning') or triage_card.get('escalation_reason') or claim.get('error_log') or 'Manual review required.',
        'verified_things': verified_things if isinstance(verified_things, list) else _text_list([verified_things]),
        'unverified_things': unverified_things if isinstance(unverified_things, list) else _text_list([unverified_things]),
        'next_steps': next_steps,
        'documents': documents,
        'drive_view_url': drive_view_url,
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

    claimant_name = request.form.get('claimant_name', '').strip()
    claimant_email = request.form.get('claimant_email', '').strip()

    if not claimant_name or not claimant_email:
        return jsonify({"error": "Claimant name and email are required."}), 400

    claimant_id = create_claimant(claimant_name, claimant_email)
    claim_id = create_claim(claimant_id)

    # ── Stage 1: Extract text from all PDFs ───────────────────────────────────
    raw_docs = []
    skipped = []

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
        save_error(claim_id, "Could not extract text from any uploaded files.")
        return jsonify({
            "error": "Could not extract text from any uploaded files.",
            "detail": "All files appear to be scanned image PDFs or are corrupted. "
                      "Please upload text-layer PDFs.",
            "skipped": skipped
        }), 422

    def generate():
        try:
            set_claim_status(claim_id, 'processing')

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
                error_message = "No documents could be classified. Manual review required."
                save_error(claim_id, error_message)
                yield _sse_event({
                    "stage": "error",
                    "error": error_message,
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
            internal_result = {
                "triage_card": triage_card,
                "defender": defender_output,
                "prosecutor": prosecutor_output,
                "documents": parsed_docs,
                "skipped": skipped,
            }
            save_result(claim_id, internal_result)

            user_result = _build_user_result(triage_card, claim_id)

            yield _sse_event({
                "stage": "complete",
                "claim_id": claim_id,
                "user_result": user_result
            })
        except Exception as exc:
            save_error(claim_id, str(exc))
            yield _sse_event({
                "stage": "error",
                "error": str(exc),
                "claim_id": claim_id
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
    pending_claims = [
        _build_admin_view(claim)
        for claim in get_all_claims()
        if claim.get('verdict') == 'MANUAL_REVIEW' and not claim.get('worker_decision')
    ]
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
