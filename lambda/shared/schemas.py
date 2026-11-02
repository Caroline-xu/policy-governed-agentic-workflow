"""Output schemas per action node (Appendix B 'Output' fields, verbatim names)."""
from __future__ import annotations

_STR_OR_NULL = {"type": ["string", "null"]}
_NUM_OR_NULL = {"type": ["number", "null"]}
_STR_LIST = {"type": "array", "items": {"type": "string"}}

SCHEMAS = {
    "N01": {
        "type": "object",
        "required": ["claim_type", "policy_number", "claimant_name", "incident_date", "submission_date", 
                     "claimed_amount", "documents", "missing_fields"],
        "properties": {
            "claim_type": {"type": ["string", "null"],
                           "enum": ["TRIP_CANCELLATION", "BAGGAGE_LOSS", "MEDICAL_EXPENSE", None]},
            "policy_number": _STR_OR_NULL,
            "claimant_name": _STR_OR_NULL,
            "incident_date": _STR_OR_NULL,
            "submission_date": _STR_OR_NULL,
            "claimed_amount": _NUM_OR_NULL,
            "documents": {"type": "array", 
                          "items": {
                              "type": "object",
                              "required": ["doc_id", "doc_type", "summary"],
                              "properties": {
                                  "doc_id": {"type": "string"},
                                  "doc_type": {"type": "string"},
                                  "summary": {"type": "string"}
                              }}},
            "missing_fields": _STR_LIST,
        }

    },
    "N02": {
        "type": "object",
        "required": ["within_coverage_period", "benefit_covered"],
        "properties": {
            "within_coverage_period": {"type": "boolean"},
            "benefit_covered": {"type": "boolean"},
        }
    },
    "N03": {
        "type": "object",
        "required": ["days_since_incident", "hospitalization_documented", "deadline_days", "timely"],
        "properties": {
            "days_since_incident": {"type": ["integer", "null"]},
            "hospitalization_documented": {"type": "boolean"},
            "deadline_days": {"type": "integer", "enum": [90, 180]},
            "timely": {"type": "boolean"},
        },
    },
    **{n: {
        "type": "object",
        "required": ["exclusion_outcome", "excluded_items", "eligible_line_items", "required_documents_present", 
                     "missing_documents", "rationale", "policy_citations"],
        "properties": {
            "exclusion_outcome": {"type": "string", "enum": ["NONE", "PARTIAL", "FULL"]},
            "excluded_items": _STR_LIST,
            "eligible_line_items": {
                "type": "array", 
                "items": {
                    "type": "object",
                    "required": ["description", "amount"],
                    "properties": {
                        "description": {"type": "string"},
                        "amount": {"type": "number"}
                    }
                }},
            "required_documents_present": {"type": "boolean"},
            "missing_documents": _STR_LIST,
            "rationale": {"type": "string"},
            "policy_citations": _STR_LIST,
    }} for n in ("N04", "N05", "N06")},
    "N07": {
        "type": "object",
        "required": ["payable_amount", "calculation_steps"],
        "properties": {
            "payable_amount": {"type": "number"},
            "calculation_steps": _STR_LIST,
        },
    },
    "N08": {
        "type": "object",
        "required": ["indicators", "evidence"],
        "properties": {
            "indicators": {"type": "array",
                           "items": {"type": "string", "enum": ["a", "b", "c"]}},
            "evidence": _STR_LIST,
        },
    },
    "N09": {
        "type": "object",
        "required": ["notice_text", "policy_citations"],
        "properties": {
            "notice_text": {"type": "string"},
            "policy_citations": _STR_LIST,
        },
    },

}