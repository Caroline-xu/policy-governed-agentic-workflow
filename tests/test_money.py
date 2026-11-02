"""Unit tests for N07's payable calculation (lambda/shared/money.py).

Each test pins one money rule: medical charges are paid up to the
medical limit with no deductible (6.4); baggage is capped per item
and per claim, minus the deductible (5.3); trip cancellation is paid
up to its limit with no deductible (4.4); and a payable amount never
goes below zero (8.1).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambda"))

from shared.money import calculate_payable

POLICY = {"medical_limit": 10000, "trip_cancellation_limit": 5000}


def item(description, amount):
    return {"description": description, "amount": amount}


def test_medical_charges_are_summed_in_full():
    # The four lines of TC-025's hospital statement.
    result = calculate_payable(
        "MEDICAL_EXPENSE",
        [item("Emergency consultation", 365), item("Otoscopic procedure", 820),
         item("Hearing assessment", 410), item("Medication", 240)],
        POLICY,
    )
    assert result["payable_amount"] == 1835.00


def test_medical_charges_stop_at_the_medical_limit():
    result = calculate_payable(
        "MEDICAL_EXPENSE", [item("Surgery", 12000)], POLICY
    )
    assert result["payable_amount"] == 10000.00


def test_baggage_items_are_capped_at_500_each():
    # Camera 780 counts as 500, sunglasses 210 in full, minus the 100
    # deductible. This is TC-023's arithmetic: 500 + 210 - 100 = 610.
    result = calculate_payable(
        "BAGGAGE_LOSS",
        [item("Camera", 780), item("Sunglasses", 210)],
        POLICY,
    )
    assert result["payable_amount"] == 610.00


def test_baggage_claim_is_capped_at_2000():
    result = calculate_payable(
        "BAGGAGE_LOSS",
        [item("Item A", 500), item("Item B", 500), item("Item C", 500),
         item("Item D", 500), item("Item E", 500)],
        POLICY,
    )
    assert result["payable_amount"] == 1900.00


def test_cancellation_is_paid_up_to_its_limit_with_no_deductible():
    # TC-003's numbers: 1,250 airfare plus 1,200 non-refundable hotel.
    result = calculate_payable(
        "TRIP_CANCELLATION",
        [item("Airfare", 1250), item("Hotel, non-refundable part", 1200)],
        POLICY,
    )
    assert result["payable_amount"] == 2450.00


def test_payable_never_goes_below_zero():
    # Items worth less than the baggage deductible: payable floors at 0.
    # A zero payable is what routes a case to T06.
    result = calculate_payable(
        "BAGGAGE_LOSS", [item("Umbrella", 80)], POLICY
    )
    assert result["payable_amount"] == 0.00
