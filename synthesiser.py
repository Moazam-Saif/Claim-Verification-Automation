"""
agents/synthesiser.py

Stage 4: Pure Python synthesis layer. No AI call.

"AI reasons. Python decides."

Responsibilities:
1. Apply escalation rules deterministically
2. Compute verdict: RECOMMEND_APPROVE | MANUAL_REVIEW | RECOMMEND_REJECT
3. Compute confidence score from weighted conditions (no AI scores used)
4. Build the human checklist from actual flag data
5. Produce the final triage card object that the frontend renders

── Confidence scoring ────────────────────────────────────────────────────────

Confidence is computed deterministically from weighted deductions.
Score starts at 1.0; each failed condition subtracts its weight.
This replaces the original approach of averaging AI confidence scores,
which were unreliable and not grounded in specific policy criteria.

Hard-rule deductions (from validators.py flag IDs):
    HR001 — Required document missing         −0.15 per missing doc type
    HR002 — Claim amount exceeds maximum      −0.15
    HR003 — Treatment before coverage start   −0.20  (structurally invalid)
    HR004 — Treatment after policy expiry     −0.20  (structurally invalid)
    HR005 — Invoice before treatment date     −0.10  (known fraud pattern)
    HR006 — Patient name mismatch             −0.15  (identity signal)
    HR007 — Out-of-network physician          −0.05

AI-generated flag deductions (non-hard-rule flags only):
    HIGH severity                             −0.12 per flag
    MEDIUM severity                           −0.06 per flag
    LOW severity                              −0.02 per flag

Other deductions:
    Defender unable_to_defend item            −0.05 per item
    AI agent failure (error)                  −0.10 per failed agent

Confidence tiers:
    ≥ 0.75 → HIGH
    0.45 – 0.74 → MEDIUM
    < 0.45 → LOW
"""

# ── Confidence weight tables ───────────────────────────────────────────────────

# Deduction per hard-rule flag ID (from validators.py)
HARD_RULE_WEIGHTS = {
    "HR001": 0.15,   # Required document missing (charged per occurrence)
    "HR002": 0.15,   # Claim amount exceeds policy maximum
    "HR003": 0.20,   # Treatment before coverage start — structurally invalid
    "HR004": 0.20,   # Treatment after policy expiry — structurally invalid
    "HR005": 0.10,   # Invoice issued before treatment (pre-treatment billing)
    "HR006": 0.15,   # Patient name mismatch across documents
    "HR007": 0.05,   # Out-of-network physician
}

# Deduction per AI-generated flag, by severity (applied only when source != "hard_rule")
AI_FLAG_WEIGHTS = {
    "HIGH":   0.12,
    "MEDIUM": 0.06,
    "LOW":    0.02,
}

UNABLE_TO_DEFEND_WEIGHT = 0.05   # Per item the defender could not address
AGENT_ERROR_WEIGHT      = 0.10   # Per AI agent that failed to run


def synthesise(defender: dict, prosecutor: dict, parsed_docs: list) -> dict:
    """
    Merge Defender and Prosecutor outputs into a final triage card.

    Args:
        defender:    output from defender.py
        prosecutor:  output from prosecutor.py (after hard rule flags merged in)
        parsed_docs: list of parsed document dicts (for checklist context)

    Returns:
        A triage card dict ready to be returned to the frontend as JSON.
    """
    flags   = prosecutor.get("flags", [])
    summary = prosecutor.get("summary", {"HIGH": 0, "MEDIUM": 0, "LOW": 0})

    verdict    = _apply_escalation_rules(defender, prosecutor, summary)
    confidence = _compute_confidence(defender, prosecutor, flags)
    checklist  = _build_checklist(flags, parsed_docs)
    reasoning  = _build_reasoning(verdict, summary, defender)

    return {
        "verdict":                       verdict,
        "confidence_tier":               confidence["tier"],
        "confidence_score":              confidence["score"],
        "verdict_reasoning":             reasoning,
        "key_approval_factors":          _top_approval_factors(defender),
        "key_risk_factors":              _top_risk_factors(flags),
        "human_checklist":               checklist,
        "estimated_total_review_minutes": _estimate_review_time(checklist, verdict),
        "flag_summary":                  summary,
        "escalate_immediately":          verdict == "RECOMMEND_REJECT" or summary["HIGH"] > 1,
        "escalation_reason":             _escalation_reason(verdict, summary, flags),
        "documents_processed":           _doc_status(parsed_docs)
    }


# ── Escalation rules (deterministic) ─────────────────────────────────────────

def _apply_escalation_rules(defender: dict, prosecutor: dict, summary: dict) -> str:
    """
    Pure rule-based verdict. No AI involved.

    Rules (in priority order):
    1. Any flag matching a known fraud pattern AND HIGH severity → RECOMMEND_REJECT
    2. Any HIGH flag → MANUAL_REVIEW minimum
    3. 2+ MEDIUM flags → MANUAL_REVIEW
    4. Defender has unable_to_defend items → MANUAL_REVIEW
    5. Defender confidence < 0.5 AND any flag exists → MANUAL_REVIEW
    6. Either agent errored → MANUAL_REVIEW (safe default)
    7. All clear → RECOMMEND_APPROVE
    """
    flags = prosecutor.get("flags", [])

    # Rule 1: confirmed fraud pattern + HIGH severity
    for flag in flags:
        if flag.get("severity") == "HIGH" and flag.get("fraud_pattern"):
            return "RECOMMEND_REJECT"

    # Rule 2: any HIGH flag
    if summary.get("HIGH", 0) > 0:
        return "MANUAL_REVIEW"

    # Rule 3: two or more MEDIUM flags
    if summary.get("MEDIUM", 0) >= 2:
        return "MANUAL_REVIEW"

    # Rule 4: defender cannot defend something
    if defender.get("unable_to_defend"):
        return "MANUAL_REVIEW"

    # Rule 5: low defender confidence + any flag
    if defender.get("confidence", 1.0) < 0.5 and len(flags) > 0:
        return "MANUAL_REVIEW"

    # Rule 6: agent errors — safe default
    if defender.get("agent_error") or prosecutor.get("agent_error"):
        return "MANUAL_REVIEW"

    # Rule 7: all clear
    return "RECOMMEND_APPROVE"


# ── Confidence calculation (weighted, deterministic) ─────────────────────────

def _compute_confidence(defender: dict, prosecutor: dict, flags: list) -> dict:
    """
    Compute confidence score from weighted condition deductions.

    Starts at 1.0 (perfect) and deducts for each failed condition.
    Uses the flag IDs from validators.py and AI flag severities.
    Does NOT use the AI agents' self-reported confidence scores — those
    are opaque and unreliable as a confidence signal.

    Returns { "score": float, "tier": "HIGH"|"MEDIUM"|"LOW" }.
    """
    score = 1.0

    for flag in flags:
        flag_id  = flag.get("id", "")
        severity = flag.get("severity", "LOW")
        source   = flag.get("source", "ai")

        if source == "hard_rule":
            # Structured deduction — exact weight per rule
            deduction = HARD_RULE_WEIGHTS.get(flag_id, 0.05)
        else:
            # AI-generated flag — weight by severity
            deduction = AI_FLAG_WEIGHTS.get(severity, 0.02)

        score -= deduction

    # Deduct for each item the defender explicitly couldn't address
    unable = defender.get("unable_to_defend") or []
    score -= len(unable) * UNABLE_TO_DEFEND_WEIGHT

    # Deduct for each AI agent that failed to run
    if defender.get("agent_error"):
        score -= AGENT_ERROR_WEIGHT
    if prosecutor.get("agent_error"):
        score -= AGENT_ERROR_WEIGHT

    score = max(0.05, min(0.99, round(score, 2)))

    if score >= 0.75:
        tier = "HIGH"
    elif score >= 0.45:
        tier = "MEDIUM"
    else:
        tier = "LOW"

    return {"tier": tier, "score": score}


# ── Human checklist builder ───────────────────────────────────────────────────

def _build_checklist(flags: list, parsed_docs: list) -> list:
    """
    Build a prioritised human checklist from actual flag data.
    Maximum 3 items. Ordered: HIGH first, then MEDIUM, then LOW.
    """
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    sorted_flags   = sorted(flags, key=lambda f: severity_order.get(f.get("severity", "LOW"), 2))

    checklist = []
    for i, flag in enumerate(sorted_flags[:3]):
        severity   = flag.get("severity", "LOW")
        issue      = flag.get("issue", "")
        rec_check  = flag.get("recommended_check", "")
        evidence   = flag.get("evidence", [])
        fraud_pat  = flag.get("fraud_pattern")

        action = rec_check if rec_check else f"Review: {issue}"

        if fraud_pat:
            why = f"This matches a known pattern: '{fraud_pat}'. Confirming prevents wrongful approval."
        elif severity == "HIGH":
            why = "This is a policy violation. Approving without verification could constitute a compliance breach."
        elif severity == "MEDIUM":
            why = "This inconsistency could indicate an error or misrepresentation. Verification prevents wrongful approval."
        else:
            why = "Minor issue worth confirming before final decision."

        est_minutes = _estimate_item_time(severity, rec_check)

        checklist.append({
            "priority":          i + 1,
            "severity":          severity,
            "action":            action,
            "why":               why,
            "evidence":          evidence,
            "estimated_minutes": est_minutes
        })

    if not checklist:
        checklist.append({
            "priority":          1,
            "severity":          "LOW",
            "action":            "Confirm all documents are authentic and complete before approving.",
            "why":               "Final human sign-off is required regardless of automated recommendation.",
            "evidence":          [],
            "estimated_minutes": 2
        })

    return checklist


def _estimate_item_time(severity: str, action_text: str) -> int:
    action_lower = (action_text or "").lower()
    if "id" in action_lower or "identity" in action_lower or "contact" in action_lower:
        return 5
    if severity == "HIGH":
        return 4
    if severity == "MEDIUM":
        return 3
    return 2


def _estimate_review_time(checklist: list, verdict: str) -> int:
    base = sum(item.get("estimated_minutes", 2) for item in checklist)
    if verdict == "RECOMMEND_APPROVE":
        return max(2, base)
    return base


# ── Summary text builders ─────────────────────────────────────────────────────

def _build_reasoning(verdict: str, summary: dict, defender: dict) -> str:
    high   = summary.get("HIGH",   0)
    medium = summary.get("MEDIUM", 0)
    low    = summary.get("LOW",    0)
    unable = defender.get("unable_to_defend", [])

    if verdict == "RECOMMEND_REJECT":
        return (
            f"Claim flagged for rejection: {high} HIGH severity issue(s) match known fraud patterns. "
            f"These require escalation to a senior adjudicator before any further action."
        )
    if verdict == "MANUAL_REVIEW":
        reasons = []
        if high > 0:
            reasons.append(f"{high} HIGH severity flag(s)")
        if medium >= 2:
            reasons.append(f"{medium} MEDIUM severity flags")
        if unable:
            reasons.append("unresolved issues the approval case could not address")
        reason_str = " and ".join(reasons) if reasons else "flags requiring verification"
        return (
            f"Manual review required due to {reason_str}. "
            f"Please work through the checklist below before making a final decision."
        )
    flag_note = f"{low} minor note(s) logged." if low > 0 else "No issues found."
    return (
        f"Claim appears consistent across all submitted documents. "
        f"Coverage was active, amounts are within limits, and no policy violations detected. "
        f"{flag_note} Human confirmation required before final approval."
    )


def _top_approval_factors(defender: dict) -> list:
    factors = defender.get("approval_factors", [])
    return [f.get("reason", "") for f in factors[:3] if f.get("reason")]


def _top_risk_factors(flags: list) -> list:
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    sorted_flags   = sorted(flags, key=lambda f: severity_order.get(f.get("severity", "LOW"), 2))
    return [f.get("issue", "") for f in sorted_flags[:3] if f.get("issue")]


def _escalation_reason(verdict: str, summary: dict, flags: list) -> str | None:
    if verdict != "RECOMMEND_REJECT" and summary.get("HIGH", 0) <= 1:
        return None
    fraud_flags = [f for f in flags if f.get("fraud_pattern") and f.get("severity") == "HIGH"]
    if fraud_flags:
        patterns = ", ".join(f["fraud_pattern"] for f in fraud_flags)
        return f"Fraud pattern(s) detected: {patterns}"
    if summary.get("HIGH", 0) > 1:
        return f"{summary['HIGH']} HIGH severity policy violations present."
    return None


def _doc_status(parsed_docs: list) -> list:
    return [
        {
            "filename": d.get("filename"),
            "doc_type": d.get("doc_type"),
            "unusable": d.get("unusable", False),
            "reason":   d.get("unusable_reason")
        }
        for d in parsed_docs
    ]
