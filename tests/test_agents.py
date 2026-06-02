import pytest
from unittest.mock import patch

import parser as parser_mod
import prosecutor as prosecutor_mod


def fake_call_claude_success_parse(*args, **kwargs):
    return {"ok": True, "data": {
        "doc_type": "invoice",
        "confidence": 0.95,
        "unusable": False,
        "fields": {"patient_name": "Test", "claim_amount": "8450.00"},
        "citations": {"patient_name": "Test"},
        "missing_required_fields": []
    }}


def fake_call_claude_success_prosec(*args, **kwargs):
    return {"ok": True, "data": {
        "flags": [
            {"id": "AI001", "severity": "MEDIUM", "issue": "Test issue", "evidence": ["invoice.claim_amount = 8450.00"], "fraud_pattern": None, "recommended_check": "Check"}
        ],
        "summary": {"HIGH": 0, "MEDIUM": 1, "LOW": 0},
        "overall_risk": "MEDIUM",
        "confidence": 0.75
    }}


@patch('parser.call_claude', side_effect=fake_call_claude_success_parse)
def test_parse_document_clamps_and_shape(mock_call):
    # Simulate a long raw text; expect truncated flag False for short
    res = parser_mod.parse_document('Short text', 'test.pdf')
    assert res['doc_type'] == 'invoice'
    assert 0.0 <= res['confidence'] <= 1.0
    assert 'truncated' in res


@patch('prosecutor.call_claude', side_effect=fake_call_claude_success_prosec)
def test_prosecutor_merge_and_confidence(mock_call):
    parsed_docs = [{
        'filename': 'test.pdf',
        'doc_type': 'invoice',
        'unusable': False,
        'fields': {'claim_amount': 8450.0},
        'missing_required_fields': []
    }]
    proc = prosecutor_mod.run_prosecutor(parsed_docs, {})
    assert isinstance(proc['confidence'], float)
    # merge hard flags
    merged = prosecutor_mod.merge_hard_rule_flags(proc, [])
    assert merged is not proc
    assert 'flags' in merged
