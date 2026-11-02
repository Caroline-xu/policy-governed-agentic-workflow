"""Shared node execution: logic + validation + state merge."""
from __future__ import annotations
from datetime import date

import os
import time

from . import mock_logic
from .bedrock_client import MODEL_ID, invoke_model
from .coverage import verify_coverage
from .money import calculate_payable
from .policy_sections import POLICY_SECTIONS, PROMPT_VERSION
from .schemas import SCHEMAS
from .validation import validate_or_raise

MODE = os.environ.get("NODE_MODE", "mock")
STATE_KEY = {"N01": "facts", "N02": "coverage", "N03": "deadline", "N04": "assessment",
             "N05": "assessment", "N06": "assessment", "N07": "payable", "N08": "fraud",
             "N09": "notice"}
MODEL_NODES = {"N01", "N03", "N04", "N05", "N06", "N08", "N09"}

def node_logic(node_id: str, state: dict) -> tuple[dict, dict]:
    case = state["case"]
    facts = state.get("facts") or {}
    model = MODE == "model" and node_id in MODEL_NODES
    usage = {"input_tokens": 0, "output_tokens": 0}

    def call(nid: str, slice_: dict) -> dict:
        out, u = invoke_model(nid, slice_)
        usage["input_tokens"] += int(u.get("input_tokens", 0))
        usage["output_tokens"] += int(u.get("output_tokens", 0))
        return out

    if node_id == "N01":
        output = call("N01", case) if model else mock_logic.mock_n01(case)
    elif node_id == "N02":
        output = verify_coverage(case["policy"], facts)
    elif node_id == "N03":
        if model:
            model_out = call("N03", case)
            base = mock_logic.mock_n03(case, facts)
            hosp = bool(model_out.get("hospitalization_documented", base["hospitalization_documented"]))
            days = (date.fromisoformat(facts["submission_date"]) - date.fromisoformat(facts["incident_date"])).days
            deadline = 180 if hosp else 90
            output = {"days_since_incident": days, "hospitalization_documented": hosp,
                      "deadline_days": deadline, "timely": days <= deadline}
        else:
            output = mock_logic.mock_n03(case, facts)
    elif node_id in ("N04", "N05", "N06"):
        if model:
            output = call(node_id, {"case": case, "facts": facts})
        else:
            output = {"N04": mock_logic.mock_n04, "N05": mock_logic.mock_n05,
                      "N06": mock_logic.mock_n06}[node_id](case, facts)
    elif node_id == "N07":
        assessment = state["assessment"]
        output = calculate_payable(facts["claim_type"], assessment["eligible_line_items"], case["policy"])
    elif node_id == "N08":
        output = mock_logic.mock_n08(case, facts)
        if model:
            model_out = call("N08", {"case": case, "facts": facts})
            if "b" in model_out.get("indicators", []) and "b" not in output["indicators"]:
                output["indicators"].append("b")
                output["evidence"].extend(model_out.get("evidence", []))
    elif node_id == "N09":
        sections = state.get("policy_sections_relied_on") or POLICY_SECTIONS["N09"]
        payable = state["payable"]["payable_amount"]
        if model:
            output = call("N09", {"facts": facts, "payable_amount": payable,
                                "policy_sections": sections})
            if f"{payable:.2f}" not in output.get("notice_text", ""):
                output = mock_logic.mock_n09(case, facts, payable, sections)
        else:
            output = mock_logic.mock_n09(case, facts, payable, sections)
    else:
        raise ValueError(f"Unknown node {node_id}")

    return validate_or_raise(node_id, output, SCHEMAS[node_id]), usage

def apply_output(state: dict, node_id: str, output: dict) -> dict:
    new_state = dict(state)
    new_state[STATE_KEY[node_id]] = output
    return new_state

def _audit(state: dict, node_id: str, attempt: int, latency_ms: int, outcome: str, transition: str = "", usage: dict | None = None, error: str = "") -> None:
    table = os.environ.get("AUDIT_TABLE_NAME")
    if not table:
        return
    try:
        import boto3
        boto3.resource("dynamodb").Table(table).put_item(Item={
            "case_id": state.get("case_id", "unknown"),
            "attempt_key": f"{state.get('execution_id', 'unknown')}#{node_id}#{attempt}",
            "execution_id": state.get("execution_id", "unknown"),
            "node_id": node_id, "attempt": attempt,
            "model_id": MODEL_ID if (MODE == "model" and node_id in MODEL_NODES) else "none",
            "prompt_version": PROMPT_VERSION if node_id in MODEL_NODES else "none",
            "input_tokens": int((usage or {}).get("input_tokens", 0)),
            "output_tokens": int((usage or {}).get("output_tokens", 0)),
            "validation_outcome": outcome, "transition": transition,
            "error": error,
            "latency_ms": latency_ms})
    except Exception:
        pass

def make_handler(node_id: str):
    def handler(event, context=None):
        started = time.time()
        try:
            output, usage = node_logic(node_id, event)
        except Exception as exc:  # audit EVERY failed attempt, then let SFN Retry/Catch act
            _audit(event, node_id, 1, int((time.time() - started) * 1000), "FAIL", error=str(exc)[:512])
            raise
        _audit(event, node_id, 1, int((time.time() - started) * 1000), "PASS", usage=usage)
        return apply_output(event, node_id, output)
    return handler

