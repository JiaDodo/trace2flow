# Trace2Flow Roadmap

Trace2Flow turns repeated agent execution traces into an evidence-bearing,
framework-independent workflow and validates it in a local simulation. The
upstream AutoCompile miner remains a component, not the product boundary.

## M0 — Upstream and engineering baseline (complete)

Deliverables:

- Fork and remotes configured with preserved history and MIT attribution.
- Upstream commit, dependencies, entry points, input/output behavior, and
  limitations recorded.
- Upstream compile → benchmark → codegen path run in a clean Python 3.12
  environment without reading credentials or calling external services.
- Automated content-level smoke coverage on explicitly synthetic, run-disjoint
  compile and holdout fixtures.

Acceptance: `python -m unittest discover -s tests -v` passes and
`docs/UPSTREAM_AUDIT.md` distinguishes observed behavior from repository
claims.

## M1 — Typed trace ingestion and dataset boundaries (complete)

Deliverables:

- A single versioned JSON trace schema modeled with Pydantic.
- Lossless preservation of JSON parameter/output types, call occurrence IDs,
  declared dependencies, status, side-effect metadata, and synthetic labels.
- Deterministic validation errors and normalization.
- Run-level train/test split utilities and a guard that rejects overlapping run
  IDs or provenance fingerprints.
- An ASP adapter for the subset required by the upstream compiler; the typed
  source trace remains authoritative.

Acceptance: tests cover nested values, `null`, booleans, common numbers,
duplicate calls to one tool, invalid references, and split leakage. A typed
customer-support fixture compiles through the upstream adapter without type
loss in the retained source model.

## M2 — Occurrence-aware structure and evidence (complete)

Deliverables:

- Invoke the upstream compiler through a stable adapter and retain its mined
  tool-level signals as evidence.
- Align repeated call occurrences across runs without merging solely by tool
  name.
- Build a candidate DAG from explicit dependency evidence; call order is not a
  dependency.
- Record supporting and conflicting run/call evidence for every candidate edge.

Acceptance: repeated-tool and reordered-independent-call tests prove occurrence
identity and order independence. Ambiguous alignments remain unresolved.

## M3 — Workflow IR and parameter binding (complete)

Deliverables:

- Pydantic Workflow IR independent of Prefect and the local executor.
- Typed bindings for declared constants, task inputs, prior tool outputs, and
  unresolved values.
- Evidence and confidence rationale attached to dependencies and bindings.
- Explicit branch and side-effect resolution state.

Acceptance: round-trip serialization preserves types; weak equality evidence
does not create lineage; historical invariance alone does not create a
confirmed constant; invalid references and cycles are rejected.

## M4 — Safe Prefect export (complete)

Deliverables:

- One export target: Prefect.
- Generated flows can call only registered tool wrappers.
- Export gate rejects unresolved execution-critical bindings, branches, or side
  effects with actionable diagnostics.

Acceptance: generated code passes static checks, executes the controlled
fixture, and negative tests prove arbitrary trace code and unregistered tools
cannot run.

## M5 — Independent local simulation and verification (complete)

Deliverables:

- Local customer-support simulator for customer lookup, order lookup, issue
  classification, recommendation generation, and mock ticket update.
- State snapshot/diff plus final-output comparison against expected outcomes.
- Clear separation among compilation data, held-out test data, and simulator
  state.
- Replay results labeled as partial structural checks only.

Acceptance: success and intentional-failure cases verify both outputs and state
changes; no network, messages, refunds, or real customer data are used.

## M6 — Lightweight Streamlit demo and release audit (complete)

Deliverables:

- Streamlit UI for trace upload, candidate workflow, DAG/evidence inspection,
  unresolved-item resolution, Prefect export, and simulation results.
- Upstream-versus-Trace2Flow attribution in the UI and README.
- Reproducible demo command and final safety/licensing audit.

Acceptance: a clean local run demonstrates the complete customer-support story
without external credentials, and all automated tests pass.

## M7 — Recorded benchmark trace intake (complete)

Deliverables:

- Conservative importer for selected tau3-bench retail text simulations.
- Explicit benchmark-simulator provenance, producing revision, customer-data
  flag, dropped-field inventory, and honest recording claim.
- Type-preserving structured pseudonymization plus mandatory manual review.
- Review artifact for occurrence dependencies, side effects, and alignment;
  unreviewed imports are refused by candidate mining.
- Source-task-group partitioning and leakage rejection across repeated trials.

Acceptance: an official public retail simulation imports and validates without
credentials; tests prove tool argument types and repeated occurrences survive,
call order creates no dependency, incomplete review blocks mining, source-task
trials cannot cross partitions, and provider raw data is absent.

## M8 — Small reviewed recorded corpus (complete)

Deliverables:

- Select a narrow retail workflow family from distinct tau source tasks.
- Manually inspect and review a small compile/test corpus; keep raw results
  private and commit only licensing-safe reviewed normalized artifacts.
- Mine the compile partition and report structural coverage and unresolved
  items on the disjoint task-group holdout without inventing a success target.
- Add an independent matching local simulator only if the selected tau tools
  can be modeled faithfully; otherwise report ingestion/mining evidence only.

Acceptance: every run has pinned provenance and a review record, no source task
group crosses partitions, no unreviewed trace reaches mining, and all reported
numbers are reproduced from committed commands/artifacts.

## M9 — Recorded-workflow execution and presentation (complete)

Deliverables:

- Resolve bindings for the selected four-tool recorded workflow without
  promoting observed values to constants.
- Implement an independent, minimal retail simulator for only the selected
  lookup/product/item-modification behavior, using new local state rather than
  recorded response replay.
- Compare sink output and complete mutable order state on held-out cases.
- Add the recorded-corpus evidence and its limitations to the Streamlit demo,
  plus clean-install CI and a concise portfolio walkthrough.

Acceptance: the generated workflow runs only registered local retail tools;
intentional output/state corruptions fail; the UI clearly distinguishes
synthetic end-to-end verification, recorded structural coverage, and any new
independent execution result.

## M10 — DeepSeek trace producer (extension, complete)

Add a single-purpose LangChain `create_agent` producer using DeepSeek and the
existing five local simulated customer-support tools. Capture calls, typed
arguments/results, model messages/usage, failure endings, and full local state.
Do not impose a fixed business tool sequence. Guard task identity, observed
order facts, policy recommendations, and writes; keep the collector separate
from the upstream compiler. Live recordings use an explicit paid-call flag,
bounded calls, no automatic retries, and ignored local output directories.

Acceptance: offline scripted-model tests exercise the actual framework loop,
normal output/state, failed calls, strict types, repeated occurrences, budgets,
and partial recording. Unreviewed normalized output cannot enter mining. Run a
small explicitly authorized DeepSeek development pilot; report actual results
without treating the pilot as a holdout score or claiming automatic lineage.

## M11 — Reviewed agent corpus and independent evaluation (complete, controlled local experiment)

Freeze task partitions before collecting a larger corpus. Add a checked,
source-pinned review intake for collector recordings, preserving original raw
evidence and explicit dependency/binding declarations. Keep all failures and
unsupported structures in the evaluation inventory. Repeated trials and task
paraphrases remain within one task group. Evaluate Agent and workflow against
independently specified expected output/state on untouched test tasks, with
separate coverage, accepted-case correctness, unsafe acceptance, and review
effort. Recorded local model runs remain synthetic-business evidence.

M11a engineering baseline is complete:

- Predeclared 30-task plan: compile 10 / development 8 / test 12, with isolated
  entity identities, explicit independent output/state expectations and
  Agent-visible input projection.
- Source/plan/prompt freeze and final workflow/compile artifact pinning;
  intentionally unapproved exhaustive review drafts and strict review intake.
- Real upstream-backed build from reviewed compile runs, agreeing-declaration
  translation and unresolved-binding retention.
- Planned-task Agent evaluation and fresh-state workflow execution with
  separate admission coverage, correctness and safety; twenty offline tests.

M11b completed all thirty predeclared live tasks once, explicitly AI-reviewed
the compile population, recorded machine-check time while labeling manual AI
effort unmeasured, froze the workflow/report before test collection, and archived
complete reports including failed calls and a zero-call run. Workflow test
coverage is 8/12; all eight accepted output/full-state comparisons pass with
zero unsafe acceptances. A real local Prefect target run also passes. These
are controlled synthetic-business results, not automatic lineage discovery,
human-review evidence or production/generalization claims.

## M12 — Live-evidence demo handoff (complete)

Integrate the archived DeepSeek corpus/result into the existing Streamlit
inspection story without a new frontend architecture. Show one raw task/tool
recording, occurrence DAG, declared bindings, independent execution/state diff
and coverage alongside accepted correctness. Keep AI-review and synthetic-state
labels prominent and expose failure/zero-call evidence. Add a concise Chinese
demo script and screenshots. Reuse known archived fixtures for UI regression,
not a fresh holdout score. Any policy/workflow tuning needs a new predeclared
test population. No live customer integration or self-evolution loop is implied.

Completed: public-only offline source selection; four loss-labeled original
task/tool projections including repeated failure and zero-call evidence; frozen
five-node/three-edge DAG and per-occurrence evidence; all fifteen declared
bindings; twelve selectable known regression tasks with fresh-state execution,
output/full-state comparison and field diffs; separate historical coverage and
accepted correctness. Added 19 helper/UI tests and a real Chromium screenshot
script with seven screenshots plus `docs/LIVE_DEMO_WALKTHROUGH.md` in Chinese.
No model request, policy/core/scorer/frozen-artifact change or publication.

Acceptance verified by 141 offline tests (no skips), lint, source compile,
locked dependency check, package build, browser interaction/rendering checks
and unchanged upstream/frozen-pipeline diffs. Historical test results remain
M11 evidence, not newly measured holdout performance.

## Post-MVP release handoff (requires repository publication authority)

- Review the final branch history and choose merge/squash policy.
- Push the development branch and observe the first GitHub Actions clean
  install on hosted infrastructure.
- Capture a short demo recording and create a release tag only after the hosted
  checks pass.

M0–M9 now cover the scoped MVP. Production integrations, arbitrary intent
planning, and generalized branch synthesis remain intentionally out of scope,
not unfinished acceptance items.

## Out of scope for the MVP

Multi-user support, databases, live platform integrations, multi-agent
orchestration, general shell execution, complex client/server separation, and
production deployment are intentionally excluded.
