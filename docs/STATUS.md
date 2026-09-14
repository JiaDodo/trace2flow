# Trace2Flow Status

Last updated: 2026-09-14

Current milestone: M0 complete

Working branch: `feat/m0-baseline`

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

There is no blocker to M1, but the upstream boundary cannot satisfy the MVP by
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

M1: implement typed, versioned JSON ingestion and run-level dataset-boundary
checks, then adapt the validated trace subset to upstream ASP without treating
the lossy ASP representation as the source of truth. No UI work is planned for
M1.
