"""Document-text parsing helpers used ONLY by the skeleton mock heuristics."""
from __future__ import annotations

import re
from decimal import Decimal

def to_decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))

def classify_doc(text: str) -> str:
    t = text.lower()
    if "property irregularity" in t:
        return "property_irregularity_report"
    if "police report" in t:
        return "police_report"
    if "physician report" in t:
        return "physician_report"
    if "itemized" in t:
        return "itemized_statement"
    if "death certificate" in t:
        return "death_certificate"
    if "medical note" in t:
        return "medical_note"
    if "supplier statement" in t or "invoice" in t:
        return "supplier_statement"
    if "item list" in t or "lost items" in t:
        return "claimant_item_list"
    if "advisory" in t:
        return "advisory_reference"
    return "other"

def find_total(text: str) -> Decimal | None:
    m = re.search(r"[Tt]otal[^0-9]{0,30}?(\d{1,3}(?:,\d{3})*\.\d{2})", text)
    return to_decimal(m.group(1)) if m else None

LABELLED_AMOUNT_RE = re.compile(
    r"([A-Za-z][A-Za-z '&/()\-]{1,60}?)\s*[:\-]?\s*\$?(\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})"
)

def _clean_desc(raw: str) -> str:
    # Take the segment after the last sentence/label boundary before the amount.
    seg = re.split(r"[.\n]", raw)[-1]
    seg = seg.split(":")[-1] if seg.rstrip().endswith(("items", "costs")) is False else seg
    seg = re.sub(r"^(lost items?|items?|total|value)\b", "", seg.strip(" :-,"), flags=re.I)
    seg = re.sub(r"\bvalue\s*$", "", seg.strip(" :-,"), flags=re.I)
    return (seg.strip(" :-," ).capitalize() or "Item")

def parse_labelled_amounts(text: str) -> list[dict]:
    """Extract [{description, amount, receipt}] from free text.
    Drops a 'Total ...' line when other items already sum to it, so totals
    are not double-counted as line items.
    """
    items: list[dict] = []
    for m in LABELLED_AMOUNT_RE.finditer(text):
        desc = _clean_desc(m.group(1))
        amount = to_decimal(m.group(2))
        tail = text[m.end():m.end() + 40].lower()
        receipt = None
        if "no receipt" in tail:
            receipt = False
        elif "receipt" in tail:
            receipt = True
        items.append({"description": desc, "amount": amount, "receipt": receipt,
                      "_is_total": "total" in m.group(1).lower()})
    non_total = [i for i in items if not i["_is_total"]]
    totals = [i for i in items if i["_is_total"]]
    if totals and non_total and sum(i["amount"] for i in non_total) == totals[0]["amount"]:
        items = non_total
    elif totals and not non_total:
        items = totals  # a single total-only document: treat the total as one item
    for i in items:
        i.pop("_is_total", None)
    return items
