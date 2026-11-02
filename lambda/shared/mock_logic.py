"""Skeleton mock heuristics for the model-backed nodes.
*** SKELETON ONLY -- labelled heuristics, not final model logic. ***
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal

from .parsing import classify_doc, find_total, parse_labelled_amounts

DOC_SIGNALS = {
    "TRIP_CANCELLATION": [("non-refundable", 3), ("supplier statement", 2),
                          ("cancel my booking", 2), ("cancelled my trip", 2), ("cancel the trip", 1)],
    "MEDICAL_EXPENSE": [("itemized", 2), ("physician report", 2), ("diagnosis", 1), ("hospital", 1)],
    "BAGGAGE_LOSS": [("property irregularity", 3), ("lost items", 2), ("suitcase", 1)],
}


def _docs_text(case: dict) -> str:
    return "\n".join(d.get("text", "") for d in case.get("documents", []))


def resolve_claim_type(case: dict) -> str | None:
    """Policy 1.2: the claim type described in the documents wins over the form."""
    form_type = (case.get("claim_form") or {}).get("claim_type")
    docs = _docs_text(case).lower()
    if not docs.strip():
        return form_type
    scores = {t: sum(w for kw, w in sigs if kw in docs) for t, sigs in DOC_SIGNALS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else form_type

# N01
def mock_n01(case: dict) -> dict:
    policy, form = case.get("policy") or {}, case.get("claim_form") or {}
    documents = [{"doc_id": d.get("doc_id", f"D{i+1}"),
                  "doc_type": classify_doc(d.get("text", "")),
                  "summary": d.get("text", "")[:120]}
                 for i, d in enumerate(case.get("documents", []))]
    facts = {
        "claim_type": resolve_claim_type(case),
        "policy_number": policy.get("policy_number"),
        "claimant_name": form.get("claimant_name"),
        "incident_date": form.get("incident_date"),
        "submission_date": form.get("submission_date"),
        "claimed_amount": form.get("claimed_amount"),
        "documents": documents,
    }
    # 1.1 mandatory-field checklist is CODE on the validated extraction, not model say-so.
    missing = [k for k in ("policy_number", "claimant_name", "claim_type", "incident_date",
                           "submission_date", "claimed_amount") if facts.get(k) in (None, "")]
    if not documents:
        missing.append("documents")
    facts["missing_fields"] = missing
    return facts

# N03
def hospitalization_documented(case: dict, incident: date) -> bool:
    """N03's one bounded model question (3.2), as a skeleton heuristic.

    True only for an explicit admission whose start date falls in the
    90 days after the incident. Explicit negations win ('not admitted') 
    -- TC-103 is built to catch the naive keyword match.
    """
    text = _docs_text(case)
    low = text.lower()
    if "not admitted" in low or "not hospitalized" in low or "not hospitalised" in low:
        return False
    for pattern in (r"admitted to hospital from (\d{4}-\d{2}-\d{2})",
                r"hospitalized (\d{4}-\d{2}-\d{2})",
                r"admission (\d{4}-\d{2}-\d{2})"):
        for m in re.finditer(pattern, low):
            start = date.fromisoformat(m.group(1))
            if incident <= start <= incident + timedelta(days=90):
                return True
    return False

def mock_n03(case: dict, facts: dict) -> dict:
    incident = date.fromisoformat(facts["incident_date"])
    submission = date.fromisoformat(facts["submission_date"])
    days = (submission - incident).days
    hosp = hospitalization_documented(case, incident)
    deadline = 180 if hosp else 90
    return {"days_since_incident": days, "hospitalization_documented": hosp,
            "deadline_days": deadline, "timely": days <= deadline}

# N04, N05, N06
def _items_from_docs(case: dict, doc_types: tuple[str, ...]) -> list[dict]:
    items: list[dict] = []
    for d in case.get("documents", []):
        if classify_doc(d.get("text", "")) in doc_types:
            items.extend(parse_labelled_amounts(d.get("text", "")))
    return items

def _as_line_items(items: list[dict]) -> list[dict]:
    return [{"description": i["description"], "amount": float(i["amount"])} for i in items]


def mock_n04(case: dict, facts: dict) -> dict:
    combined = ((case.get("claim_form") or {}).get("description", "") + "\n" + _docs_text(case)).lower()
    items = _items_from_docs(case, ("supplier_statement",))
    doc_types = {d["doc_type"] for d in facts["documents"]}
    missing = []

    if not any("non-refundable" in d.get("text", "").lower() for d in case.get("documents", [])):
        missing.append("proof of non-refundable cost (4.3)")
    if not (doc_types & {"medical_note", "death_certificate", "advisory_reference"}):
        missing.append("proof of cancellation reason (4.3)")
        
    not_covered = [p for p in ("changed my mind", "change of mind", "work commitment",
                           "financial reasons", "fear of travel") if p in combined]
    if not_covered:
        return {"exclusion_outcome": "FULL", "excluded_items": [i["description"] for i in items] or ["Entire trip cancellation claim"],
                "eligible_line_items": [], "required_documents_present": not missing, "missing_documents": missing,
                "rationale": f"Cancellation reason is not covered under 4.2: matched '{not_covered[0]}'.",
                "policy_citations": ["4.2", "7.1"]}

    return {"exclusion_outcome": "NONE", "excluded_items": [],
            "eligible_line_items": _as_line_items(items),
            "required_documents_present": not missing, "missing_documents": missing,
            "rationale": "Covered cancellation reason (4.1) with required documents checked against 4.3.",
            "policy_citations": ["4.1", "4.3", "7.1", "7.3"]}


BAGGAGE_EXCLUDED_WORDS = ("cash", "passport", "travel document")

def mock_n05(case: dict, facts: dict) -> dict:
    combined = _docs_text(case).lower()
    items = _items_from_docs(case, ("claimant_item_list",))
    if not items:  # fall back to any document carrying labelled amounts
        items = _items_from_docs(case, ("property_irregularity_report",))
    doc_types = {d["doc_type"] for d in facts["documents"]}
    missing = []
    if not (doc_types & {"property_irregularity_report", "police_report"}):
        missing.append("property irregularity report or police report (5.1)")

    excluded, eligible = [], []
    for item in items:
        desc_low = item["description"].lower()
        if any(w in desc_low for w in BAGGAGE_EXCLUDED_WORDS) or "unattended" in combined and "unattended" in desc_low:
            excluded.append(item)
        else:
            eligible.append(item)
            # Receipt rule is CODE (5.1): eligible item > $200 needs a receipt.
            if item["amount"] > Decimal("200") and item.get("receipt") is not True:
                missing.append(f"receipt for {item['description']} (5.1)")

    if excluded and eligible:
        outcome = "PARTIAL"
    elif excluded:
        outcome = "FULL"
    else:
        outcome = "NONE"
    return {"exclusion_outcome": outcome,
            "excluded_items": [i["description"] for i in excluded],
            "eligible_line_items": _as_line_items(eligible),
            "required_documents_present": not missing, "missing_documents": missing,
            "rationale": "Item-by-item assessment under 5.1/5.2; excluded items removed per 7.2.",
            "policy_citations": ["5.1", "5.2", "7.1", "7.2", "7.3"]}


def mock_n06(case: dict, facts: dict) -> dict:
    items = _items_from_docs(case, ("itemized_statement",))
    doc_types = {d["doc_type"] for d in facts["documents"]}
    missing = []
    if "itemized_statement" not in doc_types:
        missing.append("itemized medical bill (6.3)")
    if "physician_report" not in doc_types:
        missing.append("physician report (6.3)")

    text = _docs_text(case).lower()
    # 6.2 skeleton heuristic: a pre-existing condition excludes ONLY if the text
    # shows instability (medication change / new treatment / related
    # hospitalization) in the 90 days before the trip. 'Unchanged' / 'stable'
    # wording (TC-001) keeps it covered.
    unstable = any(p in text for p in ("medication was changed", "dose was increased",
                                    "new treatment was started", "treatment was changed"))
    stable = any(p in text for p in ("unchanged", "stable"))
    # NOTE: the mock checks wording only -- it does not date the change, so the
    # 90-day window itself is not verified here (the model judges timing in
    # model mode).
    if "pre-existing" in text and unstable and not stable:
        return {"exclusion_outcome": "FULL", "excluded_items": ["Entire medical claim"],
                "eligible_line_items": [], "required_documents_present": not missing,
                "missing_documents": missing,
                "rationale": "Pre-existing condition was not stable in the 90 days before the trip (6.2).",
                "policy_citations": ["6.2", "7.1"]}
    return {"exclusion_outcome": "NONE", "excluded_items": [],
            "eligible_line_items": _as_line_items(items),
            "required_documents_present": not missing, "missing_documents": missing,
            "rationale": "Emergency treatment for a sudden condition (6.1); any pre-existing condition documented as stable / unrelated (6.2).",
            "policy_citations": ["6.1", "6.2", "6.3", "7.1", "7.3"]}

# N08
def mock_n08(case: dict, facts: dict) -> dict:
    policy, form = case.get("policy") or {}, case.get("claim_form") or {}
    indicators, evidence = [], []
    # 9.1(a) -- code
    purchase = date.fromisoformat(policy["purchase_date"])
    incident = date.fromisoformat(facts["incident_date"])
    claimed = Decimal(str(form.get("claimed_amount") or 0))
    if (incident - purchase).days < 14 and claimed > Decimal("3000"):
        indicators.append("a")
        evidence.append(f"9.1(a): policy purchased {(incident - purchase).days} days before incident (<14) and claimed {claimed} > 3000")
    # 9.1(b) -- code hard check: document totals vs claimed amount
    for d in case.get("documents", []):
        total = find_total(d.get("text", ""))
        if total is not None and claimed and abs(total - claimed) > Decimal("0.01"):
            indicators.append("b")
            evidence.append(f"9.1(b): document {d.get('doc_id')} total {total} != claimed amount {claimed}")
            break
    # 9.1(c) -- code
    prior = policy.get("prior_claims_last_12_months", 0)
    if prior > 2:
        indicators.append("c")
        evidence.append(f"9.1(c): prior_claims_last_12_months = {prior} (> 2)")
    return {"indicators": indicators, "evidence": evidence}

# N09
def mock_n09(case: dict, facts: dict, payable_amount: float, sections: list[str]) -> dict:
    """Model writes in model mode; mock mode uses the fallback template --
    which is also the production fallback if verification of a model draft fails."""
    amount = f"{payable_amount:.2f}"
    notice = (
        f"Dear {facts.get('claimant_name')}, your claim {facts.get('policy_number')} has been "
        f"approved. We will pay you ${amount} CAD. This decision is based on policy sections "
        f"{', '.join(sections)}."
    )
    return {"notice_text": notice, "policy_citations": sections}
