# Trace2Flow Status

Last updated: 2026-09-14

Current milestone: M7 complete — recorded benchmark intake ready

Working branch: `feat/m7-recorded-traces`

## M7 update

M7 establishes an honest, review-gated path from public recorded simulations
to Trace2Flow without adding tau3-bench as a runtime dependency:

- Added `trace2flow import-tau` for explicitly selected text-mode retail
  simulations. It records the embedded producing commit, benchmark execution
  context, MIT license, and `contains_real_customer_data=false`.
- Typed tool arguments and occurrence identity survive conversion. Recorded
  string tool responses stay strings; provider payloads, prompts, timestamps,
  costs, token usage, and audio are not copied.
- Structured identity fields receive deterministic type-preserving pseudonyms,
  which are also replaced in free text. Automatic processing remains labeled
  incomplete until a human confirms redaction.
- The importer never infers dependencies or side effects from call order. An
  exhaustive `tau-import-review/1.0` artifact is required, and candidate mining
  refuses quarantined imports.
- Added `task_group_id`, group-aware splitting, and cross-partition leakage
  rejection so different trials of the same tau task cannot leak.

The official tau3-bench repository was inspected at
`2174a603f6d014ef94473ffa95957f6ce27100db`. A public successful retail
simulation from a historical result produced at
`ade39493be54aad326a4c65295f77fe09780329b` was imported locally: one complete
run, three distinct calls, valid normalized JSON, review status `required`.
No credentials or model calls were used. The generated audit file stayed in a
temporary directory and was not added to the repository.

```text
$ PYTHONPATH=src python -m unittest discover -s tests -v
Ran 56 tests in 11.888s
OK

$ ruff check src/trace2flow tests streamlit_app.py
All checks passed!

$ PYTHONPATH=src python -m compileall -q src tests streamlit_app.py
completed with exit code 0

$ uv lock --check --offline
Resolved 179 packages in 2ms
```

The new tau files under `tests/fixtures/` are schema-shaped synthetic test
fixtures only; they are not claimed as collected benchmark evidence. The next
milestone is a small manually reviewed corpus from multiple disjoint source
tasks. It requires data selection and semantic review, but no production data.

The reviewed regression path produced 3 runs/9 calls, split entire task groups
2/1, and mined 3 aligned nodes plus 2 evidence-bearing edges with no unresolved
dependencies. This is adapter coverage on a synthetic fixture, not a benchmark
performance result.

## M6 update

M6 adds the lightweight inspection/demo layer and closes the MVP scope:

- Added a Streamlit entrypoint with default or uploaded compile/test JSON,
  editable ResolutionPlan JSON, DAG visualization, per-run/call edge evidence,
  upstream-signal inspection, binding/blocker inspection, Prefect source
  download, and independent verification output.
- Uploaded traces that invalidate the bundled resolution fall back to an
  inspectable unresolved IR; they cannot trigger Prefect export or simulation.
- Added pure demo orchestration helpers so the UI reuses the same tested
  compiler, IR, exporter, and verifier APIs.
- Added Streamlit 1.63, a console-script entry point, product metadata, a clear
  upstream-versus-Trace2Flow README boundary, and a final release audit.
- Hardened candidate and workflow schemas against empty node/occurrence sets.

The clean five-node customer-support pipeline and generated Prefect flow both
ran successfully. Streamlit `AppTest` loaded the real entrypoint and activated
the default pipeline without exceptions.

```text
$ PYTHONPATH=src python -m unittest discover -s tests -v
Ran 49 tests in 11.107s
OK

$ ruff check src/trace2flow tests streamlit_app.py
All checks passed!

$ PYTHONPATH=src python -m compileall -q src tests streamlit_app.py
completed with exit code 0

$ uv lock --check --offline
Resolved 179 packages in 2ms
```

Final clean demo artifacts were created under a new temporary directory:

```text
candidate.json: 5 nodes, 5 edges, 0 unresolved dependencies
workflow.json: 5 nodes, 5 edges, 0 blockers
generated_flow.py: 5 required tools, 2900 bytes
verification.json: 2/2 cases passed
```

Running that generated five-node Prefect flow against one fresh holdout
simulator produced `nodes_executed=5`, `final_output_match=true`, and
`state_match=true`.

An editable package build also succeeded, and the installed `trace2flow
--help` command exposed `validate`, `split`, `to-asp`, `mine`, `build-ir`,
`export-prefect`, and `verify`.

## M5 update

M5 adds independent, in-memory verification for the customer-support story:

- Added local registered implementations of customer lookup, order lookup,
  issue classification, action recommendation, and mock ticket update.
- Added a framework-independent local IR executor with the same blocker and
  registry preflight requirements as Prefect export.
- Added deterministic state diffs and `verification-report/1.0`, comparing both
  sink output and complete mutable ticket state.
- Added three synthetic compile runs and two provenance-disjoint held-out runs,
  plus an explicit reviewed resolution plan. The compile data produces five
  aligned nodes, five evidence-bearing edges, and no unresolved dependencies.
- Added structural replay with the fixed label
  `recorded_response_replay_partial` and
  `equivalent_execution_claimed=false`.
- Added `trace2flow verify` and an end-to-end CLI regression.

Actual end-to-end CLI result:

```text
compile: 3 synthetic complete runs
holdout: 2 synthetic complete runs
workflow: 5 nodes, 5 edges, 0 blockers
verification scope: independent_local_simulation
passed cases: 2/2
final output matches: 2/2
state matches: 2/2
```

An intentional expected-output and expected-state corruption produced a failed
case with both match flags false. These controlled synthetic results establish
only the demo behavior; they are not a success-rate or business-benefit claim.

```text
$ PYTHONPATH=src python -m unittest discover -s tests -v
Ran 44 tests in 9.660s
OK

$ ruff check src/trace2flow tests
All checks passed!

$ PYTHONPATH=src python -m compileall -q src tests
completed with exit code 0

$ uv lock --check --offline
Resolved 170 packages in 2ms
```

## M4 update

M4 adds one guarded execution target, Prefect 3:

- Added deterministic Python source generation from resolved Workflow IR.
- Added a fixed Prefect `@flow` and registered-tool `@task`; parameter values
  are emitted only as literals or validated JSON-path lookups.
- Added a two-stage allowlist: export requires every tool name in the declared
  set, and the generated flow checks its runtime `ToolRegistry` before the
  first call.
- Export fails before writing output when `execution_blockers()` reports an
  unresolved dependency, alignment, parameter, branch, or side effect.
- Added negative AST/runtime tests proving trace strings are not evaluated and
  unknown tools cannot dispatch.
- Added Prefect `>=3.8,<4`; the lock resolved Prefect 3.8.5 and it was installed
  in the isolated validation environment.

The generated two-node controlled flow was imported and run through the real
local Prefect 3.8.5 engine. Both registered tasks and the flow completed, and
the returned sink output was `{"result": 8}`. This is a controlled execution
smoke result, not a performance or production claim.

```text
$ PYTHONPATH=src python -m unittest discover -s tests -v
Ran 37 tests in 8.983s
OK

$ ruff check src/trace2flow tests
All checks passed!

$ PYTHONPATH=src python -m compileall -q src tests
completed with exit code 0

$ uv lock --check --offline
Resolved 170 packages in 2ms
```

## M3 update

M3 adds the framework-independent `workflow-ir/1.0` boundary:

- Added discriminated Pydantic bindings for typed declared constants, task
  input paths, accepted predecessor-output paths, and unresolved candidates.
- Added a `ResolutionPlan` for explicit human/config declarations. Every
  declaration is checked across all matching compile occurrences; conflicting
  constants, missing input paths, output mismatches, and output bindings
  without accepted dependency edges are rejected.
- Equality and historical invariance produce evidence-backed candidates only.
  They never silently become resolved lineage or business constants.
- Added validated workflow nodes/edges, cycle and reference rejection,
  occurrence evidence, explicit branch state, and explicit side-effect state.
  Writes and upstream conditional/mutually-exclusive signals require
  confirmation.
- Added `WorkflowIR.execution_blockers()` as the single safety gate consumed by
  later exporters and executors.
- Added `trace2flow build-ir` and a versioned IR specification.

Focused M3 verification passed: six IR tests plus one CLI test cover typed
round trips, all four binding forms, weak-equality ambiguity, historical
invariance, declaration contradictions, missing dependency edges, cycles,
references, branches, and write confirmation.

```text
$ PYTHONPATH=src python -m unittest discover -s tests -v
Ran 33 tests in 1.842s
OK

$ ruff check src/trace2flow tests
All checks passed!

$ PYTHONPATH=src python -m compileall -q src tests
completed with exit code 0

$ uv lock --check --offline
Resolved 100 packages in 1ms
```

## M2 update

M2 adds occurrence-aware structure mining while keeping the audited upstream
compiler unchanged:

- Added a stable upstream subprocess adapter. It accepts only the named
  `strict` and `relaxed` rules profiles, enforces a 60-second timeout, validates
  exposed output fields, and records the upstream baseline plus source,
  compiler, and rules SHA-256 values.
- Added versioned `candidate-dag/1.0` Pydantic models for candidate nodes,
  accepted edges, dependency evidence, and unresolved dependencies. This is an
  evidence artifact, not yet the M3 executable Workflow IR.
- Candidate occurrence signatures use tool name, parameter names, and declared
  side-effect shape, or an explicit `metadata.alignment_key`. They do not use
  parameter values, trace array position, or dependency direction.
- If the same signature appears more than once in a run, all distinct
  run-qualified calls remain present and the node is explicitly unresolved.
- Accepted edges come only from `depends_on`. Every accepted direction retains
  run/source-occurrence/target-occurrence evidence. Edges touching an
  unresolved node, reciprocal directions, and combined cross-run cycles are
  excluded from the DAG and recorded as unresolved.
- Added the local `trace2flow mine` CLI. It invokes no recorded tool and cannot
  select an arbitrary rules file.

Actual M2 CLI verification on the synthetic customer-support compile fixture:

```text
source runs: 3
candidate nodes: 5
accepted edges: 2
unresolved alignment nodes: 1
unresolved dependency groups: 2
```

The unresolved node contains all six distinct `lookup_order` calls (two per
run). The accepted edges are `classify_issue -> recommend_action` and
`recommend_action -> update_ticket`, each supported by three occurrence-level
records. Dependencies into and out of the ambiguous repeated-call family are
retained as unresolved evidence.

Actual M2 automated verification:

```text
$ PYTHONPATH=src python -m unittest discover -s tests -v
Ran 26 tests in 1.229s
OK

$ ruff check src/trace2flow tests
All checks passed!

$ PYTHONPATH=src python -m compileall -q src tests
completed with exit code 0

$ uv lock --check --offline
Resolved 100 packages in 2ms
```

The nine added tests cover the real upstream adapter/CLI path, repeated-tool
alignment with explicit keys, reordered independent calls, equal common values,
reciprocal evidence, cycles that emerge only across runs, and source-hash
mismatch and test-partition rejection.

One upstream limitation became more precise during M2: its ordering rules
require `spawned_by` parent structure. Direct actionable-call `depends_on`
chains in the typed customer-support fixture did not affect its phases, so all
five upstream tool types were placed in phase 0. Trace2Flow preserves that
observed upstream result as context but derives candidate edges separately from
the typed occurrence-level declarations.

## M1 update

M1 establishes a typed authority boundary in `src/trace2flow/` without
rewriting the audited upstream compiler:

- Added strict Pydantic models for schema version `1.0`, complete task runs,
  distinct tool-call occurrences, provenance, statuses, explicit references,
  side-effect metadata, task inputs, outputs, and state snapshots.
- Added deterministic canonical JSON serialization and stable validation
  diagnostics. Duplicate JSON keys, non-finite numbers, unknown fields,
  duplicate IDs, missing/self references, and dependency cycles are rejected.
- Added explicit run-level splitting. Compile/test overlap is rejected by both
  run ID and provenance fingerprint, so renaming a copied run does not bypass
  the guard.
- Added a reversible ASP parameter encoding based on canonical JSON and
  Base64URL. Values such as `1`, `1.0`, `true`, `null`, and `"1"` remain
  distinct even though the upstream ASP interface accepts strings.
- Added local `validate`, `split`, and `to-asp` CLI commands. They transform
  data only and do not execute trace content or contact external services.
- Added an explicitly synthetic customer-support fixture with 3 runs and 18
  call occurrences. Each run calls `lookup_order` twice to protect occurrence
  identity at the typed/adapter boundary.
- Added Pydantic to `pyproject.toml` and refreshed `uv.lock`.

Actual M1 CLI verification:

```text
validate: 3 runs, 18 steps, valid=true
split: 2 complete compile runs, 1 complete test run
ASP adapter: canonical-json-base64url-v1
upstream compile: 2 source runs, 5 core tool types
```

Actual M1 automated verification:

```text
$ PYTHONPATH=src python -m unittest discover -s tests -v
Ran 17 tests
OK

$ ruff check src/trace2flow tests
All checks passed!

$ PYTHONPATH=src python -m compileall -q src tests
completed with exit code 0

$ uv lock --check --offline
completed with exit code 0
```

The 17 tests include the 3 M0 upstream smoke tests. The new tests cover nested
JSON values, booleans, nulls, integers versus floats/strings, repeated tools,
canonical round trips, invalid references/cycles, leakage by ID/provenance,
CLI artifacts, reversible parameter encoding, and real invocation of the
pinned upstream compiler.

## Repository setup

- GitHub login verified as `JiaDodo`.
- Fork created at `https://github.com/JiaDodo/trace2flow` and verified by the
  GitHub API as a fork of `mirkokiefer/autocompile`.
- `origin`: `https://github.com/JiaDodo/trace2flow.git`
- `upstream`: `https://github.com/mirkokiefer/autocompile.git`
- Audited upstream commit:
  `b168d6760213b489e2fb2f5571f5d4e6d648dee8`
  (`feat: clinical pathway compilation from real sepsis data + fix concurrent phases`).
- No development commit has been pushed, and no PR or merge was created.
- The checkout was clean before M0 work; no pre-existing changes were present.

## Completed in M0

- Reviewed repository status/remotes, MIT license, `pyproject.toml`, `uv.lock`,
  README, trace specification, core compiler/rules, benchmark, codegen, Datalog
  alternatives, and experimental entry points.
- Reviewed scripts for credential/network behavior before execution. Core
  compile/benchmark/codegen are local. Optional files under `experiments/src/`
  contain OpenRouter/network paths and were not executed; no credential file
  was read.
- Created an isolated Conda environment at
  `/media/E/dodo/conda_envs/trace2flow-m0` with Python 3.12.14, Clingo 5.8.0,
  and pytest 8.4.2. The committed smoke suite itself uses `unittest` and does
  not require pytest.
- Ran the upstream travel-updates compile → benchmark → pseudo codegen → daslab
  codegen chain with outputs under `/tmp`, leaving tracked example artifacts
  untouched.
- Added a content-level smoke suite plus explicitly synthetic, run-disjoint
  train and holdout fixtures.
- Added development constraints, roadmap, status, and upstream audit docs.

## Actual validation results

Audited upstream example, using `mine_patterns_relaxed.lp`:

- Compilation completed for 177 source runs.
- Result contained 5 core tool types in 3 synthesized phases, 11 compiled calls,
  and the current `_analysis` metadata.
- Daslab codegen emitted 13 calls after list fan-out; pseudo codegen emitted all
  three phases.
- Benchmark printed 60% tool accuracy, 88% parameter accuracy, and a match in
  171/177 runs. These are **not held-out performance results** because the
  benchmark JSON covers the same run population used by the combined `.lp`
  compilation input. They establish CLI behavior only.

Committed synthetic smoke suite:

```text
$ python -m unittest discover -s tests -v
Ran 3 tests in 0.208s
OK
```

The train fixture has three synthetic runs and the holdout fixture has two
different synthetic runs. The controlled expected result is 100% for the
limited metrics that the upstream benchmark computes. This is a regression
oracle, not a product success-rate claim.

Negative capability checks:

- Direct JSON passed to `src/compile.py` exited 1 with Clingo syntax/lexer
  errors.
- ASP `.lp` passed to `src/benchmark.py` exited 1 with `JSONDecodeError`.

## Current blockers and limits

There is no blocker to the defined MVP. The upstream boundary still cannot
satisfy it by itself:

- Compile accepts ASP facts in practice, not the documented direct JSON input.
- ASP parameters are strings, so the current compiler path does not preserve
  original JSON types.
- Synthesis aggregates by tool name and therefore cannot represent repeated
  occurrences of the same tool safely.
- Stable-value frequency is treated as a compiled input; it is not a declared
  or confirmed business constant.
- The output is an unvalidated JSON shape, not a Pydantic Workflow IR, and it
  contains no per-edge evidence records or explicit unresolved bindings.
- Benchmark collapses actual calls to a tool set and the first parameter map,
  does not validate ordering despite its docstring, string-coerces scalar
  comparisons, and reports “no false positives” without requiring no misses.
- Daslab codegen embeds runtime bindings and conditions as annotations rather
  than executable semantics. There is no Prefect target or registered-tool
  execution gate.
- The root dependency set still mixes core and optional experimental packages;
  the isolated environment contains the core M0 dependencies, Prefect, and
  Streamlit for verified execution and UI testing.

Trace2Flow now supplies a validated IR, declaration-gated typed bindings,
explicit branch/side-effect resolution, safe Prefect export, a runtime tool
registry, independent held-out simulation, and the Streamlit inspection/demo
layer. Remaining limitations are documented in `docs/RELEASE_AUDIT.md`.

See `docs/UPSTREAM_AUDIT.md` for evidence and source locations.

## Next milestone

The requested MVP is complete. A post-MVP iteration should ingest a small set
of genuinely recorded but sanitized traces, add a richer occurrence-resolution
workflow, and evaluate conditional-expression IR without weakening the current
export gates. Production deployment and live customer integrations remain out
of scope.
