"""Amazon Bedrock wrapper for model-backed nodes (model mode).

Model mode is used only when NODE_MODE=model. It needs boto3 and Bedrock
access for Claude Haiku 4.5 in your own AWS account -- NOT yet
verified (see README prerequisites). In mock mode nothing here is called.

The prompt contains ONLY the node's policy sections (policy_sections.py)
plus the case slice the node needs. The model is asked to return JSON
matching the node's schema; the caller validates that JSON before use.
The schema has no 'next node' field: the model never chooses routing.
"""
from __future__ import annotations

import json
import os

MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-haiku-4-5")
# Token usage is returned by Bedrock Converse; skeleton records it when present.
from .schemas import SCHEMAS
from .policy_sections import POLICY_SECTIONS, POLICY_TEXT, PROMPT_VERSION

def build_prompt(node_id: str, case_slice: dict) -> str:
    sections = POLICY_SECTIONS[node_id]
    policy_text = "\n".join(f"[{s}] {POLICY_TEXT[s]}" for s in sections)
    return (
        f"You are node {node_id} in a fixed insurance claim triage graph. "
        f"Do ONLY this node's task. Return JSON only.\n"
        f"Policy sections for this node ONLY:\n{policy_text}\n"
        f"Case data for this node:\n{json.dumps(case_slice, default=str)}\n"
        f"Your reply must be a single JSON object with EXACTLY this shape "
        f"(same field names, same types):\n{json.dumps(SCHEMAS[node_id])}\n"
        f"Prompt version: {PROMPT_VERSION}"
    )

def _extract_json(text: str) -> str:
    """Models sometimes wrap JSON in markdown fences or a sentence of prose.
    Return the outermost {...} block; if there is none, return the text
    unchanged so json.loads raises the honest error."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return text
    return text[start : end + 1]


def invoke_model(node_id: str, case_slice: dict) -> tuple[dict, dict]:
    """Returns (parsed_json_output, usage) where usage has token counts."""
    try:
        import boto3  # available in the Lambda runtime; not required locally
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "NODE_MODE=model but boto3 is unavailable; run in mock mode or in Lambda"
        ) from exc
    client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    resp = client.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": build_prompt(node_id, case_slice)}]}],
        inferenceConfig={"temperature": 0, "maxTokens": 2000},
    )
    text = resp["output"]["message"]["content"][0]["text"]
    usage = resp.get("usage", {})
    return json.loads(_extract_json(text)), {
        "input_tokens": usage.get("inputTokens", 0),
        "output_tokens": usage.get("outputTokens", 0),
        "model_id": MODEL_ID,
        "prompt_version": PROMPT_VERSION,
    }
