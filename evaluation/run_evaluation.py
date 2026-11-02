"""Part 3 evaluation harness: STAGE graph vs monolithic baseline, on AWS.

Graph runs go through the deployed Step Functions state machine (model
mode); the baseline is one Bedrock Converse call per case carrying the
full policy text. Both are scored with the same checks as the local
runner. The graph's path is scored from the execution history, which is
the authoritative record (cloud decision records carry path=[]).
"""
from __future__ import annotations

import json
import os
import sys
import time
import boto3
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambda"))

REGION = "us-east-2"
# Fill these from the `cdk deploy` outputs of your own stack (or set the env vars).
STATE_MACHINE_ARN = os.environ.get("STAGE_STATE_MACHINE_ARN", "")
AUDIT_TABLE = os.environ.get("STAGE_AUDIT_TABLE", "")
SIMULATOR_FUNCTION = os.environ.get("STAGE_SIMULATOR_FUNCTION", "")
MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
RUNS = 3


def money_equal(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return round(float(a), 2) == round(float(b), 2)


def score(record: dict, path: list, expected: dict) -> dict:
    return {
        "status": record["final_status"] == expected["final_status"],
        "reason_codes": record["reason_codes"] == expected["reason_codes"],
        "payable": money_equal(record["payable_amount"], expected["payable_amount"]),
        "path": path == expected["path"],
    }

def history_path(sfn, execution_arn: str) -> list[str]:
    """State names in entry order = the path the execution actually took."""
    path: list[str] = []
    token = None
    while True:
        page = (sfn.get_execution_history(executionArn=execution_arn, maxResults=200, nextToken=token)
                if token else sfn.get_execution_history(executionArn=execution_arn, maxResults=200))
        for event in page["events"]:
            if event["type"].endswith("StateEntered"):
                name = event["stateEnteredEventDetails"]["name"]
                if name == "H01Route":
                    continue  # official paths fold H01's exit choice into H01 itself
                if not path or path[-1] != name:
                    path.append(name)
        token = page.get("nextToken")
        if not token:
            return path

def fetch_h01_token(dynamodb, case_id: str, execution_name: str) -> str | None:
    """The H01 audit row for THIS execution carries the task token."""
    resp = dynamodb.query(
        TableName=AUDIT_TABLE,
        KeyConditionExpression="case_id = :c",
        ExpressionAttributeValues={":c": {"S": case_id}},
    )
    for item in resp["Items"]:
        if (item.get("node_id", {}).get("S") == "H01"
                and execution_name in item.get("attempt_key", {}).get("S", "")
                and "task_token" in item):
            return item["task_token"]["S"]
    return None

def run_graph_case(sfn, dynamodb, lam, case: dict, run_no: int,
                   prefix: str = "eval") -> dict:
    """One graph run: start it, auto-resume H01 if it parks, collect the record."""
    case_id = case["case_id"]
    execution_id = f"{prefix}-{case_id}-r{run_no}"
    system_case = {k: v for k, v in case.items() if k not in ("expected", "exercises")}
    body = {"case_id": case_id, "execution_id": execution_id, "case": system_case}
    started = time.time()
    arn = sfn.start_execution(stateMachineArn=STATE_MACHINE_ARN, name=execution_id,
                              input=json.dumps(body))["executionArn"]
    resumed = False
    desc: dict = {}
    while time.time() - started < 600:
        desc = sfn.describe_execution(executionArn=arn)
        if desc["status"] != "RUNNING":
            break
        if (not resumed and case.get("simulated_adjuster_decision")
                and time.time() - started > 20):
            token = fetch_h01_token(dynamodb, case_id, execution_id)
            if token:
                lam.invoke(FunctionName=SIMULATOR_FUNCTION,
                           Payload=json.dumps({
                               "task_token": token,
                               "simulated_adjuster_decision":
                                   case["simulated_adjuster_decision"]}))
                resumed = True
        time.sleep(3)
    record = json.loads(desc["output"]) if desc.get("output") else {}
    return {"execution_id": execution_id, "record": record,
            "path": history_path(sfn, arn),
            "latency_s": round(time.time() - started, 1),
            "exec_status": desc.get("status", "UNKNOWN")}

def run_baseline_case(bedrock, case: dict) -> dict:
    """Monolithic baseline: ONE call — full policy + full case -> verdict JSON."""
    from shared.bedrock_client import _extract_json
    from shared.policy_sections import POLICY_TEXT

    policy = "\n\n".join(f"Section {sid}: {text}"
                         for sid, text in sorted(POLICY_TEXT.items()))
    system_case = {k: v for k, v in case.items() if k not in ("expected", "exercises")}
    prompt = f"""You are an expert travel-insurance claims adjudicator. Decide the claim below by applying the policy. Do the whole job in this single reply: read the documents, apply every rule, compute any amount yourself.

POLICY (complete):
{policy}

OUTPUT — reply with a single JSON object and nothing else, exactly this shape:
{{"final_status": ..., "reason_codes": [...], "payable_amount": ...}}
- final_status is one of: APPROVED, DENIED, INCOMPLETE, PENDING_DOCUMENTS, REFERRED_SIU, ADJUSTER_REJECTED, NEEDS_REVIEW
- reason_codes uses only: INCOMPLETE_CLAIM, NOT_COVERED, LATE_FILING, EXCLUDED, MISSING_DOCUMENTS, BELOW_DEDUCTIBLE, FRAUD_INDICATOR, ADJUSTER_DECISION (empty list when APPROVED)
- payable_amount is a number only when final_status is APPROVED, otherwise null
- If the payable amount would exceed $5,000, a human adjuster decides: the case carries simulated_adjuster_decision (APPROVE or REJECT). APPROVE = approved at that amount; REJECT = final_status ADJUSTER_REJECTED, payable_amount null.

CASE:
{json.dumps(system_case, indent=1, default=str)}"""
    started = time.time()
    resp = bedrock.converse(modelId=MODEL_ID,
                            messages=[{"role": "user",
                                       "content": [{"text": prompt}]}],
                            inferenceConfig={"temperature": 0, "maxTokens": 2000})
    usage = resp.get("usage", {})
    text = resp["output"]["message"]["content"][0]["text"]
    try:
        verdict = json.loads(_extract_json(text))
        record = {"final_status": verdict.get("final_status"),
                  "reason_codes": verdict.get("reason_codes") or [],
                  "payable_amount": verdict.get("payable_amount")}
        parsed = True
    except Exception:
        record = {"final_status": None, "reason_codes": [], "payable_amount": None}
        parsed = False
    return {"record": record, "parsed": parsed,
            "input_tokens": usage.get("inputTokens", 0),
            "output_tokens": usage.get("outputTokens", 0),
            "latency_s": round(time.time() - started, 1)}

def graph_tokens(dynamodb, case_id: str, execution_name: str) -> tuple[int, int]:
    """Sum one execution's audit rows = what that run actually cost in tokens."""
    resp = dynamodb.query(
        TableName=AUDIT_TABLE,
        KeyConditionExpression="case_id = :c",
        ExpressionAttributeValues={":c": {"S": case_id}},
    )
    tin = tout = 0
    for item in resp["Items"]:
        if execution_name in item.get("attempt_key", {}).get("S", ""):
            tin += int(item.get("input_tokens", {}).get("N", 0))
            tout += int(item.get("output_tokens", {}).get("N", 0))
    return tin, tout


def summarise(rows: list[dict], keys: tuple) -> dict:
    by_case: dict[str, list[dict]] = {}
    for r in rows:
        by_case.setdefault(r["case_id"], []).append(r)

    def full(row: dict) -> bool:
        return all(row["checks"][k] for k in keys)

    n = len(by_case)
    pass1 = sum(1 for rs in by_case.values() if full(rs[0]))
    pass3 = sum(1 for rs in by_case.values() if any(full(r) for r in rs))
    return {
        "cases": n, "runs": len(rows),
        "pass1": f"{pass1}/{n}", "pass3": f"{pass3}/{n}",
        "field_accuracy": {k: round(sum(r["checks"][k] for r in rows) / len(rows), 4)
                           for k in keys},
        "mean_input_tokens": round(sum(r["input_tokens"] for r in rows) / len(rows), 1),
        "mean_output_tokens": round(sum(r["output_tokens"] for r in rows) / len(rows), 1),
        "mean_latency_s": round(sum(r["latency_s"] for r in rows) / len(rows), 1),
    }

def main() -> None:
    sfn = boto3.client("stepfunctions", region_name=REGION)
    dynamodb = boto3.client("dynamodb", region_name=REGION)
    lam = boto3.client("lambda", region_name=REGION)
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)

    all_cases = json.loads((REPO / "data" / "demo-test-cases.json")
                           .read_text(encoding="utf-8"))["cases"]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    prefix = "trial" if "--trial" in sys.argv else "eval"
    cases = [c for c in all_cases if not args or c["case_id"] in args]
    if not cases:
        print("no cases selected")
        return
    print(f"{len(cases)} cases x {RUNS} runs, prefix={prefix}")

    graph_rows: list[dict] = []
    baseline_rows: list[dict] = []
    for case in cases:
        expected = case["expected"]
        for r in range(1, RUNS + 1):
            g = run_graph_case(sfn, dynamodb, lam, case, r, prefix)
            gchecks = (score(g["record"], g["path"], expected) if g["record"] else
                       {"status": False, "reason_codes": False,
                        "payable": False, "path": False})
            tin, tout = graph_tokens(dynamodb, case["case_id"], g["execution_id"])
            graph_rows.append({"case_id": case["case_id"], "run": r, "checks": gchecks,
                               "latency_s": g["latency_s"], "input_tokens": tin,
                               "output_tokens": tout, "exec_status": g["exec_status"],
                               "got_status": g["record"].get("final_status"),
                               "got_path": g["path"],
                               "got_payable": g["record"].get("payable_amount")})
            print(f"graph    {case['case_id']} r{r}: {gchecks} in={tin} out={tout} {g['latency_s']}s")

            b = run_baseline_case(bedrock, case)
            ball = score(b["record"], [], expected)
            bchecks = {k: ball[k] for k in ("status", "reason_codes", "payable")}
            baseline_rows.append({"case_id": case["case_id"], "run": r, "checks": bchecks,
                                  "latency_s": b["latency_s"],
                                  "input_tokens": b["input_tokens"],
                                  "output_tokens": b["output_tokens"],
                                  "parsed": b["parsed"],
                                  "got_status": b["record"].get("final_status"),
                                  "got_payable": b["record"].get("payable_amount")})
            print(f"baseline {case['case_id']} r{r}: {bchecks} in={b['input_tokens']} out={b['output_tokens']} {b['latency_s']}s")

    report = {"graph": summarise(graph_rows, ("status", "reason_codes", "payable", "path")),
              "baseline": summarise(baseline_rows, ("status", "reason_codes", "payable")),
              "graph_rows": graph_rows, "baseline_rows": baseline_rows}
    out = REPO / "evaluation" / "evaluation_report.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({"graph": report["graph"], "baseline": report["baseline"]}, indent=1))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
