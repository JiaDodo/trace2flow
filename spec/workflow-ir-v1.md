# Trace2Flow Workflow IR 1.0

`workflow-ir/1.0` is the framework-independent contract between trace mining
and execution targets. It does not contain Python code, shell commands, or
runtime-specific objects.

## Parameter bindings

Every node parameter has exactly one discriminated binding:

- `constant`: a typed JSON value explicitly declared as a business constant;
- `task_input`: a declared path into the invocation input;
- `tool_output`: a declared path into an accepted predecessor's result; or
- `unresolved`: observed values and zero or more evidence-backed candidates.

Observed invariance never becomes a constant automatically. Equality with a
task input or predecessor output never becomes lineage automatically. Such
matches are recorded as candidates with per-run evidence and require a
`ResolutionPlan` declaration. A declared binding is checked against every
aligned observation and is rejected if it contradicts the compile traces.

JSON paths are arrays of object keys and list indexes. For example,
`["customer", "id"]` selects `value["customer"]["id"]`; an empty output path
selects the predecessor's complete result.

## Structure and safety state

Workflow edges are copied only from accepted candidate-DAG dependencies and
retain occurrence-level `depends_on` evidence. The model rejects missing node
references, duplicate edges, and cycles. A tool-output binding must have a
matching incoming workflow edge.

Each node also records:

- occurrence alignment status;
- branch-resolution status;
- observed side-effect declarations; and
- side-effect-resolution status.

Writes and upstream conditional/mutually-exclusive behavior require explicit
confirmation. In version 1.0, confirming a branch node declares that it should
execute unconditionally; general conditional expressions are not represented.
`WorkflowIR.execution_blockers()` lists unresolved dependencies, alignments,
parameter bindings, branches, and side effects. Exporters and executors must
reject a workflow while this list is non-empty.

## Local construction

```bash
PYTHONPATH=src python -m trace2flow build-ir compile.json \
  --candidate candidate.json \
  --resolution resolution.json \
  --output workflow.json
```

Omit `--resolution` to inspect conservative candidates without confirming
them. The command only constructs data models and executes no workflow tools.
