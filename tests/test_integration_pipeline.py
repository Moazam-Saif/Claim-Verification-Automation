import glob
import re
from unittest.mock import patch

import pdf_reader
import parser as parser_mod
import defender as defender_mod
import prosecutor as prosecutor_mod
import validators as validators_mod
import synthesiser as synthesiser_mod


def _fake_parse(raw_text, filename):
    # Very small heuristic to determine doc_type
    text = raw_text.lower()
    doc_type = "unknown"
    if "invoice" in text or "invoice date" in text:
        doc_type = "invoice"
    elif "treatment" in text or "diagnosis" in text:
        doc_type = "treatment_summary"
    elif "policy" in text or "coverage" in text:
        doc_type = "insurance_form"
    elif "payslip" in text or "salary" in text:
        doc_type = "payslip"
    elif "patient" in text:
        doc_type = "patient_record"

    # Try to extract a monetary amount
    match = re.search(r"\b(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\b", raw_text)
    claim_amount = float(match.group(1).replace(",", "")) if match else None

    # Return in the adapter's expected envelope
    return {
        "ok": True,
        "data": {
            "doc_type": doc_type,
            "confidence": 0.9,
            "unusable": False,
            "fields": {
                "patient_name": "Test Patient",
                "claim_amount": claim_amount,
                "invoice_date": None,
                "treatment_date": None,
            },
            "citations": {},
            "missing_required_fields": []
        }
    }


def _fake_defender(parsed_docs, policy_rules):
    return {
        "approval_factors": [],
        "unable_to_defend": [],
        "overall_support_strength": "HIGH",
        "confidence": 0.85,
        "agent_error": False
    }


def _fake_prosecutor(parsed_docs, policy_rules):
    return {
        "flags": [],
        "summary": {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
        "overall_risk": "LOW",
        "confidence": 0.85,
        "agent_error": False
    }


@patch('parser.call_claude', side_effect=lambda *a, **k: _fake_parse(a[1] if len(a)>1 else "", a[0] if len(a)>0 else ""))
@patch('defender.call_claude', side_effect=lambda *a, **k: {"ok": True, "data": {"approval_factors": [], "unable_to_defend": [], "overall_support_strength": "HIGH", "confidence": 0.85}})
@patch('prosecutor.call_claude', side_effect=lambda *a, **k: {"ok": True, "data": {"flags": [], "summary": {"HIGH":0,"MEDIUM":0,"LOW":0}, "overall_risk": "LOW", "confidence": 0.85}})
def test_full_pipeline(mock_proc, mock_def, mock_parse):
    pdf_paths = sorted(glob.glob("*.pdf"))
    assert len(pdf_paths) >= 1, "No PDF files found for integration test"

    parsed_docs = []
    for p in pdf_paths:
        with open(p, 'rb') as fh:
            res = pdf_reader.extract_text(fh)
        if not res['success']:
            parsed_docs.append({
                'filename': p,
                'doc_type': 'unknown',
                'confidence': 0.0,
                'unusable': True,
                'unusable_reason': res['reason'],
                'fields': {},
                'citations': {},
                'missing_required_fields': []
            })
            continue

        parsed = parser_mod.parse_document(res['text'], p)
        parsed_docs.append(parsed)

    # Run deterministic validators
    hard_flags = validators_mod.run_hard_rules(parsed_docs)

    # Run defender and prosecutor
    defender_out = defender_mod.run_defender(parsed_docs, validators_mod.POLICY_RULES)
    prosecutor_out = prosecutor_mod.run_prosecutor(parsed_docs, validators_mod.POLICY_RULES)

    merged = prosecutor_mod.merge_hard_rule_flags(prosecutor_out, hard_flags)

    triage = synthesiser_mod.synthesise(defender_out, merged, parsed_docs)

    # Basic assertions about triage card shape
    assert 'verdict' in triage
    assert 'documents_processed' in triage
    assert len(triage['documents_processed']) == len(parsed_docs)
    # Flag summary should match merged summary
    assert triage['flag_summary'] == merged['summary']
