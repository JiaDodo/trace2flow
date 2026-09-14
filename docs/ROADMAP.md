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

## M8 — Small reviewed recorded corpus (next)

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

## Out of scope for the MVP

Multi-user support, databases, live platform integrations, multi-agent
orchestration, general shell execution, complex client/server separation, and
production deployment are intentionally excluded.
