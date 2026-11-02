"""H01 evaluation simulator -- NOT a node and NOT the human decision itself.

H01 in the state machine is a Step Functions callback task
(dynamodb:putItem.waitForTaskToken): the execution pauses and an external
actor resumes it with SendTaskSuccess. For automated evaluation runs the
assignment allows that external decision to come from a simulator reading
`simulated_adjuster_decision` (APPROVE / REJECT) from the test case.

Local use: simulated_decision(case) is what local_runner calls at H01.
AWS use: handler(event) expects {task_token, simulated_adjuster_decision}
and calls sfn:SendTaskSuccess with output {"decision": <value>}.
"""
from __future__ import annotations

import json
import os


def simulated_decision(case: dict) -> str:
    decision = case.get("simulated_adjuster_decision")
    if decision not in ("APPROVE", "REJECT"):
        raise ValueError(
            f"Case {case.get('case_id')} reached H01 but simulated_adjuster_decision "
            f"is {decision!r}; a case that passes H01 must carry APPROVE or REJECT "
            "(Appendix C). Refusing to invent an adjuster decision.")
    return decision


def handler(event, context=None):
    import boto3
    sfn = boto3.client("stepfunctions", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    decision = event["simulated_adjuster_decision"]
    if decision not in ("APPROVE", "REJECT"):
        raise ValueError(f"simulated_adjuster_decision must be APPROVE or REJECT, got {decision!r}")
    sfn.send_task_success(taskToken=event["task_token"],
                          output=json.dumps({"decision": decision}))
    return {"decision": decision, "resumed": True}
