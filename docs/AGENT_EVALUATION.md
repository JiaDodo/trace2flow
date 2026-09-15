# Agent corpus and independent evaluation (M11a)

The M11a engineering baseline and M11b controlled live experiment are complete.
See [the experiment record](AGENT_EXPERIMENT.md) for the actual thirty-task
DeepSeek results and limitations. M10 pilots remain development evidence and
are not retroactively inserted into this corpus.

## Task plan and evidence boundaries

`examples/customer-support-agent/corpus-plan.json` predeclares 30 synthetic
business tasks: 10 compile, 8 development, 12 test. Tasks cover delivery delay,
damage, duplicate billing, general review, foreign orders, missing identifiers,
unknown customers and one complaint containing a write-inducing instruction.
Customer/order/ticket identities and complete task groups cannot cross roles.
Paraphrases share a group; additional repetitions require a new predeclared
inventory rather than selecting a convenient successful attempt.

`agent_corpus.materialize` creates a fresh environment per task. The model gets
only `AgentTask` fields, not the scenario label, state snapshot or gold answer.
Expected outputs and full customer/order/ticket states come from an explicit
business expectation table, not by calling the tested classification or
recommendation implementation. This avoids implementation-self-agreement but
does not prove that the synthetic policy represents real customer service.
Classification and recommendations still use deterministic simulator tools;
the Agent orchestrates their calls. This is not an open-ended reasoning test.

A freeze saves task/plan/prompt and selected producer, review, evaluator,
candidate, IR, runtime and simulator source hashes. A final freeze also pins
the exact workflow and its compile dataset. It rejects blocked or mismatched
workflow/source pairs. The manifest does not independently verify whether
someone has already inspected test results; maintain that discipline yourself.
The public test plan is a **logical seal**, not access control, cryptographic
attestation or an independent benchmark custodian. SHA hashes bind content,
not proof that a recording really came from a model or that a human reviewed it.

## Freeze, then collect compile/development tasks

Run from the repository with the locked optional `agent` environment. All
directories below must be new; recordings and manifests stay in ignored
`data-private/`. No command pushes to GitHub. Only the collection command makes
a paid model request; it requires configured `DEEPSEEK_API_KEY` and the flag.

```bash
.venv/bin/python -m trace2flow.agent_corpus examples/customer-support-agent/corpus-plan.json

.venv/bin/python -m trace2flow.agent_corpus \
  examples/customer-support-agent/corpus-plan.json \
  --freeze data-private/agent-corpus-v1-freeze

.venv/bin/python -m trace2flow.agent_corpus \
  examples/customer-support-agent/corpus-plan.json \
  --case-id compile-01 \
  --manifest data-private/agent-corpus-v1-freeze/manifest.json \
  --allow-paid-call \
  --collect-output data-private/agent-corpus-v1/compile/compile-01
```

Collect every predeclared compile and development task, preserving failures,
provider/budget stops and zero-call raw records. Do not retry a case and hide
the original attempt. Changed implementation/prompt/plan requires a new version
and freeze; the live CLI rejects mismatches. Model aliases remain unpinned.

## Explicit review, not automatic lineage inference

Create an intentionally unapproved draft:

```bash
.venv/bin/python -m trace2flow.agent_review \
  examples/customer-support-agent/corpus-plan.json \
  data-private/agent-corpus-v1/compile/compile-01/raw.json \
  --draft --output data-private/agent-corpus-v1/compile/compile-01/review.json
```

The draft has blank reviewer, `redaction_confirmed=false`, no data edges and
every binding `unresolved`. It cannot be approved merely by being generated.
Inspect original events, each distinct occurrence, typed arguments/results and
states. Record the real reviewer identity, rationale and actual review minutes;
never label an automated fixture or AI declaration as human review.

For each call, declare `depends_on`, registered `side_effects`, optional
`alignment_key` (needed for indistinguishable repetitions) and every parameter:

- Task input: `{"kind":"task_input","path":["customer_id"],"rationale":"..."}`.
- Tool output: `{"kind":"tool_output","source_call_id":"actual-call-id","path":["status"],"rationale":"..."}`; explicitly name that call in `depends_on`.
- Constant: `{"kind":"constant","value":"v1","rationale":"explicitly declared business policy"}`. Historical invariance alone is insufficient.
- Ambiguous: `{"kind":"unresolved","rationale":"multiple plausible sources"}`.

Use `decision=include` only for complete known-tool recordings eligible for
this executable workflow family. Partial, failed and unsupported cases use
`exclude_from_compilation`; this does **not** remove them from evaluation.
The intake checks all occurrences/parameters, SHA identity, typed observed
values, preceding dependencies and the actual registered effect contract.
Same-valued booleans/numbers are not promoted without a declaration.

After review, run:

```bash
.venv/bin/python -m trace2flow.agent_review \
  examples/customer-support-agent/corpus-plan.json \
  data-private/agent-corpus-v1/compile/compile-01/raw.json \
  data-private/agent-corpus-v1/compile/compile-01/review.json \
  --output data-private/agent-corpus-v1/compile/compile-01/reviewed.json
```

Excluded recordings produce a decision message and no included dataset. Review
preserves ambiguity even when a recording is included. Multiple reviewed runs
may only combine within one corpus role and plan.

## Compile and develop without reading test results

Pass only included compile recordings to the build entrypoint:

```bash
.venv/bin/python -m trace2flow.agent_build \
  data-private/agent-corpus-v1/compile/compile-01/reviewed.json \
  data-private/agent-corpus-v1/compile/compile-02/reviewed.json \
  data-private/agent-corpus-v1/compile/compile-03/reviewed.json \
  --dataset-id agent-corpus-v1-compile \
  --output-dir data-private/agent-corpus-v1-build

.venv/bin/python -m trace2flow.agent_evaluation \
  examples/customer-support-agent/corpus-plan.json \
  data-private/agent-corpus-v1/development --partition development \
  --workflow data-private/agent-corpus-v1-build/workflow.json \
  --compile data-private/agent-corpus-v1-build/compile.json
```

The three paths illustrate syntax, not permission to cherry-pick three runs:
include every reviewed eligible compile run in the actual evaluation build.
The build saves compile data, real upstream-backed candidate, declaration
resolution and Workflow IR. Only agreeing reviewer declarations translate into
resolved bindings. Conflicts remain unresolved; unknown branches are not
confirmed automatically. Exit 2 means artifacts are inspection-only and
execution remains blocked. The single aligned `update_ticket` is the declared
customer-support business output; its role is a tool contract, not discovered
from call ordering.

The workflow evaluator initializes independent state rather than replaying
recorded responses. It explicitly checks customer/order existence and ownership
before execution. This is a declared admission guard, **not a mined branch**.
It also checks IR blockers and the registered tool allowlist. Report coverage
alongside accepted-case correctness; refusing everything is not a good workflow.

Agent evaluation counts every planned task, marking missing records `not_run`
and `score_final=false`. Failed and zero-call runs remain counted. It checks
final update output and the complete mutable/immutable fixture state, and flags
even blocked unsafe write attempts. For refusal cases this is safety/outcome
scoring only: correctness of the final customer-facing chat is not measured.
Workflow admission is reported separately; no generalization, cost-saving or
LLM-call-reduction claim follows from fewer tool calls.

## Final workflow freeze and one-shot test evaluation

Once compile/development review is complete, freeze the final artifacts before
collecting test model runs:

```bash
.venv/bin/python -m trace2flow.agent_corpus \
  examples/customer-support-agent/corpus-plan.json \
  --freeze data-private/agent-corpus-v1-final-freeze \
  --workflow data-private/agent-corpus-v1-build/workflow.json \
  --compile data-private/agent-corpus-v1-build/compile.json
```

Test selection/collection requires `--unlock-test`; use the final manifest for
each test case and preserve all 12 planned records. Then use
`agent_evaluation --partition test --unlock-test --manifest ...` with the test
recording directory and frozen workflow/compile paths. The CLI checks source
hashes and final artifact hashes. Do not tune on these results; any later
iteration needs a newly declared holdout. Review effort is recorded in review
artifacts and summed in combined compile metadata, not estimated by the scorer.

## Offline validation

```bash
.venv/bin/python -m unittest discover -s tests -p test_agent_corpus.py -v
```

Twenty tests run without paid calls. They include actual Clingo mining of
explicitly scripted compile fixtures, unresolved export gates, declared-binding
translation, and independent execution on eight development fixture tasks:
four accepted and correct, four safely refused, zero unsafe acceptances.
Coverage is 4/8. These numbers are regression assertions, **not DeepSeek
performance or held-out model results**. No test model result was collected or
inspected while implementing the original M11a baseline. The later M11b
experiment froze its scoring code before collecting all twelve test tasks.
