"""N07 Calculate Payable Amound -- deterministic code (Policy 4.4, 5.3, 6.4, 8.1). No Model."""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
BAGGAGE_ITEM_CAP = Decimal("500")
BAGGAGE_CLAIM_CAP = Decimal("2000")
BAGGAGE_DEDUCTIBLE = Decimal("100")

def _d(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)

def calculate_payable(claim_type: str, eligible_line_items:list[dict], policy: dict) -> dict:
    steps: list[str] = []
    items = [(i["description"], _d(i["amount"])) for i in eligible_line_items]

    if claim_type == "BAGGAGE_LOSS":
        capped = []
        for desc, amount in items:
            after = min(amount, BAGGAGE_ITEM_CAP)
            if after != amount:
                steps.append(f"Per-item cap (5.3): {desc} {amount} -> {after} (max $500/item)")
            capped.append((desc, after))
        subtotal = sum(a for _, a in capped)
        steps.append(f"Eligible subtotal after per-item caps: {subtotal}")
        if subtotal > BAGGAGE_CLAIM_CAP:
            steps.append(f"Per-claim cap (5.3): {subtotal} -> {BAGGAGE_CLAIM_CAP} (max $2,000/claim)")
            subtotal = BAGGAGE_CLAIM_CAP
        deductible = BAGGAGE_DEDUCTIBLE
        steps.append(f"Deductible (5.3): -{deductible}")
    elif claim_type == "TRIP_CANCELLATION":
        subtotal = sum(a for _, a in items)
        limit = _d(policy["trip_cancellation_limit"])
        steps.append(f"Eligible non-refundable prepaid total (4.4): {subtotal}")
        if subtotal > limit:
            steps.append(f"Policy trip-cancellation limit (4.4): {subtotal} -> {limit}")
            subtotal = limit
        deductible = Decimal("0")
        steps.append("Deductible (4.4): none")
    elif claim_type == "MEDICAL_EXPENSE":
        subtotal = sum(a for _, a in items)
        limit = _d(policy["medical_limit"])
        steps.append(f"Eligible itemized emergency charges (6.4): {subtotal}")
        if subtotal > limit:
            steps.append(f"Policy medical limit (6.4): {subtotal} -> {limit}")
            subtotal = limit
        deductible = Decimal("0")
        steps.append("Deductible (6.4): none")
    else:
        raise ValueError(f"Unknow claim_type {claim_type!r}")
    
    payable = subtotal - deductible
    if payable < 0:
        steps.append(f"Floor at $0 (8.1): {payable} -> 0.00")
        payable = Decimal("0")
    payable = payable.quantize(CENT, rounding=ROUND_HALF_UP)
    steps.append(f"Payable amount (8.1): {payable}")
    return {"payable_amount": float(payable), "calculation_steps": steps}