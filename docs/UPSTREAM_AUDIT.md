# Upstream AutoCompile Audit

Audit date: 2026-09-14

Repository: `mirkokiefer/autocompile`

Baseline commit: `b168d6760213b489e2fb2f5571f5d4e6d648dee8`

This document separates behavior observed at the pinned commit from broader
claims in upstream documentation. “Verified” means inspected and/or run
locally during M0; it does not mean production-ready or independently proven on
real systems.

## Provenance, license, and layout

- The Git history and fork relationship are preserved.
- `LICENSE` is the MIT License with copyright “2026 Mirko Kiefer”. It remains
  unchanged.
- Core entry points are `src/compile.py`, `src/benchmark.py`, and
  `src/codegen.py`; ASP rules live in `rules/`.
- `datalog/` contains Python, Soufflé, and egglog alternatives. They were
  inspected but not needed for the verified README path and were not executed
  in M0.
- `experiments/` contains domain prototypes, including optional code paths that
  access datasets, OpenRouter, Blender, or other non-core dependencies. Those
  paths were not executed.
- `pyproject.toml` requires Python >=3.12 and declares Clingo plus a broad set of
  experiment/data dependencies. `uv.lock` pins Clingo 5.8.0. The M0 core path
  was verified with Python 3.12.14 and Clingo 5.8.0.

## Compile: verified input, output, and behavior

Command exercised:

```bash
python src/compile.py \
  --traces examples/travel-updates/traces.lp \
  --rules rules/mine_patterns_relaxed.lp \
  --output /tmp/.../result.json
```

Observed behavior:

- `src/compile.py` resolves inputs relative to the project root, loads the trace
  and rule files directly into Clingo, solves for an optimized answer set, and
  writes JSON.
- The rules classify tools by the number of runs in which a tool name occurs.
  The default rule uses a 50% core threshold; the relaxed rule uses 25%.
- Ordering evidence comes from explicit `depends`/`spawned_by` facts, not raw
  list position. More precisely, the current `precedes_in_job` rules require
  `spawned_by` parent structure; a direct dependency between two actionable
  calls without that parent structure does not become an upstream ordering.
  M2 verified this on the typed customer-support fixture: despite direct
  `depends_on` chains, upstream placed all five tool types in phase 0.
- Conflicting tool-level ordering evidence is solved and reported, but
  `synthesize()` intentionally uses only consistent orderings as hard phase
  constraints. Conflicts are placed concurrently rather than imposing the
  chosen direction.
- Output has `_autocompile`, `_boundary`, `_analysis`, and `calls` sections.
  It is plain JSON without schema validation.
- On the travel example at the pinned commit: 177 source runs, 5 core tool
  types, 3 phases, and 11 synthesized calls.

Input mismatch found:

- README/spec text says JSON or ASP is accepted and JSON is converted
  internally. The executable compiler has no JSON parser or conversion branch;
  it passes `--traces` directly to `clingo.Control.load()`.
- Passing `examples/travel-updates/traces.json` to the compiler was tested and
  exited 1 with Clingo syntax/lexer errors. Direct JSON compile is therefore
  **not verified and currently unsupported in practice**.

Important limitations:

- Node identity is a tool name in synthesis (`step_ids[tool]`). Repeated calls
  of the same tool within a run are reduced to tool-level counts/patterns and
  cannot be represented as distinct logical nodes.
- ASP `param/4` values are strings, consistent with the current trace spec.
  Original JSON scalar/container types cannot survive this path.
- A parameter value occurring in at least half of runs using a tool is labeled
  stable and copied into executable-looking inputs. Stability is not proof of a
  declared business constant.
- Multiple stable values can become a list. Compiler synthesis has special-case
  fan-out for the field name `account`; this is domain-specific rather than a
  general binding model.
- Conditional relationships are based on tool co-occurrence containment, not
  output values or causal proof. Several possible dependencies can be emitted
  for the same tool.
- Dependency evidence is not retained per emitted edge in the JSON result.
- If the phase graph cannot make progress, synthesis assigns all remaining
  tools to a phase instead of surfacing a cycle/unresolved structure.
- There is no explicit representation of task input, prior-output binding,
  unresolved binding, side effects, or required human confirmation.

Primary source locations: `src/compile.py`, `rules/mine_patterns.lp`,
`rules/mine_patterns_relaxed.lp`, and `spec/trace-format.md`.

## M2 adapter and candidate-graph findings

Trace2Flow now invokes `src/compile.py` behind an adapter that accepts only the
audited `strict` or `relaxed` rule file, uses a 60-second timeout, and records
the baseline commit plus compiler, rules, and typed-source SHA-256 values. It
validates and retains the upstream output signals that are actually exposed:
core tools, synthesized phases/call count, conditionals, fusion candidates,
mutual exclusions, chosen conflict resolutions, and variable parameters.

These are contextual tool-level signals, not occurrence-level truth. The M2
candidate graph separately aligns run-qualified calls and builds edges only
from normalized `depends_on` declarations. The customer-support fixture
therefore retains all six `lookup_order` occurrences as an unresolved family,
accepts only the unambiguous `classify_issue -> recommend_action ->
update_ticket` chain, and keeps the two dependency families touching
`lookup_order` unresolved with their original run/call evidence.

M2 did not modify the upstream compiler or ASP rules.

## Benchmark: verified input, output, and behavior

Command exercised:

```bash
python src/benchmark.py \
  --compiled /tmp/.../result.json \
  --holdout examples/travel-updates/traces.json
```

Observed behavior:

- Both compiled workflow and evaluation traces are loaded with `json.loads`.
- Tools are converted to sets after three hard-coded glue tool names are
  removed.
- Parameters for repeated actual calls are taken from only the first call of a
  tool.
- Tool accuracy is recall over compiled core-tool predictions. Actual tools
  outside the core set are shown as misses but do not enter that percentage.
- Parameter scoring covers only parameters emitted in the compiled call and
  compares scalar values through `str()`. It does not validate retained JSON
  types.
- Conditional co-occurrence is reported, but ordering/phases are not checked,
  despite the module docstring listing ordering as a benchmark goal.
- “Runs with no false positives” does not require absence of missed tools.
- The CLI prints metrics but emits no machine-readable benchmark artifact.

Input mismatch found:

- The usage docstring mentions `.lp`, but the implementation is JSON-only.
  Passing an ASP trace was tested and exited 1 with `JSONDecodeError`.

Data-split caveat:

- The README quick-start benchmarks a result compiled from the combined travel
  `.lp` against the combined travel JSON population. Its observed 60% tool,
  88% parameter, and 171/177 match figures are not held-out estimates.
- M0 added separate synthetic training and holdout fixtures for regression
  smoke coverage. Their 100% expected score proves only that the narrow CLI
  path still behaves as asserted.

Primary source location: `src/benchmark.py`.

## Codegen: verified input, output, and behavior

Commands exercised:

```bash
python src/codegen.py --compiled /tmp/.../result.json --target pseudo
python src/codegen.py \
  --compiled /tmp/.../result.json \
  --target daslab \
  --output /tmp/.../job.json
```

Observed behavior:

- Only `pseudo` and `daslab` targets exist.
- Pseudo output renders phases, stable inputs, conditional comments, and a
  generic “steps requiring LLM” footer. It is inspection text, not executable
  Python.
- Daslab output maps a hard-coded set of Gmail, Sheets, and tracking parameter
  names, performs a few type coercions, expands the first list-valued parameter,
  and carries `waits_for` IDs.
- On the travel example, Daslab codegen expanded the 11 compiled calls to 13
  calls.

Important limitations:

- Runtime parameters are `_runtime_params`/`_note` annotations; no source
  binding expression is generated.
- Conditions are `_conditional` strings; no executable branch semantics are
  generated.
- Only the first list-valued parameter is expanded, so multiple lists do not
  express a defined zip/product relationship.
- Analysis-only fields are dropped through a hard-coded name list.
- There is no tool registry/allowlist enforcement, local executor, output/state
  verification, or Prefect target.

Primary source location: `src/codegen.py`.

## What M0 added versus what upstream already had

Upstream already provided the Clingo pattern miner, rule files, JSON-like
compiled result, printed benchmark, pseudo/Daslab code generation, examples,
Datalog/experimental prototypes, and MIT license.

Trace2Flow M0 adds only:

- this evidence-based audit and milestone documentation;
- repository working rules in `AGENTS.md`;
- a content-level automated smoke suite; and
- explicitly synthetic, disjoint train/holdout smoke fixtures.

M0 does not add typed JSON ingestion, Workflow IR, evidence-bearing DAGs,
binding inference, Prefect export, a simulator, or a Streamlit UI.

## M10 producer boundary

M10 adds an optional LangChain/DeepSeek trace producer and a fixed development
pilot checker under `src/trace2flow/`. It reuses the existing Trace2Flow local
customer-support simulator, not upstream experiment Agents. DeepSeek chooses
tool calls; classification and recommendations remain existing deterministic
rules. Raw recordings retain failures and model batch structure. Normalized
output is quarantined and contains no automatically inferred dependencies.
This pilot is not evidence of upstream automatic JSON ingestion or generalized
business workflow synthesis. The four audited upstream core paths remain
unchanged against the baseline commit.
