"""Local evaluation runner -- mirrors state_machine/definition.asl.json.

For each test case: run N01..N09 with at most 2 attempts per node (a schema
ValidationError consumes an attempt and retries); attempts exhausted -> T10.
D01-D08 route on validated outputs only. H01 pauses are answered from the
case's simulated_adjuster_decision (see lambda/h01_simulator.py).
Emits results/decision_records.json, results/audit_records.json and
results/summary.json (scored against `expected` when present).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambda"))

from h01_simulator import simulated_decision  # noqa: E402
from shared.node_base import MODEL_NODES, apply_output, node_logic  # noqa: E402
from shared.policy_sections import POLICY_SECTIONS, PROMPT_VERSION  # noqa: E402
from shared.validation import ValidationError  # noqa: E402
from terminal import build_decision_record  # noqa: E402

MAX_ATTEMPTS = 2

# Sections each node relies on (Appendix A numbering). Used for the decision
# record's policy_sections_relied_on; the model prompt slices live in
# shared/policy_sections.py (POLICY_SECTIONS).
NODE_SECTIONS = {
    "N01": ["1.1", "1.2"], "N02": ["2"], "N03": ["3.1", "3.2"],
    "N04": POLICY_SECTIONS["N04"], "N05": POLICY_SECTIONS["N05"],
    "N06": POLICY_SECTIONS["N06"], "N07": ["7.1", "7.2", "7.3"],
    "N08": ["9.1", "9.2"], "N09": ["8.1"], "H01": ["10"],
}
ROUTE_BY_TYPE = {"TRIP_CANCELLATION": "N04", "BAGGAGE_LOSS": "N05",
                 "MEDICAL_EXPENSE": "N06"}

def run_case(case: dict, execution_id: str) -> tuple[dict, list[dict]]:
    case_id = case["case_id"]
    # The system under test never sees `expected` (the answer key) or
    # `exercises` (the official conventions forbid passing it to the system).
    system_case = {k: v for k, v in case.items()
                   if k not in ("expected", "exercises")}
    state: dict = {"case_id": case_id, "execution_id": execution_id,
                   "case": system_case}
    path: list[str] = []
    audit: list[dict] = []
    sections: list[str] = []

    def note_sections(node: str) -> None:
        for s in NODE_SECTIONS[node]:
            if s not in sections:
                sections.append(s)

    def attempt_node(node: str) -> bool:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.perf_counter()
            error = None
            try:
                output, _usage = node_logic(node, state)
                updated = apply_output(state, node, output)
            except ValidationError as exc:
                error = str(exc)
            latency = int((time.perf_counter() - started) * 1000)
            audit.append({
                "case_id": case_id,
                "execution_id": execution_id,
                "attempt_key": f"{execution_id}#{node}#{attempt}",
                "node_id": node,
                "attempt": attempt,
                "outcome": "PASS" if error is None else "FAIL",
                "validation_error": error,
                "model_id": ("mock (NODE_MODE=mock)" if node in MODEL_NODES
                             else "none"),
                "prompt_version": PROMPT_VERSION if node in MODEL_NODES else "none",
                "input_tokens": 0,
                "output_tokens": 0,
                "latency_ms": latency,
                "policy_sections": NODE_SECTIONS[node],
                "transition": None,  # back-filled by terminal() once path is final
            })
            if error is None:
                state.update(updated)
                note_sections(node)
                path.append(node)
                return True
        return False

    def terminal(tid: str) -> tuple[dict, list[dict]]:
        state["policy_sections_relied_on"] = sections
        record = build_decision_record(state, tid, path + [tid])
        full = path + [tid]
        for row in audit:
            rows_of_node = [r for r in audit if r["node_id"] == row["node_id"]]
            idx = rows_of_node.index(row)
            occ = [i for i, p in enumerate(full) if p == row["node_id"]]
            if idx < len(occ) and occ[idx] + 1 < len(full):
                row["transition"] = f"{row['node_id']}->{full[occ[idx] + 1]}"
        return record, audit

    # ---- graph walk (mirrors definition.asl.json) ----
    if not attempt_node("N01"):
        return terminal("T10")
    path.append("D01")
    if state["facts"]["missing_fields"]:  # D01
        return terminal("T01")
    if not attempt_node("N02"):
        return terminal("T10")
    path.append("D02")
    cov = state["coverage"]
    if not (cov["within_coverage_period"] and cov["benefit_covered"]):  # D02
        return terminal("T02")
    if not attempt_node("N03"):
        return terminal("T10")
    path.append("D03")
    if not state["deadline"]["timely"]:  # D03
        return terminal("T03")
    assess = ROUTE_BY_TYPE[state["facts"]["claim_type"]]  # D04
    path.append("D04")
    if not attempt_node(assess):
        return terminal("T10")
    path.append("D05")
    a = state["assessment"]
    if a["exclusion_outcome"] == "FULL":  # D05: exclusion (7.1) before documents
        return terminal("T04")
    if not a["required_documents_present"]:
        return terminal("T05")
    if not attempt_node("N07"):
        return terminal("T10")
    path.append("D06")
    if not state["payable"]["payable_amount"] > 0:  # D06
        return terminal("T06")
    if not attempt_node("N08"):
        return terminal("T10")
    path.append("D07")
    if state["fraud"]["indicators"]:  # D07
        return terminal("T07")
    path.append("D08")
    if state["payable"]["payable_amount"] > 5000:  # D08 / H01 (section 10)
        decision = simulated_decision(case)
        path.append("H01")
        note_sections("H01")
        audit.append({
            "case_id": case_id, "execution_id": execution_id,
            "attempt_key": f"{execution_id}#H01#1", "node_id": "H01",
            "attempt": 1, "outcome": decision, "validation_error": None,
            "model_id": "none (human)", "prompt_version": "none",
            "input_tokens": 0, "output_tokens": 0, "latency_ms": 0,
            "policy_sections": NODE_SECTIONS["H01"], "transition": None,
        })
        if decision == "REJECT":
            return terminal("T08")
    if not attempt_node("N09"):
        return terminal("T10")
    return terminal("T09")

def money_equal(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return round(float(a), 2) == round(float(b), 2)

def main() -> int:
    cases_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "data" / "demo-test-cases.json"
    raw = json.loads(cases_path.read_text())
    cases = raw["cases"] if isinstance(raw, dict) else raw
    results_dir = REPO / "results"
    results_dir.mkdir(exist_ok=True)
    records, audits, rows = [], [], []
    passed = 0
    for case in cases:
        record, audit = run_case(case, f"local-{case['case_id']}")
        records.append(record)
        audits.extend(audit)
        exp = case["expected"]
        checks = {
            "status": record["final_status"] == exp["final_status"],
            "reason_codes": record["reason_codes"] == exp["reason_codes"],
            "payable": money_equal(record["payable_amount"], exp["payable_amount"]),
            "path": record["path"] == exp["path"],
        }
        ok = all(checks.values())
        passed += ok
        rows.append({"case_id": case["case_id"], "pass": ok, "checks": checks,
                     "got": {"status": record["final_status"],
                             "reason_codes": record["reason_codes"],
                             "payable_amount": record["payable_amount"],
                             "path": record["path"]},
                     "expected": exp})
        detail = " ".join(f"{k}={'OK' if v else 'FAIL'}" for k, v in checks.items())
        print(f"{case['case_id']}: {'PASS' if ok else 'FAIL'}  {detail}  "
              f"status={record['final_status']} payable={record['payable_amount']}")
    summary = {"cases_run": len(cases), "passed": passed,
               "failed": len(cases) - passed, "results": rows}
    (results_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    (results_dir / "decision_records.json").write_text(json.dumps(records, indent=2))
    (results_dir / "audit_records.json").write_text(json.dumps(audits, indent=2))
    print(f"\n{passed}/{len(cases)} cases match expected final_status, reason_codes, "
          f"payable_amount (to the cent) and path.")
    print(f"Wrote results/summary.json, results/decision_records.json, "
          f"results/audit_records.json ({len(audits)} audit rows)")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
