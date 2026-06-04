"""
utils/validators.py

Deterministic policy rule checks. No AI involved.

These run independently of the AI agents as a safety net.
Rules that can be checked with pure logic live here — not in prompts.
Output flags are merged into the Prosecutor output before synthesis.

Why separate from the AI Prosecutor:
- Deterministic rules should never be probabilistic
- Date range checks, amount thresholds, required doc checks are 100% reliable here
- Provides a hard floor even if the AI Prosecutor misses something
"""

from datetime import datetime, date
from difflib import SequenceMatcher


# ── Policy configuration ──────────────────────────────────────────────────────

POLICY_RULES = {
    "max_claim_amount":    50000,
    "required_doc_types":  ["invoice", "insurance_form"],
    "coverage_check":      True,
    "name_match_required": True,
    "invoice_date_check":  True,
}

# Approved network physicians (hardcoded for demo)
NETWORK_PHYSICIANS = [
    "dr. sarah ahmed",
    "dr. omar hassan",
    "dr. fatima al-zaabi",
    "dr. james thornton",
    "dr. priya nair",
]


# ── Main entry point ──────────────────────────────────────────────────────────

def run_hard_rules(parsed_docs: list) -> list:
    """
    Run all deterministic checks across the full document set.
    Returns a list of flag dicts in the same format as the Prosecutor agent.
    """
    flags = []
    doc_types = [d.get("doc_type") for d in parsed_docs if not d.get("unusable")]

    flags += _check_required_documents(doc_types)
    flags += _check_claim_amount(parsed_docs)
    flags += _check_coverage_dates(parsed_docs)
    flags += _check_invoice_before_treatment(parsed_docs)
    flags += _check_name_consistency(parsed_docs)
    flags += _check_network_physician(parsed_docs)

    return flags


# ── Rule implementations ──────────────────────────────────────────────────────

def _check_required_documents(doc_types: list) -> list:
    flags = []
    for required in POLICY_RULES["required_doc_types"]:
        if required not in doc_types:
            flags.append(_flag(
                id="HR001",
                severity="HIGH",
                issue=f"Required document type '{required}' is missing from the submission.",
                evidence=[],
                fraud_pattern=None,
                recommended_check=(
                    f"Request the missing '{required}' document from the claimant "
                    f"before proceeding with evaluation."
                )
            ))
    return flags


def _check_claim_amount(docs: list) -> list:
    flags = []
    for doc in docs:
        if doc.get("unusable"):
            continue
        amount = doc.get("fields", {}).get("claim_amount")
        if amount is None:
            continue
        try:
            amt = float(str(amount).replace(",", "").strip())
            if amt > POLICY_RULES["max_claim_amount"]:
                flags.append(_flag(
                    id="HR002",
                    severity="HIGH",
                    issue=(
                        f"Claim amount USD {amt:,.2f} exceeds the maximum annual "
                        f"benefit of USD {POLICY_RULES['max_claim_amount']:,}."
                    ),
                    evidence=[f"{doc.get('doc_type')}.claim_amount = {amt}"],
                    fraud_pattern=None,
                    recommended_check=(
                        "Verify if this claim falls under any special benefit extension "
                        "or if the claimant has a supplementary policy."
                    )
                ))
        except (ValueError, TypeError):
            pass
    return flags


def _check_coverage_dates(docs: list) -> list:
    flags = []
    treatment = _find_field(docs, "treatment_date")
    cov_start = _find_field_from_type(docs, "coverage_start_date", "insurance_form")
    cov_end   = _find_field_from_type(docs, "coverage_end_date",   "insurance_form")

    if not (treatment and cov_start and cov_end):
        return flags

    t = _parse_date(treatment["value"])
    s = _parse_date(cov_start["value"])
    e = _parse_date(cov_end["value"])

    if not (t and s and e):
        return flags

    if t < s:
        flags.append(_flag(
            id="HR003",
            severity="HIGH",
            issue=(
                f"Treatment date ({treatment['value']}) is before coverage start "
                f"({cov_start['value']}). Policy was not yet active."
            ),
            evidence=[
                f"{treatment['doc_type']}.treatment_date = {treatment['value']}",
                f"{cov_start['doc_type']}.coverage_start_date = {cov_start['value']}"
            ],
            fraud_pattern="Backdated claim",
            recommended_check=(
                "Confirm treatment date on hospital records. "
                "Cross-check with admission/discharge reports."
            )
        ))

    if t > e:
        flags.append(_flag(
            id="HR004",
            severity="HIGH",
            issue=(
                f"Treatment date ({treatment['value']}) is after policy expiry "
                f"({cov_end['value']}). Policy was not active on treatment date."
            ),
            evidence=[
                f"{treatment['doc_type']}.treatment_date = {treatment['value']}",
                f"{cov_end['doc_type']}.coverage_end_date = {cov_end['value']}"
            ],
            fraud_pattern="Claim after policy lapse",
            recommended_check=(
                "Verify policy status on the date of treatment. "
                "Check if a renewal was processed but not yet reflected."
            )
        ))

    return flags


def _check_invoice_before_treatment(docs: list) -> list:
    flags = []
    inv_date  = _find_field(docs, "invoice_date")
    treat_date = _find_field(docs, "treatment_date")

    if not (inv_date and treat_date):
        return flags

    i = _parse_date(inv_date["value"])
    t = _parse_date(treat_date["value"])

    if not (i and t):
        return flags

    if i < t:
        delta = (t - i).days
        flags.append(_flag(
            id="HR005",
            severity="MEDIUM",
            issue=(
                f"Invoice date ({inv_date['value']}) is {delta} day(s) before "
                f"treatment date ({treat_date['value']}). "
                f"Providers should not invoice before treatment occurs."
            ),
            evidence=[
                f"{inv_date['doc_type']}.invoice_date = {inv_date['value']}",
                f"{treat_date['doc_type']}.treatment_date = {treat_date['value']}"
            ],
            fraud_pattern="Pre-treatment billing",
            recommended_check=(
                "Contact the provider's billing department to confirm the invoice date. "
                "This may be a clerical error but must be verified."
            )
        ))

    return flags


def _check_name_consistency(docs: list) -> list:
    flags = []
    names = []

    for doc in docs:
        if doc.get("unusable"):
            continue
        name = doc.get("fields", {}).get("patient_name")
        if name:
            names.append({"name": name.strip(), "doc_type": doc.get("doc_type")})

    if len(names) < 2:
        return flags

    base = names[0]
    for other in names[1:]:
        ratio = SequenceMatcher(None, base["name"].lower(), other["name"].lower()).ratio()
        if ratio < 0.80:
            flags.append(_flag(
                id="HR006",
                severity="HIGH",
                issue=(
                    f"Patient name mismatch: '{base['name']}' ({base['doc_type']}) "
                    f"vs '{other['name']}' ({other['doc_type']}). "
                    f"Name similarity: {ratio:.0%}."
                ),
                evidence=[
                    f"{base['doc_type']}.patient_name = {base['name']}",
                    f"{other['doc_type']}.patient_name = {other['name']}"
                ],
                fraud_pattern="Identity substitution",
                recommended_check=(
                    "Request government-issued ID from the claimant. "
                    "Verify which name matches the policy holder on record."
                )
            ))
    return flags


def _check_network_physician(docs: list) -> list:
    flags = []
    for doc in docs:
        if doc.get("unusable"):
            continue
        physician = doc.get("fields", {}).get("physician_name")
        if not physician:
            continue
        on_network = any(
            SequenceMatcher(None, physician.lower(), n).ratio() > 0.85
            for n in NETWORK_PHYSICIANS
        )
        if not on_network:
            flags.append(_flag(
                id="HR007",
                severity="LOW",
                issue=(
                    f"Attending physician '{physician}' is not on the approved provider network."
                ),
                evidence=[f"{doc.get('doc_type')}.physician_name = {physician}"],
                fraud_pattern=None,
                recommended_check=(
                    "Check if the patient has out-of-network benefit coverage. "
                    "Apply any applicable co-payment adjustment."
                )
            ))
        break  # Only check first physician found
    return flags


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_field(docs: list, field_name: str) -> dict | None:
    for doc in docs:
        if doc.get("unusable"):
            continue
        value = doc.get("fields", {}).get(field_name)
        if value is not None:
            return {"value": str(value), "doc_type": doc.get("doc_type", "unknown")}
    return None

def _find_field_from_type(docs: list, field_name: str, doc_type: str) -> dict | None:
    """Like _find_field but only searches documents of a specific type."""
    for doc in docs:
        if doc.get("unusable"):
            continue
        if doc.get("doc_type") != doc_type:
            continue
        value = doc.get("fields", {}).get(field_name)
        if value is not None:
            return {"value": str(value), "doc_type": doc.get("doc_type", "unknown")}
    return None


def _parse_date(date_str: str) -> date | None:
    formats = [
        "%Y-%m-%d", "%d %B %Y", "%d %b %Y",
        "%d/%m/%Y", "%m/%d/%Y", "%B %d, %Y", "%d.%m.%Y"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _flag(id, severity, issue, evidence, fraud_pattern, recommended_check) -> dict:
    return {
        "id":                id,
        "severity":          severity,
        "issue":             issue,
        "evidence":          evidence,
        "fraud_pattern":     fraud_pattern,
        "recommended_check": recommended_check,
        "source":            "hard_rule"
    }
