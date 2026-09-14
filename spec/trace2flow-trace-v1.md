# Trace2Flow Normalized Trace Format 1.0

This is the sole normalized JSON input format for Trace2Flow. It represents
complete task runs and distinct tool-call occurrences without assuming that
array order proves data dependency.

## Envelope

```json
{
  "schema_version": "1.0",
  "dataset_id": "customer_support_train",
  "partition": "compile",
  "runs": [],
  "metadata": {}
}
```

- `schema_version` must be exactly `1.0`.
- `dataset_id` is a non-empty identifier.
- `partition` is `compile`, `test`, or `unspecified`.
- `runs` is a non-empty array of complete task runs. Run IDs and provenance
  fingerprints must be unique inside a dataset.
- Unknown fields are rejected rather than silently discarded.

## Complete task run

```json
{
  "id": "run_001",
  "provenance": {
    "kind": "synthetic",
    "source": "generator/customer_support_v1",
    "source_run_id": "case_001"
  },
  "inputs": {"priority": 1, "expedited": false, "coupon": null},
  "steps": [],
  "status": "completed",
  "final_output": {"recommendation": "request_carrier_update"},
  "state_before": {},
  "state_after": {},
  "metadata": {}
}
```

- `provenance.kind` must be `synthetic` or `recorded`; this prevents synthetic
  data from being presented as real traces.
- `source` and `source_run_id` identify the original complete run. Their stable
  fingerprint prevents a renamed run from appearing in both compile and test
  partitions.
- `inputs`, `final_output`, state snapshots, and metadata accept JSON values.
  Strings, integers, floats, booleans, `null`, arrays, and objects retain their
  original types.
- Run status is `completed`, `failed`, `partial`, or `cancelled`.

## Tool-call occurrence

```json
{
  "id": "lookup_order_2",
  "tool": "lookup_order",
  "params": {"order_id": 1002},
  "output": {"delivered": true},
  "depends_on": ["lookup_customer_1"],
  "spawned_by": null,
  "status": "completed",
  "side_effects": [{"kind": "read", "target": "mock.orders"}],
  "metadata": {}
}
```

- `id` identifies this call occurrence inside its run. Different calls to the
  same `tool` must have different IDs.
- `depends_on` and `spawned_by` are explicit references to occurrence IDs in
  the same run. Missing, duplicate, self, and cyclic references are rejected.
- Array position records observation order only. It does not add a dependency.
- Step status is `completed`, `failed`, or `skipped`.
- Side-effect kind is `none`, `read`, or `write`. Reads and writes require an
  explicit target. A write may record whether it was reversible.
- `metadata.alignment_key`, when present, is a non-empty human-declared key for
  matching the same logical occurrence across runs. It is scoped by tool name.
  Reusing one key more than once in a run remains unresolved.

## Candidate occurrence alignment and dependencies

M2 produces a separate `candidate-dag/1.0` artifact. Automatic occurrence
signatures use the tool name, parameter **names**, and side-effect
kind/target/reversibility. They intentionally ignore parameter values, array
position, and dependency direction. A declared `metadata.alignment_key`
replaces the inferred structural part of the signature.

If one inferred or declared signature occurs more than once in the same run,
Trace2Flow preserves every run-qualified occurrence under one unresolved node;
it does not guess a pairing. Equal values such as `false`, `null`, or `1` do
not resolve that ambiguity.

Candidate edges come only from explicit `depends_on` declarations. Each edge
contains its supporting run/source-call/target-call records. Dependencies with
unresolved endpoints, reciprocal evidence, or a cycle across runs are moved to
`unresolved_dependencies` rather than silently forced into the accepted DAG.
`spawned_by` records orchestration provenance and is not treated as proof of a
data dependency by this candidate graph.

## Upstream ASP adaptation

The upstream compiler consumes ASP facts and treats parameters as strings.
Trace2Flow therefore:

1. validates and retains the typed Pydantic source as authoritative;
2. emits one `call/4` fact per occurrence, including repeated tools;
3. encodes each parameter as canonical JSON plus Base64URL using
   `canonical-json-base64url-v1`, preventing collisions such as `1`, `1.0`,
   `true`, and `"1"`; and
4. passes only the upstream-supported fields (`job`, status, call, dependency,
   spawn, and parameter facts) to the miner.

The current upstream synthesis may still aggregate those facts by tool name.
The adapter does not treat its lossy compiled JSON as a replacement for the
typed source. M2 retains normalized upstream tool-level signals as contextual
evidence but derives occurrence-aware edges from the authoritative typed trace.

## Local commands

From the repository root:

```bash
PYTHONPATH=src python -m trace2flow validate traces.json \
  --output normalized.json

PYTHONPATH=src python -m trace2flow split normalized.json \
  --test-run-id run_003 \
  --compile-output compile.json \
  --test-output test.json

PYTHONPATH=src python -m trace2flow to-asp compile.json \
  --output compile.lp

PYTHONPATH=src python -m trace2flow mine compile.json \
  --output candidate.json \
  --rule-profile strict
```

These commands validate and transform local data only. `mine` invokes the
audited local Clingo compiler with an allowlisted rules profile; none of them
execute trace-carried code, call recorded tools, or access external services.
