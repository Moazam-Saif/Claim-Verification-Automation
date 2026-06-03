"""
agents/prosecutor.py

Stage 3b: Find all inconsistencies, violations, fraud indicators, missing information.

Prompt architecture: from the Gemini-optimized file (tight, schema-first).
fraud_pattern added back to the schema — it's what makes flags actionable
and lets the Python synthesiser detect fraud-pattern escalations.
Output feeds into synthesiser.py (Python), not an AI judge.
"""

import json
from claude_client import call_claude

SYSTEM_PROMPT = """You are an insurance fraud and compliance analyst.

You will receive structured claim data extracted from multiple documents.

Your goal:
Find all inconsistencies, policy violations, suspicious patterns, and missing information.

Rules:
- Cross-check field values across all documents
- Compare dates logically (invoice before treatment? treatment outside coverage window?)
- Detect identity inconsistencies (name, DOB, ID mismatches across docs)
- Detect policy violations (amounts, dates, required fields)
- Never invent information
- Be thorough — it is better to over-flag than to miss an issue
- Return ONLY valid JSON
- No markdown
- No explanations

Severity rules:
- HIGH = major policy violation or strong fraud indicator. Never auto-approve if HIGH present.
- MEDIUM = inconsistency requiring human verification before decision
- LOW = minor issue or possible clerical error, unlikely to block approval"""

USER_TEMPLATE = """Analyze this insurance claim for risks, inconsistencies, fraud indicators, and policy violations.

CLAIM DATA:
{claim_json}

POLICY RULES:
{policy_json}

Return this exact JSON and nothing else:
{{
  "flags": [
    {{
      "id": "AI001",
      "severity": "HIGH|MEDIUM|LOW",
      "issue": "Plain English description of the problem",
      "evidence": ["doc_type.field = value"],
      "fraud_pattern": "Name of known fraud pattern or null",
      "recommended_check": "Specific action the human reviewer should take"
    }}
  ],
  "summary": {{
    "HIGH": 0,
    "MEDIUM": 0,
    "LOW": 0
  }},
  "overall_risk": "HIGH|MEDIUM|LOW",
  "confidence": 0.0
}}"""


def run_prosecutor(parsed_docs: list, policy_rules: dict) -> dict:
    """
    Run the Prosecutor agent across all parsed documents.

    Args:
        parsed_docs:  list of document dicts from parser.py
        policy_rules: dict of policy constraints from config

    Returns prosecutor output dict, or safe fallback on failure.
    """
    claim_summary = _build_claim_summary(parsed_docs)

    result = call_claude(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=USER_TEMPLATE.format(
            claim_json=json.dumps(claim_summary, indent=2),
            policy_json=json.dumps(policy_rules, indent=2)
        ),
        max_tokens=1400
    )

    if result["ok"]:
        data  = result["data"]
        flags = data.get("flags", [])
        # Clamp confidence
        try:
            conf = float(data.get("confidence", 0.5))
        except Exception:
            conf = 0.5
        conf = max(0.0, min(1.0, conf))

        return {
            "flags":        flags,
            "summary":      _recount(flags),   # recount as safety net
            "overall_risk": data.get("overall_risk", "LOW"),
            "confidence":   conf,
            "agent_error":  False
        }

    return {
        "flags":        [],
        "summary":      {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
        "overall_risk": "LOW",
        "confidence":   0.0,
        "agent_error":  True,
        "error_detail": result.get("error", "Unknown error")
    }


def merge_hard_rule_flags(prosecutor_output: dict, hard_flags: list) -> dict:
    """
    Merge flags from validators.py (deterministic checks) into the
    prosecutor output. Recounts summary after merging.

    Called by app.py before passing to the synthesiser.
    """
    # Build a new prosecutor output dict to avoid mutating the caller's object
    existing_flags = list(prosecutor_output.get("flags", []))

    # Tag hard rule flags with a source and ensure IDs are unique
    tagged_hard = []
    existing_ids = {f.get("id") for f in existing_flags if f.get("id")}
    hr_counter = 1
    for hf in hard_flags:
        new_flag = dict(hf)
        new_flag.setdefault("source", "hard_rule")
        if not new_flag.get("id"):
            # generate a deterministic HR ID if none provided
            nid = f"HR{hr_counter:03d}"
            while nid in existing_ids:
                hr_counter += 1
                nid = f"HR{hr_counter:03d}"
            new_flag["id"] = nid
            existing_ids.add(nid)
            hr_counter += 1
        tagged_hard.append(new_flag)

    all_flags = existing_flags + tagged_hard

    # Build new prosecutor output
    new_output = dict(prosecutor_output)
    new_output["flags"] = all_flags
    new_output["summary"] = _recount(all_flags)

    # Recalculate overall_risk from merged flags
    s = new_output["summary"]
    if s["HIGH"] > 0:
        new_output["overall_risk"] = "HIGH"
    elif s["MEDIUM"] > 0:
        new_output["overall_risk"] = "MEDIUM"
    else:
        new_output["overall_risk"] = new_output.get("overall_risk", "LOW")

    return new_output


def _recount(flags: list) -> dict:
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in flags:
        sev = f.get("severity", "LOW")
        if sev in counts:
            counts[sev] += 1
    return counts


def _build_claim_summary(docs: list) -> list:
    return [
        {
            "filename": d.get("filename"),
            "doc_type": d.get("doc_type"),
            "unusable": d.get("unusable", False),
            "fields":   d.get("fields", {}),
            "missing":  d.get("missing_required_fields", [])
        }
        for d in docs
    ]
