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

import os
from flask import Flask, request, jsonify, render_template
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

    # ── Stage 2: Parse each document (classify + extract) ─────────────────────
    parsed_docs = []
    for doc in raw_docs:
        parsed = parse_document(doc["text"], doc["filename"])
        parsed_docs.append(parsed)

    # Check we have at least one usable document
    usable = [d for d in parsed_docs if not d.get("unusable")]
    if not usable:
        return jsonify({
            "error": "No documents could be classified. Manual review required.",
            "documents": parsed_docs
        }), 422

    # ── Stage 3a: Defender ────────────────────────────────────────────────────
    defender_output = run_defender(parsed_docs, POLICY_RULES)

    # ── Stage 3b: Prosecutor ──────────────────────────────────────────────────
    prosecutor_output = run_prosecutor(parsed_docs, POLICY_RULES)

    # ── Hard rule validation (deterministic, non-AI) ──────────────────────────
    hard_flags = run_hard_rules(parsed_docs)
    prosecutor_output = merge_hard_rule_flags(prosecutor_output, hard_flags)

    # ── Stage 4: Python synthesis — no AI ─────────────────────────────────────
    triage_card = synthesise(defender_output, prosecutor_output, parsed_docs)

    # ── Return full response ──────────────────────────────────────────────────
    return jsonify({
        "triage_card": triage_card,
        "defender":    defender_output,
        "prosecutor":  prosecutor_output,
        "documents":   parsed_docs,
        "skipped":     skipped
    })


@app.route('/health')
def health():
    """Simple health check for deployment monitoring."""
    return jsonify({"status": "ok", "model": os.environ.get("GEMINI_MODEL", os.environ.get("ANTHROPIC_MODEL", "gemini-2.5-flash"))})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        print("WARNING: GOOGLE_API_KEY / GEMINI_API_KEY not set. Set it in your .env file.")
    app.run(debug=True, port=5000)
