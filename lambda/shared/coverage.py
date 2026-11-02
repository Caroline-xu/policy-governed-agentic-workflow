"""N02 Verify Coverage -- deterministic code (Policy 2.1, 2.2). No Model."""
from __future__ import annotations
from datetime import date

def verify_coverage(policy: dict, facts: dict) -> dict:
    incident = date.fromisoformat(facts["incident_date"])
    start = date.fromisoformat(policy["coverage_start"])
    end = date.fromisoformat(policy["coverage_end"])
    within = start <= incident <= end
    benefit = facts["claim_type"] in policy.get("covered_benefits", [])
    return {"within_coverage_period": within, "benefit_covered": benefit}