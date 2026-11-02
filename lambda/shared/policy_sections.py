"""Policy-scoped context per node (Appendix B 'Policy:' lines)."""
from __future__ import annotations

PROMPT_VERSION = "v0.1-skeleton"

POLICY_SECTIONS: dict[str, list[str]] = {
    "N01": ["1.1", "1.2"],
    "N03": ["3.1", "3.2"],
    "N04": ["4.1", "4.2", "4.3", "4.4", "7.1", "7.2", "7.3"],
    "N05": ["5.1", "5.2", "5.3", "7.1", "7.2", "7.3"],
    "N06": ["6.1", "6.2", "6.3", "6.4", "7.1", "7.2", "7.3"],
    "N08": ["9.1"],
    "N09": ["11.1", "11.2"],
}

POLICY_TEXT: dict[str, str] = {
    "1.1": "A claim is complete only if it contains: policy number, claimant name, claim type, incident date, claim submission date, claimed amount, and at least one supporting document.",
    "1.2": "Claim type must be TRIP_CANCELLATION, BAGGAGE_LOSS or MEDICAL_EXPENSE. If the form type does not match the supporting documents, the documents take precedence.",
    "3.1": "A claim must be submitted within 90 days of the incident date.",
    "3.2": "If the documents show the claimant was hospitalized at any time during the 90 days following the incident date, the deadline is extended to 180 days.",
    "4.1": "Trip cancellation covered reasons: sickness/injury of claimant or immediate family preventing travel; death of an immediate family member; government advisory against non-essential travel issued after policy purchase.",
    "4.2": "Not covered: change of mind, work commitments, financial reasons, fear of travel without a government advisory.",
    "4.3": "Required: proof of non-refundable cost (an invoice or supplier statement) and proof of the reason (medical note, death certificate, or advisory reference).",
    "4.4": "Eligible: non-refundable prepaid costs only, up to the trip cancellation limit. No deductible.",
    "5.1": "Required: property irregularity report from the carrier, or police report for theft. A receipt is required for any item above $200.",
    "5.2": "Not covered: cash, travel documents, items left unattended in a public place.",
    "5.3": "Limits: $500 per item, $2,000 per claim. Deductible $100 per claim.",
    "6.1": "Covered: emergency treatment for a sudden and unforeseen sickness or injury during the trip.",
    "6.2": "Not covered: treatment related to a pre-existing condition that, in the 90 days before trip start, required a change in medication, a new treatment, or hospitalization. A stable pre-existing condition is covered.",
    "6.3": "Required: itemized medical bills and a physician report describing the diagnosis.",
    "6.4": "Eligible: itemized emergency charges up to the medical limit. No deductible.",
    "7.1": "Exclusions are assessed before document sufficiency. A fully excluded claim is denied even if documents are missing (EXCLUDED).",
    "7.2": "If only some items are excluded, remove them and continue with the remainder.",
    "7.3": "If a required document is missing for the remaining claim: PENDING_DOCUMENTS / MISSING_DOCUMENTS.",
    "9.1": "Refer to SIU if: (a) policy purchased fewer than 14 days before incident AND claimed > $3,000; (b) dates/amounts in documents inconsistent with each other or the claim form; (c) more than two prior claims in the 12 months before submission.",
    "11.1": "Every claim reaching a final status produces a decision record: status, reason codes, payable amount where applicable, policy sections relied on.",
    "11.2": "Approved claims also receive a plain-language notice explaining the decision and the amount.",
}
