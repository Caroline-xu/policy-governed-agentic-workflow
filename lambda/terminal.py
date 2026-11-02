"""Terminal-state Lambda (T01-T10) -- infrastructure, not a graph decision node.

Invoked by every terminal state in the state machine with parameters
{terminal_id, final_status, reason_codes}. Builds the final decision record
(Appendix C format) from the validated execution state, writes it to the
decision table when DECISION_TABLE_NAME is set, and returns the record.
All routing decisions were already made by Choice states; this Lambda
decides nothing.
"""
from __future__ import annotations

import os

TERMINALS = {  # Appendix B terminal nodes, verbatim
    "T01": ("INCOMPLETE", ["INCOMPLETE_CLAIM"]),
    "T02": ("DENIED", ["NOT_COVERED"]),
    "T03": ("DENIED", ["LATE_FILING"]),
    "T04": ("DENIED", ["EXCLUDED"]),
    "T05": ("PENDING_DOCUMENTS", ["MISSING_DOCUMENTS"]),
    "T06": ("DENIED", ["BELOW_DEDUCTIBLE"]),
    "T07": ("REFERRED_SIU", ["FRAUD_INDICATOR"]),
    "T08": ("ADJUSTER_REJECTED", ["ADJUSTER_DECISION"]),
    "T09": ("APPROVED", []),
    "T10": ("NEEDS_REVIEW", ["SYSTEM_ATTEMPTS_EXHAUSTED"]),
}


def build_decision_record(state: dict, terminal_id: str, path: list[str] | None = None) -> dict:
    status, reasons = TERMINALS[terminal_id]
    payable = None
    if terminal_id == "T09" and state.get("payable") is not None:
        # Official convention: payable_amount is the amount actually payable --
        # set only for APPROVED (T09), null otherwise. The N07-computed amount
        # for unpaid terminals (T07/T08) stays visible in the audit trail.
        payable = state["payable"]["payable_amount"]
    return {
        "case_id": state.get("case_id"),
        "final_status": status,
        "reason_codes": reasons,
        "payable_amount": payable,
        "path": path if path is not None else state.get("path", []),
        "policy_sections_relied_on": state.get("policy_sections_relied_on", []),
        "notice_text": (state.get("notice") or {}).get("notice_text"),
        "terminal": terminal_id,
    }


def handler(event, context=None):
    # ASL terminal states invoke with {"terminal_id": "Txx", "state": {...}};
    # a flat state dict with event["terminal"]["terminal_id"] is also accepted.
    if isinstance(event.get("state"), dict):
        state, terminal_id = event["state"], event.get("terminal_id")
    else:
        state, terminal_id = event, (event.get("terminal") or {}).get("terminal_id")
    record = build_decision_record(state, terminal_id)
    table = os.environ.get("DECISION_TABLE_NAME")
    if table:
        try:
            import boto3
            from decimal import Decimal
            item = {k: (Decimal(str(v)) if isinstance(v, float) else v)
                    for k, v in record.items() if v is not None}
            boto3.resource("dynamodb").Table(table).put_item(Item=item)
        except Exception:
            pass
    return record
