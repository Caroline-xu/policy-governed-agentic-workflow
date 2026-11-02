# Policy-Governed Agentic Workflow on AWS

This project puts a fixed insurance-claims process on AWS. Each claim follows
the same set of steps, in the same order - an AI model is used only inside
individual steps, where it reads claim documents and makes a bounded judgment.
The model never decides which step comes next; that is done by a state machine.

The policy is fictional (travel-insurance claim triage, all amounts in CAD),
but the system is real and deployed: it ran a full evaluation on AWS, and the
aggregate results are included in this repo.

- **Coordinator:** AWS Step Functions, Standard type. The flow is defined in
  an ASL file and does not change at run time.
- **Steps:** one Python 3.12 Lambda per action node (N01–N09). Each node gets
  only the policy sections and case data it is allowed to use, returns a result
  in a fixed shape, and that result is checked against a schema before the
  state machine moves on.
- **Human step:** if the payable amount is above $5,000, the claim pauses at
  H01 and waits for a person's approve / reject decision.
- **Records:** every node writes an audit record, and every finished case
  writes one decision record, both in DynamoDB.
- **Model:** Amazon Bedrock, Claude Haiku 4.5
  (`us.anthropic.claude-haiku-4-5-20251001-v1:0`), called through the Converse
  API, temperature 0.
- **Infrastructure:** AWS CDK in TypeScript, region us-east-2.

## Repository layout

```
package.json          npm scripts: build, typecheck, deploy, destroy, synth
package-lock.json     locked dependency versions
tsconfig.json         TypeScript compiler settings
cdk.json              CDK app configuration
bin/app.ts            CDK entry point
lib/stage-stack.ts    the CDK stack: Lambdas, tables, bucket, roles, state machine
lambda/
  n01.py … n09.py     thin entry points, one per node: handler = make_handler("N0x")
  terminal.py         shared handler for the ten endings T01–T10; writes the decision record
  h01_simulator.py    evaluation only: resumes H01 on behalf of the test cases
  shared/
    node_base.py      the shared node wrapper: run logic, validate, write audit row
    bedrock_client.py prompt building and the single place that calls Bedrock
    schemas.py        the fixed output shape for each node
    validation.py     checks a node's output against its schema
    mock_logic.py     plain-code versions of the nodes, used by the local runner
    parsing.py        reads claim documents: classifies them, extracts amounts
    policy_sections.py  the policy text slices each node is allowed to see
    coverage.py       the coverage check used by N02 (plain code)
    money.py          the payable-amount calculation used by N07 (plain code)
state_machine/
  definition.asl.json the frozen flow: 29 states (N01–N09, D01–D08, H01, H01Route, T01–T10)
data/
  demo-test-cases.json      12 synthetic demo cases, written for this repo
local_runner/
  run_local.py        runs the same flow on your own machine, in mock mode, no AWS
evaluation/
  run_evaluation.py   the Part 3 evaluation: graph vs single-call baseline, on AWS
  evaluation_report.json  aggregate evaluation results
tests/                unit tests
  test_coverage.py
  test_money.py
results/              output of the local runner (summary, decision records, audit records)
```

## Prerequisites

- Node.js with npm, to build and deploy the CDK stack.
- An AWS account, with AWS CLI credentials set up on your machine.
- Amazon Bedrock access enabled for Claude Haiku 4.5 in us-east-2.
- Python 3, for the local runner and the evaluation script.

## Deploy

```bash
npm install
npm run build
npx cdk bootstrap   # first time only, for this account and region
npm run deploy
```

When the deploy finishes, CDK prints the state machine ARN, the DynamoDB
table names, the bucket name, and the name of the H01 simulator function.

The deployed Lambdas run in model mode: `NODE_MODE` is set to `'model'` in
`lib/stage-stack.ts`. Nodes that were designed as plain code (N02, N07, and
the code parts of N03 and N08) never call the model in either mode.

Two spot checks were run live on the deployed stack: one case that went
straight through to an approval, and one that paused at H01, was resumed
with an approve decision, and finished approved.

## Run it

There are three ways to run a case.

### 1. Local runner — no AWS, no model calls

```bash
python3 local_runner/run_local.py
python3 local_runner/run_local.py path/to/cases.json   # a different cases file
```

With no argument it uses `data/demo-test-cases.json`. The runner follows
the same flow as the ASL file, written in Python. Each node gets at most
2 attempts; H01 is answered from the case's `simulated_adjuster_decision`.
It writes `results/summary.json`, `results/decision_records.json` and
`results/audit_records.json`, and prints one pass / fail line per case.

The local nodes are the mock versions: simple, fixed rules that read the
claim documents in a limited way. On the 12 demo cases in this repo the
local score is 9/12. The 3 misses are all the same convention difference:
the demo cases record the computed payable amount on paths that end in a
denial, a fraud referral or an adjuster rejection, while the local runner
writes no payable amount on those paths. Final status, reason codes and
path match on all 12 cases. So read 9/12 as the mock's score, not the
system's.

### 2. One case on AWS, started by hand

Start an execution of the state machine and give it input in this shape:

```json
{
  "case_id": "TC-104",
  "execution_id": "my-run-TC-104-1",
  "case": { "...": "the case fields" }
}
```

Two things to note:

- `execution_id` is a name you choose, and it must be unique.
- The `case` object is the test case with the `expected` and `exercises`
  fields removed. Those two fields are scoring information and are never
  passed to the system.

### 3. Full evaluation on AWS

This needs the deployed stack and your AWS credentials.

```bash
python3 evaluation/run_evaluation.py                 # all cases in the data file
python3 evaluation/run_evaluation.py TC-104 TC-110   # selected cases only
python3 evaluation/run_evaluation.py --trial         # names executions "trial-…" instead of "eval-…"
```

For each case, the script:

- runs the case 3 times through the state machine, in model mode,
- resumes H01 after 20 seconds using the case's
  `simulated_adjuster_decision` (see the H01 section below),
- reads the path each execution actually took from the Step Functions
  execution history,
- also runs a baseline: one single Bedrock call per case, given the whole
  policy and the whole case at once,
- scores final status, reason codes, payable amount, and (for the graph)
  path, and writes the results to `evaluation/evaluation_report.json`.

## H01 — the human decision point

A case whose payable amount is above $5,000 stops at H01 and waits. No Lambda
runs while it waits, and the wait costs nothing extra: Standard state
machines charge per step taken, not per hour waited.

When the case parks, the state machine writes a row into the audit table.
That row holds the **task token** — the one piece of information needed to
restart this exact paused execution. To resume it, an outside actor calls
`SendTaskSuccess` with that token and a decision of `APPROVE` or `REJECT`:

- `APPROVE` → the case continues to the approval notice and ends APPROVED.
- `REJECT` → the case ends ADJUSTER_REJECTED.
- Anything else is treated as a contract error and ends at T10.

In real use that actor is a human adjuster. In this repo it is the simulator
Lambda (`lambda/h01_simulator.py`): the evaluation script finds the token in
the audit table, calls the simulator with the token and the case's
`simulated_adjuster_decision`, and the simulator sends the decision. The
token can be used only once — a second `SendTaskSuccess` for the same pause
fails, which is enforced by Step Functions itself.

## Results

30 evaluation cases (provided with the original exercise; not included
in this repo), 3 runs each, temperature 0, on the deployed stack:

| System | Correct on run 1 (Pass1) | Correct in any of 3 runs (Pass3) | Field accuracy | Cost per case | Latency |
|---|---|---|---|---|---|
| Graph (this project) | 26/30 | 26/30 | 0.87 on status, reason codes, payable and path | ≈ $0.0071 (2,919 input / 828 output tokens) | ≈ 20.1 s, including the simulated H01 wait |
| Single-call baseline | 15/30 | 15/30 | 0.70 status, 0.73 reason codes, 0.77 payable — no path to score | ≈ $0.0043 | ≈ 6.8 s |

Every case scored the same in all 3 of its runs, for both systems — so the
mistakes are systematic, not luck. The two systems also miss different cases:
no case defeats both. The full analysis, including which node each graph
mistake started at, is in the design document (§9). Aggregate results are in
`evaluation/evaluation_report.json`; per-case rows are omitted.

## Key design decisions

- **One Lambda per node, one IAM role per Lambda.** Only the model nodes
  (N01, N03, N04, N05, N06, N08, N09) are allowed to call Bedrock. The code
  nodes have no Bedrock permission at all, so they cannot call the model even
  by accident.
- **The split between code and model follows the information, not the topic.**
  Dates, money and counting are plain code, because they have exact answers
  (N02 checks coverage dates; N07 calculates the payable amount). Reading
  documents and weighing evidence are model work. Two nodes are mixed: N03
  lets the model answer one yes / no question and recomputes all dates in
  code; N08 checks its fraud rules in code first, and the model may only add
  one further indicator, with evidence.
- **The state machine owns all routing.** A node returns a result for its own
  step only. Step Functions decides what happens next, from fixed rules.
- **A result is checked before it is used.** If a node's output does not
  match its schema, that counts as a failure, not as an answer: the node is
  retried, up to 2 attempts in total, and if it still fails the case ends at
  T10 (NEEDS_REVIEW).
- **H01 is a callback state, not a loop.** The execution itself waits at H01.
  There is no polling, and nothing else to keep in sync.
- **Audit records have one known limitation in this build.** The audit table
  keeps one row per node per execution — the final attempt's row — because
  the attempt number is not passed into the Lambda, so a retry writes over
  the same row. The attempts that were overwritten are still fully visible
  in the Step Functions execution history, and the evaluation rebuilds each
  case's path from that history. Failed attempts are also recorded with zero
  tokens, because the failure happens before the token counts can be
  returned. This is written up in full in the design document (§8).
- **Case data travels inside the execution state.** The official cases are
  about 0.7–1.3 KB, far under the 256 KB state limit. An S3 intake bucket is
  created by the stack but is not used in this build; it is there so large
  documents could later be passed by reference — a pointer in the state
  instead of the document itself — without changing the flow. See the design
  document (§5).

## Teardown

```bash
npm run destroy
```

The DynamoDB tables and the S3 bucket are set to be removed with the stack,
so this takes everything down.

> **If you created a dedicated IAM access key for CLI access, delete it after 
> teardown as well.** Such a key is created by hand, outside the stack, so 
> `cdk destroy` will not remove it, and it stays active until it is deleted 
> in the IAM console.