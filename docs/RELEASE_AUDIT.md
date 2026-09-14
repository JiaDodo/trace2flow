# Trace2Flow MVP Release Audit

Audit date: 2026-09-14

Audited upstream baseline:
`b168d6760213b489e2fb2f5571f5d4e6d648dee8`

## Capability result

The local MVP path is complete for one normalized JSON format, one Prefect
target, and one explicitly synthetic customer-support scenario. It invokes the
upstream ASP miner, builds an occurrence-aware evidence DAG, applies reviewed
typed binding declarations, exports registered-tool-only Prefect source, and
validates held-out outputs and ticket-state changes in fresh in-memory state.

The Streamlit UI supports default or uploaded compile/test traces, editable
ResolutionPlan JSON, DAG visualization, per-edge evidence, unresolved blocker
inspection, Prefect source download, and independent verification reports. If
an uploaded trace invalidates the default resolution IDs, the UI preserves the
candidate graph and falls back to an unresolved IR instead of exporting.

## License and attribution

- `LICENSE` remains byte-identical to the upstream baseline. Both SHA-256
  values were
  `c1eece0b74a0994aa1ff1bd0618c8b0bf9d445b57bb855d2040d6aa0187ee320`.
- Git history and the original MIT copyright notice remain intact.
- `src/compile.py`, `src/benchmark.py`, `src/codegen.py`, and `rules/` have no
  diff from the audited upstream commit.
- README and UI explicitly distinguish upstream AutoCompile from Trace2Flow
  additions.

## Safety audit

- Trace content is parsed as strict JSON and is never evaluated as code.
- Static tests reject `eval`, `exec`, dynamic import, shell dispatch, and
  unregistered tools in generated paths.
- The only subprocess use in `src/trace2flow/` is the allowlisted upstream
  adapter invoking the repository's fixed compiler and one of two fixed rule
  files with a 60-second timeout.
- The simulator imports no HTTP/socket client, has no message-sending tool, and
  has no refund operation. `manual_refund_review` is output text only.
- Prefect export and local execution both preflight unresolved IR and registered
  tool names before dispatch. Writes require explicit confirmation.
- Compile/test overlap is rejected by run ID and provenance fingerprint.
- Replay is labeled partial and cannot claim execution equivalence.

## Reproduced clean demo result

The command sequence in `docs/LOCAL_VERIFICATION.md` was run into a new `/tmp`
directory:

```text
candidate: 5 nodes, 5 accepted edges, 0 unresolved dependencies
workflow: 5 nodes, 5 edges, 0 blockers
Prefect export: 5 required registered tools, valid Python source
independent holdout: 2/2 output matches and 2/2 state matches
```

The generated five-node Prefect flow was then run locally on one holdout case:

```text
nodes executed: 5
final output match: true
state match: true
```

Streamlit's `AppTest` also loaded the real entrypoint, activated the default
pipeline, and observed five nodes, five edges, zero blockers, and a passing
verification result.

Final automated verification ran 49 tests successfully. Ruff passed over the
Trace2Flow source, tests, and Streamlit entrypoint; `compileall` completed; and
the 179-package lock resolved offline. An editable package build succeeded and
the installed `trace2flow --help` exposed all seven CLI operations.

## Honest limitations

- The executable default customer-support traces and results are synthetic.
  The separate tau retail corpus contains recorded benchmark-simulator runs,
  but its committed report validates held-out structure only and does not claim
  output/state execution equivalence.
- Automatic occurrence alignment is conservative structural matching, not a
  general semantic matcher. Ambiguity requires user declarations.
- Candidate binding matches remain unresolved until declared; Trace2Flow does
  not infer causal lineage from value equality.
- Branch confirmation currently means the reviewer has declared unconditional
  execution for that node. General conditional-expression compilation is not
  implemented.
- The simulator is an independent local fixture, not a real service-integration
  test. The UI is a local demonstration, not a production deployment.
- No success rate, cost saving, or LLM-call reduction is claimed.
