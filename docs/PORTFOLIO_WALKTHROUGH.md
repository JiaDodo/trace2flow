# Trace2Flow portfolio walkthrough

This is a five-minute, locally reproducible demonstration. It makes three
different claims and keeps their evidence separate.

## 1. Start with the problem

An Agent trace is not already a workflow. Call order is not data lineage, the
same tool may occur more than once, and a repeated parameter is not necessarily
a business constant. Trace2Flow turns repeated execution evidence into an IR
that remains blocked wherever structure, bindings, branches, or writes are not
explicitly resolved.

## 2. Show recorded structural evidence

Open `examples/tau-retail-recorded/structural-report.json`. The four held-out
tau benchmark-simulator runs contain the same four occurrence-aligned nodes and
three reviewed dependency edges mined from three compile runs. This proves
held-out structural coverage only; it does not compare execution results.

## 3. Show the honest compilation boundary

Open `examples/tau-retail-recorded/resolution.json`. All nine parameters are
runtime inputs, not inferred constants. Their evidence mode is
`declared_runtime_contract` because the recorded input is natural-language
text rather than those structured paths. The selected business output is the
order-modification node; no artificial edge is added from authentication just
to make the graph have one sink.

The caller must supply the chosen product and old/new item IDs. Choosing a
variant from an arbitrary user request remains Agent or human work because the
traces do not establish a general decision policy.

## 4. Run independent execution

```bash
work_dir="$(mktemp -d /tmp/trace2flow-portfolio.XXXXXX)"

PYTHONPATH=src python -m trace2flow build-ir \
  examples/tau-retail-recorded/compile.json \
  --candidate examples/tau-retail-recorded/candidate.json \
  --resolution examples/tau-retail-recorded/resolution.json \
  --output "$work_dir/workflow.json"

PYTHONPATH=src python -m trace2flow export-prefect \
  "$work_dir/workflow.json" \
  --registered-tool find_user_id_by_name_zip \
  --registered-tool get_order_details \
  --registered-tool get_product_details \
  --registered-tool modify_pending_order_items \
  --output "$work_dir/flow.py"

PYTHONPATH=src python -m trace2flow verify-retail \
  "$work_dir/workflow.json" \
  --cases examples/tau-retail-recorded/execution-cases.json \
  --output "$work_dir/verification.json"
```

The expected local result is two of two cases matching both the declared
business output and the complete order collection after mutation. These are
new synthetic cases, not a benchmark success rate. Automated negative tests
corrupt output and state expectations independently and require both failures
to be detected.

## 5. Show the interface

```bash
PYTHONPATH=src streamlit run streamlit_app.py
```

The top evidence ladder distinguishes:

1. synthetic customer-support end-to-end verification;
2. recorded tau held-out structure coverage; and
3. fresh synthetic execution of the recorded-derived structure.

Finish with the safety property: generated flows can dispatch only through a
fixed `ToolRegistry`; trace text is never executable code, and the retail
simulator has no network, message, payment, or refund integration.
