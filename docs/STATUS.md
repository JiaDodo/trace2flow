# Trace2Flow Status

Last updated: 2026-09-14

Current milestone: M2 complete

Working branch: `feat/m2-evidence-dag`

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

There is no blocker to M3, but the current M2 artifact is deliberately not
executable and the upstream boundary cannot satisfy the MVP by itself:

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
- The root dependency set mixes core and optional experimental packages; only
  the minimal core dependency was installed for M0.

Trace2Flow now supplies validation and edge evidence around this output, but it
does not yet classify parameter bindings, declare business constants, resolve
branches/side effects, export Prefect, or execute the local simulator.

See `docs/UPSTREAM_AUDIT.md` for evidence and source locations.

## Next milestone

M3: define the framework-independent Workflow IR and infer typed candidate
bindings for task inputs and prior tool outputs while leaving weak equality,
undeclared constants, branch semantics, and execution-critical ambiguity
explicitly unresolved. Add round-trip, cycle/reference, and false-lineage
regression tests. No Prefect or UI work is planned for M3.
