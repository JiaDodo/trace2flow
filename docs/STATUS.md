# Trace2Flow Status

Last updated: 2026-09-14

Current milestone: M1 complete

Working branch: `feat/m1-trace-ingestion`

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

There is no blocker to M2, but the upstream boundary cannot satisfy the MVP by
itself:

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

See `docs/UPSTREAM_AUDIT.md` for evidence and source locations.

## Next milestone

M2: align repeated call occurrences across runs, invoke the upstream miner as
one evidence source, and build a candidate DAG whose edges retain supporting
and conflicting run/call evidence. Call order alone must not create an edge,
and ambiguous alignments must remain unresolved. No Prefect or UI work is
planned for M2.
