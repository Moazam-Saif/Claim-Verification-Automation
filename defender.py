"""
agents/defender.py

Stage 3a: Build the strongest legitimate case FOR approving the claim.

Prompt architecture: from the Gemini-optimized file (tight, schema-first).
fraud_pattern field kept from original design — it adds signal for the synthesiser.
Output feeds into synthesiser.py (Python), not an AI judge.
"""

import json
from claude_client import call_claude

SYSTEM_PROMPT = """You are an insurance approval analyst.

You will receive structured claim data extracted from multiple documents.

Your goal:
Build the strongest legitimate case FOR approving the claim.

Rules:
- Use only provided data
- Do not invent evidence
- Reference supporting fields directly using format: doc_type.field_name = value
- Identify corroboration across documents (same value appearing in multiple docs)
- If something cannot be defended, explicitly state it in unable_to_defend
- Keep arguments concise and evidence-based
- Return ONLY valid JSON
- No markdown
- No explanations"""

USER_TEMPLATE = """Build the strongest approval case for this insurance claim.

CLAIM DATA:
{claim_json}

POLICY RULES:
{policy_json}

Return this exact JSON and nothing else:
{{
  "approval_factors": [
    {{
      "reason": "",
      "evidence": ["doc_type.field = value"],
      "strength": "HIGH|MEDIUM|LOW"
    }}
  ],
  "unable_to_defend": [],
  "overall_support_strength": "HIGH|MEDIUM|LOW",
  "confidence": 0.0
}}"""


def run_defender(parsed_docs: list, policy_rules: dict) -> dict:
    """
    Run the Defender agent across all parsed documents.

    Args:
        parsed_docs:  list of document dicts from parser.py
        policy_rules: dict of policy constraints from config

    Returns defender output dict, or safe fallback on failure.
    """
    claim_summary = _build_claim_summary(parsed_docs)

    result = call_claude(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=USER_TEMPLATE.format(
            claim_json=json.dumps(claim_summary, indent=2),
            policy_json=json.dumps(policy_rules, indent=2)
        ),
        max_tokens=900
    )

    if result["ok"]:
        data = result["data"]
        # Clamp confidence
        try:
            conf = float(data.get("confidence", 0.3))
        except Exception:
            conf = 0.3
        conf = max(0.0, min(1.0, conf))

        return {
            "approval_factors":       data.get("approval_factors", []),
            "unable_to_defend":       data.get("unable_to_defend", []),
            "overall_support_strength": data.get("overall_support_strength", "LOW"),
            "confidence":             conf,
            "agent_error":            False
        }

    return {
        "approval_factors":         [],
        "unable_to_defend":         ["Defender agent failed. Manual review required."],
        "overall_support_strength": "LOW",
        "confidence":               0.0,
        "agent_error":              True,
        "error_detail":             result.get("error", "Unknown error")
    }


def _build_claim_summary(docs: list) -> list:
    """
    Strip raw text from parsed docs — agents only need structured fields.
    Keeps the prompt focused and reduces token usage.
    """
    return [
        {
            "filename":    d.get("filename"),
            "doc_type":    d.get("doc_type"),
            "unusable":    d.get("unusable", False),
            "fields":      d.get("fields", {}),
            "missing":     d.get("missing_required_fields", [])
        }
        for d in docs
    ]
