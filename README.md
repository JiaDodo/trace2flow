# Trace2Flow

Trace2Flow is a safety- and evidence-focused evolution of the upstream
[AutoCompile](https://github.com/mirkokiefer/autocompile) project. The current
Trace2Flow contribution adds strict, typed JSON trace ingestion, complete-run
dataset boundaries, a reversible adapter into the original ASP compiler, and
an occurrence-aware candidate DAG with per-edge evidence and explicit
ambiguity. Run it locally with:

```bash
PYTHONPATH=src python -m trace2flow mine \
  tests/fixtures/typed_customer_support.json \
  --output candidate.json

PYTHONPATH=src python -m trace2flow build-ir \
  tests/fixtures/typed_customer_support.json \
  --candidate candidate.json \
  --output workflow.json
```

Resolved workflows can be exported to Prefect only with an explicit tool
allowlist. See [the safe export guide](docs/PREFECT_EXPORT.md).

The complete synthetic customer-support compile and held-out simulation path
is documented in [the local verification guide](docs/LOCAL_VERIFICATION.md).
The conservative tau3-bench retail importer and its evidence language are
documented in [the recorded-data guide](docs/RECORDED_DATA.md).

An optional DeepSeek customer-support Agent now produces actual model/tool
recordings in the existing synthetic local simulator. It is a trace producer,
not a new compiler: raw evidence is saved locally, normalized output requires
dependency review, and live calls need an explicit paid-call flag. See
[the Agent collector guide](docs/AGENT_COLLECTOR.md).

The next evaluation stage has a predeclared 30-task synthetic plan, hash-bound
explicit review intake and independent Agent/workflow outcome scoring. The
engineering baseline is tested; full live corpus collection and untouched
model-test scoring are pending. See [the evaluation guide](docs/AGENT_EVALUATION.md).

A small checked-in recorded corpus demonstrates the non-synthetic data path:

```bash
PYTHONPATH=src python -m trace2flow evaluate-structure \
  examples/tau-retail-recorded/candidate.json \
  --compile examples/tau-retail-recorded/compile.json \
  --test examples/tau-retail-recorded/holdout.json \
  --output /tmp/trace2flow-structural-report.json
```

It contains three compile runs from tau task 44 and four held-out runs from
task 60. All four held-out runs cover the mined four-node/three-edge structure.
This is deliberately reported as structural evidence only, not execution
equivalence or a general benchmark success rate. See the
[corpus source record](examples/tau-retail-recorded/SOURCE.md).

M9 turns that reviewed structure into a deliberately narrower executable
contract. The caller supplies already-confirmed customer, order, current-item,
and replacement-item fields; Trace2Flow does not pretend the recorded traces
contain a general product-selection policy. Reproduce the fresh-state run:

```bash
PYTHONPATH=src python -m trace2flow build-ir \
  examples/tau-retail-recorded/compile.json \
  --candidate examples/tau-retail-recorded/candidate.json \
  --resolution examples/tau-retail-recorded/resolution.json \
  --output /tmp/trace2flow-retail-workflow.json

PYTHONPATH=src python -m trace2flow verify-retail \
  /tmp/trace2flow-retail-workflow.json \
  --cases examples/tau-retail-recorded/execution-cases.json \
  --output /tmp/trace2flow-retail-verification.json
```

The two execution cases use new local entities and state, not recorded
responses. Both the business-result node and the complete mutable order map
must match. See the [portfolio walkthrough](docs/PORTFOLIO_WALKTHROUGH.md) for
the evidence ladder and demo script.

See [the roadmap](docs/ROADMAP.md), [current status](docs/STATUS.md), and the
[upstream audit](docs/UPSTREAM_AUDIT.md) for the exact capability boundary.

## What the MVP does

```text
typed JSON traces
    -> upstream tool-level mining + Trace2Flow occurrence alignment
    -> candidate DAG with run/call evidence and unresolved items
    -> declaration-gated Workflow IR
    -> safe Prefect export + independent local simulation
```

The key idea is that a frequent pattern is evidence, not permission to execute.
Trace2Flow keeps repeated calls distinct, refuses to infer lineage from array
order or equal values, and requires declarations before constants, branches,
or writes become executable.

Run the complete local demo:

```bash
PYTHONPATH=src streamlit run streamlit_app.py
```

The default story compiles three synthetic customer-support runs and verifies
the resulting five-tool workflow against two separate synthetic holdout runs.
The same page separately shows recorded retail structure coverage and its
fresh-state local execution result. It uses only in-memory tool registries: no
real customer system, messages, payments, or refunds. See the
[release audit](docs/RELEASE_AUDIT.md) for tested scope and remaining limits.

## Contribution boundary

Upstream AutoCompile supplies the Clingo miner, ASP rules, original benchmark,
and pseudo/Daslab generation. Trace2Flow adds the strict JSON schema and split
guards, reversible typed adapter, occurrence/evidence DAG, Pydantic Workflow
IR, declaration-based bindings, registered-tool Prefect export, independent
simulator/verifier, and Streamlit inspection UI. The upstream Git history,
license, and attribution are preserved.

The original AutoCompile overview follows. Its broad product claims describe
upstream intent; verified behavior and known gaps are recorded in the audit.

## Upstream AutoCompile overview

AI agents spend most of their compute re-deriving decisions that were already answered by the last hundred runs. autocompile watches processes run and discovers their structure from data. What's invariant becomes compiled code. What varies becomes a parameter. What conflicts gets resolved by optimization. The LLM isn't eliminated -- it's relocated to exactly the decisions that require judgment.

The output is a program that separates the known from the unknown -- a map of where intelligence is actually needed, with empirical accuracy metrics for every compiled step.

## The pipeline

```
1. Observe    Collect execution traces from repeated workflow runs
2. Compile    Mine patterns using Answer Set Programming (Clingo)
3. Benchmark  Validate compiled program against held-out traces
4. Codegen    Emit an executable job spec for your runtime
```

## What the compiler discovers

Given execution traces, autocompile automatically identifies:

- **Core tools** -- which tools appear consistently across runs
- **Parallel groups** -- which tools always run concurrently
- **Dependency ordering** -- which tools must precede others
- **Conflicting orderings** -- when evidence disagrees, the solver picks the optimal direction
- **Conditional execution** -- "tool B only runs when tool A produced results"
- **Fusion candidates** -- sequential steps that can be merged into one operation
- **Mutually exclusive tools** -- branch alternatives that never co-occur
- **Stable vs variable parameters** -- which inputs are constant vs runtime-dependent

All patterns are discovered from data alone. The ASP rules are completely generic -- no workflow-specific knowledge needed.

## Why ASP (Answer Set Programming)

The simple patterns (frequency counting, parameter stability) don't need a logic solver. But real workflows have **conflicting evidence** -- tool A precedes B in 60% of runs, but B precedes A in 40%. autocompile uses Clingo's choice rules to model these conflicts and optimization to resolve them:

```prolog
% When orderings conflict, choose one direction
{ chosen_order(A, B) ; chosen_order(B, A) } = 1 :- conflicting_order(A, B).

% Minimize violations against observed evidence
#minimize { N@2,T1,T2 : order_cost(T1, T2, N) }.
```

The solver explores all consistent combinations and returns the optimal compilation. As rules grow more complex (resource constraints, branching logic, cross-workflow optimization), the ASP program grows linearly while a hand-coded solver would grow combinatorially.

## Examples

### Travel updates (177 runs)

27 real production traces + 150 synthetic traces modeled on observed patterns. The compiler discovers a 5-phase workflow with conditional branching:

```
Phase 0:  gmail_search x3 accounts (parallel)
Phase 1:  sheets_read x2 spreadsheets
            ↳ conditional on gmail_search (95% of runs)
Phase 2:  gmail_list_threads x3 accounts
            ↳ conditional on gmail_search (53% of runs)
Phase 3:  gmail_get_thread x3 accounts
            ↳ conditional on sheets_read (34% of runs)
Phase 4:  sheets_update_values
            ↳ conditional on gmail_get_thread (94% of runs)
```

4 conflicting orderings resolved by optimization. 2 fusion candidates identified (`gmail_search + gmail_get_thread`). Benchmark against held-out traces: **88% parameter accuracy, 96% of runs matched**.

### Order updates (118 runs)

118 real production traces. 6 conflicting orderings resolved. 4-phase compiled DAG. Benchmark: **73% parameter accuracy, 96% of runs matched**.

### A note on data

The travel example includes synthetic traces, clearly labeled in the `.lp` files. The order example is 100% real production data.

## Quick start

```bash
pip install clingo
git clone https://github.com/mirkokiefer/autocompile
cd autocompile

# 1. Compile: mine patterns from traces
python src/compile.py \
  --traces examples/travel-updates/traces.lp \
  --rules rules/mine_patterns_relaxed.lp \
  --output result.json

# 2. Benchmark: validate against traces
python src/benchmark.py \
  --compiled result.json \
  --holdout examples/travel-updates/traces.json

# 3. Codegen: emit executable pseudocode
python src/codegen.py --compiled result.json --target pseudo

# 4. Codegen: emit runnable job spec
python src/codegen.py --compiled result.json --target daslab --output job.json
```

## Compilation operations

autocompile applies compiler optimizations to observed workflows:

- **Constant folding** -- Steps that always produce the same output are replaced with the cached result
- **Strength reduction** -- Expensive steps are downgraded to cheaper equivalents where benchmarks confirm equivalence
- **Inlining / fusion** -- Sequential steps with deterministic data flow are fused into a single operation
- **Parallelization** -- Independent steps are scheduled concurrently
- **Dead code elimination** -- Steps whose outputs are never used downstream are removed
- **Branch compilation** -- Conditional execution patterns are inferred from co-occurrence data

## Model compilation

For steps that remain as `llm_invoke`, autocompile can test whether a cheaper model produces equivalent results. Using the inputs and outputs from existing traces as ground truth:

```
extract_booking_details:
  claude-sonnet-4-5   25/25 correct (baseline)
  qwen-3.5-35b        24/25 correct (96%)    downgrade candidate
  regex extraction     18/25 correct (72%)    not ready
```

*Status: WIP. The benchmarking framework supports this but model comparison is not yet implemented.*

## Datalog backends

The `datalog/` directory ports the monotonic fragment (~70% of the ASP rules) to three Datalog engines. All produce identical results to Clingo:

```
Engine         Solve time    Notes
─────────────────────────────────────────────
Clingo (ASP)      52ms       Full pipeline (choice rules + optimization)
Soufflé          175ms       Compiled Datalog (includes subprocess overhead)
egglog            39ms       Datalog + equality saturation
Python            15s        Reference implementation (pure Python, no deps)
```

The remaining ~30% (conflicting order resolution via choice rules and `#minimize`) stays in Clingo. See `datalog/` for details.

## Trace format

autocompile takes execution traces as JSON or ASP facts:

```json
{
  "runs": [
    {
      "id": "run_1",
      "steps": [
        {"id": "step_1", "tool": "gmail_search", "params": {"query": "flights"}, "status": "completed"},
        {"id": "step_2", "tool": "sheets_read", "depends_on": ["step_1"], "status": "completed"}
      ]
    }
  ]
}
```

See [spec/trace-format.md](spec/trace-format.md) for the full specification.

## Project structure

```
autocompile/
├── src/
│   ├── compile.py            # Trace → compiled workflow (ASP strategy)
│   ├── benchmark.py          # Validate compiled workflow against traces
│   └── codegen.py            # Compiled workflow → executable program
├── rules/
│   ├── mine_patterns.lp      # ASP rules (50% threshold)
│   └── mine_patterns_relaxed.lp  # ASP rules (25% threshold)
├── datalog/
│   ├── mine_patterns.dl      # Soufflé port of ASP rules
│   ├── souffle_compile.py    # Soufflé runner
│   ├── egglog_compile.py     # egglog runner
│   ├── engine.py             # Pure Python Datalog evaluator
│   └── compile.py            # Python engine runner
├── examples/
│   ├── travel-updates/       # 177 runs (27 real + 150 synthetic)
│   └── order-updates/        # 118 runs (100% real)
├── experiments/              # Cross-domain prototypes (robotics, lab, edge compute)
└── spec/
    └── trace-format.md       # Trace format specification
```

## Prior art

- **Compiler optimization** -- The operations are textbook. We apply them to workflows instead of instruction streams.
- **Trace-based JIT** (V8, LuaJIT) -- Observe runtime behavior to decide what to optimize. autocompile infers the program itself from traces.
- **Process mining** (Celonis) -- Discovers workflow models from event logs. autocompile compiles the discovered workflow into an executable program.
- **Program synthesis** -- Generates programs from input/output examples. autocompile applies this at the workflow step level.
- **Autonomous research** (autoresearch) -- LLM mutates code, keeps improvements. The LLM generates variations. autocompile discovers structure from observed variations instead.

## Status

Early-stage. The core pipeline works on agent workflow traces today. The same ASP rules are domain-generic -- they work on any process that produces sequential action traces. The `experiments/` directory has prototypes for robotics (LeRobot), autonomous lab protocols, and edge compute pipelines.

## License

MIT
