# Trace2Flow Development Guide

This repository is a fork of `mirkokiefer/autocompile`. Preserve its Git
history, MIT license, copyright notice, and attribution. Keep upstream
capabilities distinct from Trace2Flow additions in code, docs, and demos.

## Start every milestone

1. Read `docs/STATUS.md`, `docs/ROADMAP.md`, and the closest applicable
   `AGENTS.md`.
2. Inspect `git status --short --branch`; preserve all existing work.
3. Confirm the milestone acceptance criteria before changing code.
4. Update `docs/STATUS.md` with commands actually run and their real results.

## Safety and correctness constraints

- Never execute code carried inside a trace. Execution may call only an
  explicit registry of local simulated tools.
- Keep tool-call occurrences distinct. A tool name is not a node identity,
  because one run may call the same tool multiple times.
- Do not infer data lineage from call order or value equality alone. Treat
  booleans, nulls, small/common numbers, and other ambiguous matches as weak
  evidence and retain ambiguity.
- Do not promote an observed invariant to a business constant without an
  explicit declaration or human confirmation.
- Represent unresolved parameters, branches, dependencies, and side effects.
  Refuse executable export while execution-critical items remain unresolved.
- Split compilation and evaluation data by complete task run. Do not leak
  calls from one run across the split.
- For imported benchmark data, keep every trial of one source task group in a
  single partition. `source + task_group_id` overlap is leakage even when run
  IDs differ.
- Mark synthetic traces and fixtures as synthetic. Synthetic results establish
  only controlled-scenario behavior.
- Recorded-response replay is structural validation, not evidence of execution
  equivalence. Final validation must use a separate local simulated state.
- Do not invent success rates, cost savings, or LLM-call reductions.
- Do not connect real customer systems, send messages, or issue refunds.

## Upstream boundary

Treat `src/compile.py`, `rules/`, `src/benchmark.py`, and `src/codegen.py` as
audited upstream code at baseline commit
`b168d6760213b489e2fb2f5571f5d4e6d648dee8`. Prefer adapters and regression
tests over an unverified rewrite. If a core change is necessary, keep it small,
state why the adapter boundary was insufficient, and add a focused regression
test.

The baseline compiler consumes ASP facts in practice; direct JSON compilation
is not implemented. Its synthesized nodes are grouped by tool type, parameters
are ASP strings, and the current code-generation annotations are not executable
runtime bindings. See `docs/UPSTREAM_AUDIT.md` before relying on an upstream
claim.

## Validation commands

The core smoke path needs Python 3.12 and Clingo 5.8.0. Trace2Flow's typed path
also needs the Pydantic version recorded in `uv.lock`. Tests intentionally use
the standard-library `unittest` runner:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m compileall -q src tests
```

The normalized Trace2Flow format is specified in
`spec/trace2flow-trace-v1.md`. Validate a trace without executing it:

```bash
PYTHONPATH=src python -m trace2flow validate traces.json
```

Tau retail imports are quarantined until a complete explicit review supplies
dependencies, side effects, occurrence alignment where needed, and confirms
manual redaction. The importer never treats message order as lineage:

```bash
PYTHONPATH=src python -m trace2flow import-tau results.json \
  --dataset-id tau3_retail_reviewed \
  --task-id TASK_ID \
  --successful-only \
  --review review.json \
  --output reviewed.json
PYTHONPATH=src python -m trace2flow split reviewed.json \
  --test-group-id HELD_OUT_TASK_ID \
  --compile-output compile.json \
  --test-output test.json
```

Evaluate candidate structure only against a disjoint holdout. This command
never claims output or state equivalence:

```bash
PYTHONPATH=src python -m trace2flow evaluate-structure candidate.json \
  --compile compile.json \
  --test test.json \
  --output structural-report.json
```

Keep raw data under ignored `data-private/`. See `docs/RECORDED_DATA.md`.

Mine an evidence-bearing candidate DAG through the audited upstream adapter:

```bash
PYTHONPATH=src python -m trace2flow mine compile.json \
  --output candidate.json \
  --rule-profile strict
```

Only the named `strict` and `relaxed` rule profiles are accepted. Candidate
edges must come from explicit `depends_on` evidence; upstream phases and call
order are contextual signals, not substitutes for occurrence-level lineage.

The framework-independent IR is specified in `spec/workflow-ir-v1.md`. Build
it without executing tools:

```bash
PYTHONPATH=src python -m trace2flow build-ir compile.json \
  --candidate candidate.json \
  --resolution resolution.json \
  --output workflow.json
```

Never convert equality or historical invariance into a resolved binding.
Resolved bindings require declarations that validate against all aligned
compile observations.

When recorded task inputs are unstructured, a reviewed runtime schema may use
`evidence_mode=declared_runtime_contract`. Keep that weaker evidence label in
the IR: it declares where a future invocation supplies a value and does not
claim the path was observed in historical input. Use `output_node_ids` to name
business results instead of inventing data edges to eliminate independent
structural sinks.

Prefect export must go through `trace2flow.prefect_export.export_prefect` and
the generated flow must dispatch through `ToolRegistry`. Do not add dynamic
imports, `eval`, `exec`, shell execution, or a fallback for unknown tools.

Customer-support equivalence claims must come from `verify_workflow` against a
disjoint `test` partition and fresh simulator state. A structural replay must
remain labeled partial and must never set an execution-equivalence claim.

Reproduce the recorded-retail execution separately. Its structure comes from
recorded tau simulations, but its executable inputs and state are new local
synthetic fixtures and recorded responses are never replayed:

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

The Streamlit entrypoint is `streamlit_app.py`. Keep business logic in tested
`trace2flow` modules, render uploaded content only through safe Streamlit data
elements, and retain the fixed customer-support tool allowlist.

To reproduce the audited upstream example without overwriting tracked example
outputs, write all generated files to a temporary directory:

```bash
audit_dir="$(mktemp -d /tmp/trace2flow-audit.XXXXXX)"
python src/compile.py \
  --traces examples/travel-updates/traces.lp \
  --rules rules/mine_patterns_relaxed.lp \
  --output "$audit_dir/result.json"
python src/benchmark.py \
  --compiled "$audit_dir/result.json" \
  --holdout examples/travel-updates/traces.json
python src/codegen.py \
  --compiled "$audit_dir/result.json" \
  --target pseudo \
  --output "$audit_dir/workflow.txt"
python src/codegen.py \
  --compiled "$audit_dir/result.json" \
  --target daslab \
  --output "$audit_dir/job.json"
```

The example benchmark above reuses the compilation population and is only a
CLI smoke check. It must not be reported as held-out performance.

## DeepSeek trace collection

Install the optional producer with `uv sync --locked --extra agent --group dev`.
Use `langchain.create_agent`, not a custom Agent framework. Model credentials
come only from `DEEPSEEK_API_KEY`; never log them, headers, provider exception
text, or read `.env` in diagnostic output. LangSmith cloud tracing stays off.
Live requests require explicit user authorization and `--allow-paid-call`:

```bash
uv run --extra agent python -m trace2flow.agent_collect \
  examples/customer-support-agent/delivery-delay.json \
  --allow-paid-call --output data-private/agent-pilot/NEW_RUN
```

Never overwrite recording directories or select only successful runs after
collection. Zero-tool runs have raw records only (the normalized schema needs
one actual call); do not invent a step. Normalized collector output is
quarantined until dependencies, alignment, effects, and bindings are reviewed.
Guard requirements and list order are not data-dependency proof. Scripted
responses prove collector mechanics, not model capability. Live development
pilots are not held-out estimates; preserve full task-group partitions.

## Reviewed Agent corpus and evaluation

Use `docs/AGENT_EVALUATION.md` for M11 commands. Predeclare full task groups and
compile/development/test roles before collection. Do not send scenario labels,
state snapshots or oracle answers to the model. Preserve every paid attempt,
including failures and zero-call records. Repetitions require a new declared
inventory, not an invisible retry. Freeze sources before collection, and the
final workflow/compile artifacts before unlocking test results.

`agent_review --draft` is intentionally unapproved. Do not fabricate reviewer
identity, human participation or review time. Include decisions require
exhaustive checked declarations; ambiguity and disagreement must remain IR
blockers. Excluded compile records stay in the planned-task evaluation.
`agent_build` may compile only included reviewed compile-role data. A declared
customer/order admission guard must not be described as mined branching.

M11b evidence is archived under `examples/customer-support-agent/live-v1/`.
Read `docs/AGENT_EXPERIMENT.md` and `SOURCE.md` before making claims. Contract
review names exact occurrence IDs and is AI-reviewed, not human. Machine check
time is not manual AI/human effort. Zero-tool `test-11` stays raw-only. These
task fixtures are now known regression data: do not reuse them as untouched
holdout after policy/workflow changes. Keep the historical frozen report and
pipeline separate from any newly tuned version. A public archive without raw
recordings reproduces workflow simulation, not provider authenticity.

Run the offline baseline with:

```bash
.venv/bin/python -m unittest discover -s tests -p test_agent_corpus.py -v
```

Separate scripted regression results, actual local-model recordings and real
customer data claims. Report workflow coverage and accepted correctness
separately; pending runs mean the model score is not final. Complete state
comparison is required. Final-chat quality is currently unmeasured. Public
test definitions and local hash manifests are logical seals, not access control
or authenticity attestation. Never auto-push this evaluation branch.

## Standard conversational Agent and M13

The runnable baseline is `trace2flow.support_agent`, backed only by the local
synthetic `trace2flow.support_backend`. Read `docs/STANDARD_AGENT.md` before
changing it. A request contains natural user text plus host-authenticated
customer/ticket identity; never add scenario names, oracle answers, expected
actions, policy decisions or state snapshots to model-visible input.

Keep identity in immutable runtime context and out of model tool schemas. Read
tools must enforce ownership without distinguishing foreign from missing IDs.
`update_ticket` is the only write: retain evidence validation, idempotency,
one-attempt limit and human interrupt before mutation. Never expand the demo
into messages, carrier contact, refunds, arbitrary code or a live customer
backend. Keep provider tracing off and omit credentials, raw payloads,
reasoning and provider exception text from recordings.

Agent dependencies are optional but direct; update both `pyproject.toml` and
`uv.lock`. Run the focused baseline with:

```bash
uv sync --locked --extra agent --group dev
.venv/bin/python -m unittest tests.test_support_agent -v
```

Paid calls require existing user authorization, `DEEPSEEK_API_KEY` and the
explicit CLI `--allow-paid-call`. Use a new ignored `data-private/` path for
every attempt; never overwrite, retry-select or call a development attempt an
evaluation. Human approval in the CLI is limited to the local mock write.

M13 must not alter M11 frozen code or artifacts. The next trace adapter/router
must fall back to the Agent on ambiguity and require explicit reviewed workflow
promotion. Freeze a new disjoint evaluation before comparing accuracy, unsafe
writes, failures, calls, tokens or latency; no metric improvement is presumed.

M13b modules are `trace2flow.support_trace` and
`trace2flow.support_router`; read `docs/ADAPTIVE_ROUTER.md` before modifying
them. Unreviewed standard-Agent recordings must retain
`import_review_status=required`, empty dependencies and empty effects. Review
inventory is exhaustive and hash-bound; do not infer it from call order, equal
values or state change alone. Failed/partial runs remain evidence but cannot be
merged by the promotion helper.

The registry is append-only and has no implicit default. Keep workflow,
verification and promotion hashes identical; never replace a version in place.
The narrow delivery contract requires one explicit order ID and unambiguous
language. All mismatch, conflict, ownership, preflight and multiple-registration
cases fall back to the Agent. Workflow preview runs only on a clone. Approval
must rerun reads and evidence checks against live state before the idempotent
local write. Preserve the same router `resume` API for workflow and Agent
fallback approvals.

Run the focused M13 integration tests with:

```bash
.venv/bin/python -m unittest tests.test_support_router tests.test_support_agent -v
```

M13c evaluation is implemented in `trace2flow.support_evaluation`; read
`docs/PAIRED_AGENT_EVALUATION.md` before changing it. The checked-in plan and
freeze must be committed before any result call. Never modify a frozen source
or task and continue with the old freeze. Run each case/arm once, retain errors,
use a fresh backend for every attempt, and keep full turns/states under the
ignored `data-private/` directory. Oracle fields belong only to scoring and the
exact-match approval policy; never pass them to the model. Public reports must
be produced through the hash-bound `publish` command and must not include
messages, answers, turns or state snapshots.

Run the focused M13c controls with:

```bash
.venv/bin/python -m unittest tests.test_support_evaluation -v
```

## Scope discipline

M12 live-evidence helpers are `trace2flow.live_demo` and `live_demo_ui`; the
Streamlit source switch retains the synthetic/tau path. The default live page
must remain offline and public-only: no provider call, credential lookup,
private raw-file read or compiler rerun. Public `recordings/` files are lossy
task/tool projections, not complete raw recordings or normalized traces. Keep
the original raw hash, occurrence IDs, parameter types and privacy labels.
`demo-index.json` pins public bytes for integrity, not provider authenticity.
Reject mixed archive/pipeline identities before showing historical metrics.
New local executions must compare independently declared output and all three
state maps, never overwrite historical reports or call known fixtures fresh
holdout. Preserve failure, exception and zero-call evidence.

```bash
.venv/bin/python -m unittest discover -s tests -p test_live_demo.py -v
.venv/bin/ruff check src/trace2flow tests streamlit_app.py scripts/capture_m12_demo.py
```

See `docs/LIVE_DEMO_WALKTHROUGH.md` for the Chinese demo and local-only
Playwright screenshot script. Screenshot tooling is optional and not a project
dependency. Wait for the actual DAG/tables to render, not just the page title.

- Implement one testable milestone per iteration.
- M0 contains audit docs and smoke coverage only; it does not authorize UI or
  full-MVP work.
- Do not push branches, open pull requests, or merge unless the user explicitly
  requests it.
