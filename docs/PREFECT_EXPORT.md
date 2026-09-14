# Safe Prefect Export

Trace2Flow exports `workflow-ir/1.0` to one target: Prefect 3. Generated code
contains a fixed `@flow`, a fixed `@task`, typed binding lookups, and literal
tool names. It contains no `eval`, `exec`, dynamic import, shell dispatch, or
trace-provided source code.

Export has two gates:

1. `WorkflowIR.execution_blockers()` must be empty. Unresolved dependency,
   alignment, parameter, branch, or side-effect state stops export.
2. Every workflow tool must be named in `--registered-tool`. The generated
   flow checks the supplied `ToolRegistry` again before its first tool call.

```bash
PYTHONPATH=src python -m trace2flow export-prefect workflow.json \
  --registered-tool lookup_customer \
  --registered-tool lookup_order \
  --registered-tool classify_issue \
  --registered-tool recommend_action \
  --registered-tool update_ticket \
  --output generated_flow.py
```

The generated `run_workflow(task_input, registry)` returns the workflow ID,
all node outputs keyed by stable node ID, and the sink output. Tool functions
must be installed explicitly in `ToolRegistry`; names in traces cannot import
or discover callables.
