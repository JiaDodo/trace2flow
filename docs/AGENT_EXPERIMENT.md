# DeepSeek corpus experiment (M11b)

## Protocol and limits

Use the predeclared `examples/customer-support-agent/corpus-plan.json`:
compile 10, development 8, test 12, disjoint by full task group and entity
identity. M10 pilots are not added to the denominator. Each case has one live
attempt; tool-level retries inside a run remain distinct recorded occurrences.
Failures, blocked reads, provider stops and zero-call records are not deleted.
Only `DEEPSEEK_API_KEY` availability is checked, never its value or `.bashrc`.
LangSmith cloud tracing remains disabled.

The model orchestrates five registered local tools using the existing LangChain
loop. Customer records, order facts and ticket states are synthetic. Business
classification and recommendations are deterministic tools. The gold outcome
table is independently declared, not computed by the tested tools. Nothing
connects real customer systems, sends a message or issues a real refund.

The reviewed workflow is an explicit AI-reviewed **execution contract**. Its
parameter sources are not proof of the model's hidden mental lineage. In
particular, equal false/true values do not identify a field. The reviewer names
the semantic field and exact source occurrence ID; the intake validates every
typed observation. Customer/order IDs and policy version are task inputs;
there are no promoted historical constants. Independent customer and order
reads have no fabricated data edge. Repeated calls cannot be collapsed to fit
the narrow five-occurrence contract.

Review is explicitly labeled AI, never human. Machine declaration/validation
wall time is measured separately; human review minutes are zero and AI reasoning
effort is unmeasured (`null`). The machine timings do not estimate the effort of
reading traces, preparing declarations or resolving business ambiguity.

Workflow admission checks customer/order existence and ownership before
execution; this guard is declared, not mined branching. Coverage includes all
planned test tasks. Safe refusals are distinguished from successful updates.
Agent scoring checks output/state safety only, not final customer-facing chat
quality or every instruction-following aspect. A rejected invalid read can
still have a correct safe business outcome, and failed-call counts remain
visible. This small single-trial controlled experiment is not evidence of
production reliability, statistical generalization, money saved or a universal
natural-language intent compiler.

## Reproduction entrypoints

Raw recordings remain ignored under `data-private/agent-corpus-v1/{compile,development,test}/CASE/raw.json`.
The review plan names every compile task, original raw hash and exact included
occurrence IDs; the foreign-order task is explicitly excluded from compilation
but stays in evaluation. No tool-name matcher chooses source occurrences.

```bash
.venv/bin/python -m trace2flow.agent_contract_review \
  examples/customer-support-agent/corpus-plan.json \
  data-private/agent-corpus-v1/compile \
  examples/customer-support-agent/live-v1/review-plan.json \
  --output-dir data-private/agent-corpus-v1-reviewed
```

Pass **all nine included** `reviewed.json` paths to `agent_build`, using
`--dataset-id agent-corpus-v1-compile --output-dir NEW_DIRECTORY`. The source,
candidate, resolution and IR can be rebuilt without model calls. Compile data
is reviewed local tool evidence; model message text and credentials are absent.

Once development evaluation and offline tests pass, freeze before any test
model run or test-result inspection:

```bash
.venv/bin/python -m trace2flow.agent_final_freeze \
  examples/customer-support-agent/corpus-plan.json \
  --workflow data-private/agent-corpus-v1-build/workflow.json \
  --compile data-private/agent-corpus-v1-build/compile.json \
  --review-plan examples/customer-support-agent/live-v1/review-plan.json \
  --confirm-unseen-test \
  --output-dir data-private/agent-corpus-v1-final-freeze
```

This pins the plan, selected pipeline sources, reviewed population, workflow,
compile source, report implementation and review implementation/plan. The flag
is an operator confirmation, not cryptographic proof of an untouched test set.
The public task definitions are a procedural holdout, not access control.

Select each test case with `agent_corpus --case-id test-NN --unlock-test`, the
final `report-freeze.json` manifest, `--allow-paid-call` and a new recording
directory. Preserve all twelve planned attempts, then report:

```bash
.venv/bin/python -m trace2flow.agent_report \
  examples/customer-support-agent/corpus-plan.json \
  data-private/agent-corpus-v1/test --partition test --unlock-test \
  --manifest data-private/agent-corpus-v1-final-freeze/report-freeze.json \
  --workflow data-private/agent-corpus-v1-build/workflow.json \
  --compile data-private/agent-corpus-v1-build/compile.json \
  --output NEW_REPORT.json
```

Report output creation is exclusive. The CLI rejects changed source/workflow
hashes, wrong partitions, undeclared duplicate attempts and missing pre-test
report pins. Missing recordings stay `not_run`, with `score_final=false`.
An additional counter/timer pass repeats **only fresh local workflow execution**,
not a paid model call or response replay, and rechecks output plus full state.
Agent elapsed time includes framework/model/collection overhead; workflow time
measures local execution only. These are descriptive timings, not a valid
production speedup multiplier. Token totals include only provider-reported
usage and mark incomplete accounting. Costs are not estimated.

## Completed experiment

The pre-test checkpoint is commit `81acf50`. The workflow/report were frozen
before test collection; pipeline, declarations and scorer remained unchanged
after observing results. All 30 planned live tasks were recorded once. Test
outcomes: Agent 8 correct updates plus 4 safe unchanged outcomes; workflow
accepts 8/12, executes all accepted cases correctly and refuses 4 safely. There
are no unsafe write attempts/acceptances. This is not a customer-chat quality
score or production success-rate claim.

Accepted test tasks use 40 Agent model calls versus 0 workflow model calls;
both dispatch 40 tool calls. All 30 runs report 155,992 input and 13,597 output
tokens, with 125 requests and 120 dispatched calls, including 10 failed calls.
No paid recording was discarded. The test includes a zero-call raw-only run.
The generated target also passed a real local Prefect run with exact output
and full-state assertions. See the
[archive/source record](../examples/customer-support-agent/live-v1/SOURCE.md)
and three JSON reports for results and limitations. These fixtures are now
known archived regressions; future iterations require a newly declared holdout.
