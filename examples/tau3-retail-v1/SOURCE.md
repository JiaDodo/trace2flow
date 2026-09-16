# τ³ retail public dataset inventory

This directory records an audited inventory of the public simulated retail
tasks from `sierra-research/tau2-bench` (the project now calls the benchmark
τ³). It does **not** contain real customer data and the task action oracle is
not an Agent execution trace.

## Pinned source

- Repository: <https://github.com/sierra-research/tau2-bench>
- Commit: `2174a603f6d014ef94473ffa95957f6ce27100db`
- License: MIT; the source license hash and retail data hashes are embedded in
  `manifest.json`.
- Domain: retail, 114 base tasks: 74 official train and 40 official test.

Generate the inventory from an exact checkout into a new path:

```bash
PYTHONPATH=src python -m trace2flow.tau3_corpus /path/to/tau2-bench \
  --output /tmp/tau3-retail-manifest.json
cmp examples/tau3-retail-v1/manifest.json /tmp/tau3-retail-manifest.json
```

The checked-in manifest exposes train-side action metadata for experiment
planning. It publishes only IDs for the official 40-task test set: no test
instructions, reference actions, natural-language assertions, or expected
state. The test set must remain sealed until a new evaluation contract is
frozen.

Train tasks are grouped transitively by identifiers found in reference action
arguments. Complete groups are assigned deterministically to 48 compile and 26
development tasks, so variants sharing a customer/order/product-side entity do
not cross those roles. This grouping uses the train oracle only to prevent
leakage; it is not evidence that an Agent actually followed the reference
actions. The official train/test split itself reuses simulated entities, so
entity isolation is explicitly not claimed across that upstream boundary.

Task 105 was used for the provider pilot before the split was frozen. The
builder therefore forces its entire 19-task entity-connected group into
development. A pre-exposed task can never return to compile merely because a
different deterministic hash assignment would otherwise place it there.

## DeepSeek development pilot

`pilot-report.json` is a redacted summary of three local attempts on official
train task 105. Raw results remain under ignored `data-private/` and their
hashes are pinned in the report.

- Attempt 1 was an authentication/configuration failure because the benchmark
  did not map `DEEPSEEK_API_KEY` to its OpenAI-compatible provider path.
- Attempt 2 ran the conversation but failed during the benchmark's hard-coded
  natural-language evaluator model call.
- Attempt 3 explicitly mapped the DeepSeek OpenAI-compatible endpoint and the
  evaluator model in-process. It was a valid evaluated run, but reward was
  `0.0`: DB state remained correct (`1.0`) while the expected exchange was not
  completed and the NL assertion scored `0.0`.
- The Agent issued five `get_order_details` calls in one assistant message,
  contrary to the domain's one-tool-call-at-a-time policy. The public report
  preserves this as failure evidence.
- LiteLLM had no price mapping for this model identifier. Reported token usage
  is retained, but a zero-cost claim is forbidden.

This single failed development task is useful integration evidence, not an
accuracy estimate. It is not rerun, discarded, or moved into the sealed test
set. Scaling to a paid batch is deferred until the one-call policy and provider
evaluator configuration have deterministic regression coverage.

`development-plan.json` freezes the next six-attempt development batch before
result collection. It spans exchange, transfer, address, pending-item,
cancellation and mixed return/update families. It uses one attempt per task,
zero task retries, zero hallucination retries and two-way concurrency.

That batch is now complete and its redacted result is
`development-report.json`. All six results were retained: four terminated with
the official communication-protocol `agent_error` because a response mixed
text with one tool call, and two were stopped by Trace2Flow's multiple-tool
guard. No task succeeded and no task reached the NL evaluator. Consequently,
the official test set remains sealed and these tasks are never rerun.
