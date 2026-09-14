# Independent Local Verification

The customer-support demo uses only explicitly synthetic JSON traces and
in-memory fixture data. It performs no network calls, sends no messages, and
cannot issue refunds. `manual_refund_review` is a recommendation string, not an
operation.

The compile and holdout datasets are separate complete-run partitions:

- `examples/customer-support/compile.json`: three synthetic compile runs;
- `examples/customer-support/holdout.json`: two synthetic held-out runs; and
- `examples/customer-support/resolution.json`: reviewed binding and write
  declarations derived against compile observations only.

For each held-out case, verification creates a fresh simulator from that
case's `state_before`, invokes the resolved Workflow IR through `ToolRegistry`,
then compares both the sink output and complete mutable ticket state with the
case expectations. The report includes deterministic expected and actual state
diffs.

```bash
work_dir="$(mktemp -d /tmp/trace2flow-demo.XXXXXX)"

PYTHONPATH=src python -m trace2flow mine \
  examples/customer-support/compile.json \
  --output "$work_dir/candidate.json"

PYTHONPATH=src python -m trace2flow build-ir \
  examples/customer-support/compile.json \
  --candidate "$work_dir/candidate.json" \
  --resolution examples/customer-support/resolution.json \
  --output "$work_dir/workflow.json"

PYTHONPATH=src python -m trace2flow verify \
  "$work_dir/workflow.json" \
  --compile examples/customer-support/compile.json \
  --test examples/customer-support/holdout.json \
  --output "$work_dir/report.json"
```

`replay_structure()` is separately labeled
`recorded_response_replay_partial` and sets
`equivalent_execution_claimed=false`. A successful replay cannot replace the
independent simulation result.
