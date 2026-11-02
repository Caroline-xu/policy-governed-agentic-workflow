"""Unit tests for N02's coverage check (lambda/shared/coverage.py).

Each test pins one rule from policy section 2: the coverage period
counts both its first and its last day (2.1), and the claim's benefit
must be one of the benefits the policy covers (2.2).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambda"))

from shared.coverage import verify_coverage

POLICY = {
    "coverage_start": "2026-04-10",
    "coverage_end": "2026-04-24",
    "covered_benefits": ["TRIP_CANCELLATION", "BAGGAGE_LOSS", "MEDICAL_EXPENSE"],
}


def facts(incident_date, claim_type="MEDICAL_EXPENSE"):
    return {"incident_date": incident_date, "claim_type": claim_type}


def test_incident_inside_the_period_is_covered():
    result = verify_coverage(POLICY, facts("2026-04-15"))
    assert result["within_coverage_period"] is True
    assert result["benefit_covered"] is True


def test_incident_on_the_last_day_still_counts():
    # Section 2.1 counts both ends. This is the TC-015 edge.
    result = verify_coverage(POLICY, facts("2026-04-24"))
    assert result["within_coverage_period"] is True


def test_incident_on_the_first_day_counts():
    result = verify_coverage(POLICY, facts("2026-04-10"))
    assert result["within_coverage_period"] is True


def test_incident_before_the_trip_is_not_covered():
    result = verify_coverage(POLICY, facts("2026-04-09"))
    assert result["within_coverage_period"] is False


def test_incident_after_the_trip_is_not_covered():
    result = verify_coverage(POLICY, facts("2026-04-25"))
    assert result["within_coverage_period"] is False


def test_a_benefit_the_policy_does_not_list_is_not_covered():
    result = verify_coverage(POLICY, facts("2026-04-15", claim_type="TRIP_DELAY"))
    assert result["benefit_covered"] is False
