# Trace2Flow Status

Last updated: 2026-09-16

Current milestone: M14a complete — audited public τ³ retail inventory

Working branch: `feat/m14-public-dataset`

## M14a public τ³ retail expansion

Pinned the official `sierra-research/tau2-bench` checkout at commit
`2174a603f6d014ef94473ffa95957f6ce27100db` and audited the current retail
source. It contains 114 simulated tasks: 74 official train and 40 official
test. This is public benchmark data, not real customer data and not observed
Agent traces.

- Added `trace2flow.tau3_corpus`, which verifies the Git revision, MIT license,
  and exact hashes of the license, retail tasks, split, policy and DB before
  building a manifest. It rejects unexpected task counts, overlapping or
  incomplete official splits, duplicate IDs, and output overwrite.
- The official 40-task test oracle is sealed. The checked-in manifest exposes
  only test IDs/count; it includes no test instructions, reference actions,
  expected state or NL assertions.
- The 74 official train tasks form 35 transitive shared-entity groups. Stable
  hash ordering assigns whole groups to 48 compile and 26 development tasks;
  no such group crosses those roles. Because pilot task 105 was already
  observed, its complete 19-task entity group is explicitly forced to
  development before assignment.
- Added a checked-in manifest, source/license record, redacted pilot report,
  protocol documentation and seven regression tests. The manifest explicitly
  says task/action oracles are not execution traces.
- The existing conservative τ³ result importer accepts the current upstream
  result structure: the valid pilot imports as one completed, unreviewed,
  quarantined run with eight distinct call occurrences. No dependency is
  inferred from order and it is not eligible for mining without review.

The isolated upstream checkout needed `websockets==17.1` after its locked
core-only install because `tau2 check-data` eagerly imports a voice module. No
upstream file was modified. After that integration-only dependency addition,
`tau2 check-data` passed.

Three DeepSeek attempts on official **train** task 105 were retained locally:

| Attempt | Result | Evidence |
|---|---|---|
| 1 | infrastructure failure | provider did not consume `DEEPSEEK_API_KEY` directly (`AuthenticationError`) |
| 2 | infrastructure failure | conversation ran, hard-coded NL evaluator model was incompatible (`BadRequestError`) |
| 3 | evaluated failure | reward 0.0; DB 1.0, NL assertion 0.0; expected exchange not executed |

Attempt 3 took 177.98 seconds. Its trajectory contains 10 Agent messages with
reported usage, 8 tool calls and no tool error. Reported Agent usage is 68,422
prompt plus 6,049 completion tokens; the user simulator consumed another 7,277
prompt plus 3,688 completion tokens. Evaluator usage is not available. The
Agent batched five order lookups in one message, violating the domain policy's
one-call-at-a-time rule. LiteLLM lacked a price mapping, so cost is reported as
unavailable, not zero. This one development failure proves integration only;
it is not a holdout estimate and was not retried into a success.

Actual focused checks at this point:

```text
$ PYTHONPATH=src .venv/bin/python -m unittest tests.test_tau3_corpus -v
Ran 7 tests; OK

$ PYTHONPATH=src .venv/bin/python -m trace2flow.tau3_corpus \
    data-private/tau2-bench-source --output /tmp/.../manifest.json
{"compile": 48, "development": 26, "sealed_test": 40, "tasks": 114, ...}

$ data-private/tau2-bench-source/.venv/bin/tau2 check-data
Data directory exists; You can now run tau2 commands.

$ PYTHONPATH=src PREFECT_SERVER_ALLOW_EPHEMERAL_MODE=true \
    .venv/bin/python -m unittest discover -s tests -v
Ran 184 tests in 23.639s; OK; no skips

$ .venv/bin/ruff check src/trace2flow tests streamlit_app.py scripts/capture_m12_demo.py
All checks passed!

$ .venv/bin/uv lock --check --offline
Resolved 202 packages; lock unchanged

$ .venv/bin/uv build --out-dir /tmp/trace2flow-m14-build.XXXXXX
Successfully built sdist and wheel containing trace2flow.tau3_corpus
```

M14b's pre-result contract was implemented and frozen locally: a six-task
family-stratified plan, source/manifest/task hashes, one attempt each, zero
retries, a local τ³ adapter that fails rather than truncates multiple tool
calls, explicit DeepSeek models and separate evaluator-usage capture.

The paid batch retained all six results once with no retry. Four terminated as
`agent_error` because DeepSeek mixed response text with one tool call; two
terminated as guarded `infrastructure_error` results after proposing multiple
tool calls. Available reward is 0/4 and successes are 0/6. All six are policy
violations. Reported usage was 71,091 Agent prompt + 1,440 completion tokens,
and 4,995 user-simulator prompt + 1,356 completion tokens. No trajectory
reached the NL evaluator. Monetary cost remains unavailable, not zero.

The development gate failed, so the 40 test oracles remain sealed. M14c will
freeze a source-hashed strict tool-only response contract and untouched
development tasks before one final compatibility batch. If that declared gate
fails, this external benchmark line closes as a negative result. M13d's typed
user-facing outcome fix is still outstanding and M13c remains historical
evidence; it is not rescored.

## M13c paired evaluation

Implemented and froze the comparison contract before collecting results. The
plan contains six synthetic task cases and two arms with one attempt per
case/arm. Compile group `m13b-reference-delivery` is disjoint from every
evaluation group. Both arms receive only the natural message plus trusted
customer/ticket identity and start from an independent fresh backend.

- Plan SHA-256:
  `32f705687395d05f0ea5bc40d3fcef9263b8eba20bf3d9b945892b04760d76f4`.
- Reviewed reference workflow SHA-256:
  `1e4e72a83c379b581b029183fe3cc201bfceac91bc73f0b931fae2200e470c87`.
- The freeze binds five implementation files, the complete registration and
  scorer. Any later source or plan change fails verification.
- Full attempt turns and state snapshots are confined to ignored
  `data-private/`; public export rejects private fields and is freeze-bound.
- The exact-oracle approval policy approves only a predeclared correct local
  status/category pair. Incorrect proposals are rejected and counted; no real
  message, refund, carrier call or customer-system write exists.
- Added ten evaluation-control tests covering public-result integrity,
  task-group separation, oracle
  isolation, registry validation, complete-state/output scoring, tamper
  detection, paid-call gates, failure retention and safe publication.

The contract was committed as `dd36900` before result access. The explicitly
unlocked DeepSeek run then completed all 12 attempts exactly once. The public
report SHA-256 is
`1fd797a49ddbca69691bb298d83fe25703f631e880347edabe3af8d314278748`;
the 12 full attempts plus private report remain in the ignored
`data-private/support-m13c-v1/` directory.

| Metric | Agent | Adaptive |
|---|---:|---:|
| Overall correct | 4/6 | 4/6 |
| Complete-state correct | 6/6 | 6/6 |
| Output-semantic correct | 4/6 | 4/6 |
| Unsafe proposals / writes | 0 / 0 | 0 / 0 |
| Model calls | 23 | 15 |
| Tool calls / failures | 27 / 1 | 27 / 1 |
| Reported input + output tokens | 37,321 | 24,223 |
| Elapsed seconds | 66.49 | 46.47 |
| Workflow coverage | 0/6 | 2/6 |

The result demonstrates no accuracy gain. At 33.3% workflow coverage, the
adaptive arm used 8 fewer model calls and 13,098 fewer reported tokens, while
tool calls were unchanged. Two damage/billing responses mutated the exact
correct local state but exposed only internal English status values instead of
the predeclared user-facing semantic terms; both arms therefore failed output
and overall scoring on those cases. This is a shared product wording defect,
not a reason to rescore or retry. Each arm's one tool failure was the expected
safe lookup failure for the nonexistent-order case, which finished without a
write. The six synthetic cases are integration evidence only.

See `docs/PAIRED_AGENT_EVALUATION.md`. M13d should implement a typed
user-facing outcome contract and freeze a new broader holdout; it must not tune
or rerun M13c.

```text
$ PYTHONPATH=src .venv/bin/python -m unittest \
    tests.test_support_evaluation tests.test_support_router tests.test_support_agent -v
Ran 35 tests in 3.676s; OK

$ .venv/bin/ruff check src/trace2flow/support_evaluation.py \
    src/trace2flow/support_reference.py tests/test_support_evaluation.py
All checks passed!

$ PYTHONPATH=src .venv/bin/python -m trace2flow.support_evaluation evaluate ... \
    --allow-paid-call --unlock-evaluation
12/12 attempts retained; exit 0; no retry

$ PYTHONPATH=src PREFECT_SERVER_ALLOW_EPHEMERAL_MODE=true \
    .venv/bin/python -m unittest discover -s tests -v
Ran 177 tests in 23.469s; OK; no skips

$ .venv/bin/ruff check src/trace2flow tests streamlit_app.py scripts/capture_m12_demo.py
All checks passed!

$ .venv/bin/uv lock --check --offline
Resolved 202 packages; lock unchanged

$ .venv/bin/uv build --out-dir /tmp/trace2flow-m13c-build-final-v3
Successfully built sdist and wheel containing the M13c modules

$ git diff --exit-code dd36900 -- <five frozen M13c source files>
exit 0
```

## M13b adaptive router and trace adapter

Connected new standard-Agent recordings to the existing Trace2Flow pipeline
without modifying the frozen M11 experiment or automatically promoting any
observed pattern. No DeepSeek request, credential access, push, PR, merge or
external write was used in this milestone.

- Added `support_trace.py` with strict models for the saved session, turn,
  recording and individual calls. The adapter preserves raw JSON value types,
  repeated occurrences, final output and complete state. It rejects prompt hash
  tampering and duplicate call IDs.
- Unreviewed input is explicitly quarantined with
  `import_review_status=required`; dependencies and effects remain empty. A
  complete `SupportRecordingReview` is bound to the recording hash and must
  inventory dependencies, effects and alignment for every call. Reviewer kind
  is explicit. State-changing calls require a declared write, and only fully
  successful reviewed runs can enter the promotion merge helper.
- Added an append-only versioned registry. Workflow content, development
  verification and promotion review must share the recomputed SHA-256. The
  Workflow IR must have no blockers and match the exact five-tool delivery
  contract, reviewed bindings, evidence edges and ticket-update output. A
  duplicate version is rejected; multiple matching versions fall back rather
  than choosing silently.
- Added a conservative lexical route contract requiring exactly one explicit
  order ID plus clear delivery and delay language and no conflicting intent.
  Missing/multiple IDs, refund/billing/damage conflicts, unknown/foreign orders,
  preflight failure and unsupported work fall back to the standard Agent.
- Matched workflows first execute against a cloned backend. Live state remains
  unchanged until human approval. Approval reruns ownership, recent-order,
  shipping-date and policy evidence on current live state before the idempotent
  write; stale facts fail safely. Rejection does not mutate. Agent-fallback
  approvals resume through the same router API, and customer/ticket identity is
  immutable for each thread.
- Increased the internal LangGraph recursion allowance from 30 to 100 after a
  regression exposed that four sequential read calls plus middleware/checkpoint
  nodes could exhaust graph steps before approval. The actual safety budgets
  remain 8 model calls, 12 tools and one write attempt. No call budget was
  loosened.
- Added `docs/ADAPTIVE_ROUTER.md`, README/roadmap/development guidance and 12
  integration tests. The framework design continues to use the LangChain
  `create_agent`, middleware, checkpointer and `Command` resume boundaries from
  the selected ecosystem skills.

The offline integration fixture creates two fresh scripted LangChain Agent
runs (10 tool-call occurrences), reviews them explicitly, invokes the real
pinned upstream compiler and occurrence-aware candidate builder, and resolves a
five-node/four-edge Workflow IR. Its seven bindings are four declared constants
and three declared runtime-contract inputs; it has zero execution blockers.
On the paired accepted development case, the workflow used zero model calls,
paused for approval and produced a complete backend snapshot exactly equal to
the standard Agent baseline. This proves integration mechanics for one known
synthetic case, not accuracy, token reduction or generalization.

### Actual M13b verification

```text
$ .venv/bin/python -m unittest tests.test_support_router -v
Ran 12 tests in 2.267s; OK

$ PYTHONPATH=src PREFECT_SERVER_ALLOW_EPHEMERAL_MODE=true .venv/bin/python -m unittest discover -s tests -v
Ran 167 tests in 23.270s; OK; no skips

$ .venv/bin/ruff check src/trace2flow tests streamlit_app.py scripts/capture_m12_demo.py
All checks passed!

$ PYTHONPATH=src .venv/bin/python -m compileall -q src tests streamlit_app.py scripts
exit 0

$ .venv/bin/uv lock --check --offline
Resolved 202 packages; lock unchanged

$ .venv/bin/uv build --out-dir /tmp/trace2flow-m13b-build-final-v2
Successfully built sdist and wheel containing both M13b modules

$ git diff --exit-code b168d6760213b489e2fb2f5571f5d4e6d648dee8 -- src/compile.py src/benchmark.py src/codegen.py rules LICENSE
exit 0

$ git diff --exit-code de2f1d7 -- <M11 frozen code and artifacts>
exit 0
```

### Next milestone

M13c is next. Before any result is collected, freeze a new task-group inventory,
baseline/router configurations, route contracts, workflow registrations,
complete-state scorer and metrics. Then run the standard Agent and adaptive
router on identical fresh states, retaining every attempt. Human intervention
is required before any new paid DeepSeek corpus collection; it is not required
for drafting and validating the offline evaluation contract.

## M13a standard Agent baseline

Implemented a runnable DeepSeek customer-support Agent alongside, not inside,
the frozen Trace2Flow compiler/evaluation pipeline. It accepts ordinary user
language and authenticated runtime identity; its input has no scenario, oracle,
expected action, order ID or policy answer. Trace recording is passive and does
not determine the Agent's tool route.

- Added `support_backend.py`: fresh typed synthetic customers, orders, shipping,
  payment events, policies and tickets; customer-scoped reads, indistinguishable
  foreign/missing-order errors, typed/idempotent ticket writes and complete
  before/after snapshots. It has no network, real customer data, messaging,
  carrier or refund integration.
- Added `support_agent.py` using LangChain `create_agent`, typed tools and
  immutable runtime context. Seven allowlisted tools cover trusted context,
  recent/one-order lookup, shipping, payment events, policy and the sole local
  ticket write. `InMemorySaver` retains same-process follow-up turns.
- Added model/tool call limits, one write attempt per run, current-policy and
  fact gates, and human approve/reject interruption before state mutation.
  Authenticated customer/ticket IDs never appear in model-controlled tool
  schemas. Provider errors are reduced to exception types. A deterministic
  post-write response guard reports only the proven local effect and prevents
  model wording from promising nonexistent external follow-up.
- Added a versioned local recorder with prompt and producer hashes, model/tool
  events, typed arguments/results, provider-reported usage and complete state.
  Credentials, headers, provider payloads, reasoning and provider exception
  text are omitted; LangSmith cloud tracing is disabled.
- Added a fail-closed CLI: live calls require `--allow-paid-call`, local writes
  additionally require `--approve-local-write`, and trace paths are exclusive.
  Added direct optional dependencies for LangGraph and LangSmith and refreshed
  the lock file.
- Added `docs/STANDARD_AGENT.md`, roadmap/README/development guidance, and 14
  framework-level regression tests. The official LangChain agent, runtime,
  memory and human-in-the-loop patterns informed this baseline.

The paid development attempts exposed two real integration defects. Initially the model did
not know the backend's current date and could not reliably decide whether the
estimate was overdue. The fix added trusted current-date context and a backend
evidence check requiring the estimate to precede that date. A later attempt
still promised future follow-up that the local system cannot perform, despite a
prompt prohibition. The fix added the deterministic response guard and
regression assertions. Earlier attempts remain in ignored private storage;
they were not deleted or presented as evaluation. The final-source
`delivery-natural-v5` attempt:

- paused before the write, then completed only after explicit local approval;
- made 5 model requests and 5 successful tool calls: support context, recent
  orders, shipping, policy and ticket update;
- reported 8,027 input and 573 output tokens (8,600 total, including reported
  cache-read input); no relative reduction is claimed;
- changed only synthetic ticket `T-100` from revision 0/open to revision
  1/pending_carrier; `T-200` and `T-300` remained at revision 0;
- returned a guarded completion that explicitly says no external carrier was
  contacted, no refund started and no automatic notification exists;
- stored a producer hash exactly matching the final Agent source at run time.

This is one development integration attempt, not a benchmark, accuracy result,
generalization result or self-evolution claim. Final-chat quality is not yet
scored, and the CLI's in-memory approval cannot survive process restart.

### Actual M13a verification

```text
$ .venv/bin/python -m unittest tests.test_support_agent -v
Ran 14 tests in 1.592s; OK

$ PYTHONPATH=src PREFECT_SERVER_ALLOW_EPHEMERAL_MODE=true .venv/bin/python -m unittest discover -s tests -v
Ran 155 tests in 23.523s; OK; no skips

$ .venv/bin/ruff check src/trace2flow tests streamlit_app.py scripts/capture_m12_demo.py
All checks passed!

$ PYTHONPATH=src .venv/bin/python -m compileall -q src tests streamlit_app.py scripts
exit 0

$ .venv/bin/uv lock --check --offline
Resolved 202 packages; exit 0

$ .venv/bin/uv build --out-dir /tmp/trace2flow-m13-build-final-v2
Successfully built sdist and wheel containing both support modules

$ git diff --exit-code b168d6760213b489e2fb2f5571f5d4e6d648dee8 -- src/compile.py src/benchmark.py src/codegen.py rules LICENSE
exit 0

$ git diff --exit-code de2f1d7 -- <M11 frozen code and artifacts>
exit 0

$ git diff --check
exit 0
```

The final authorized call used the existing environment variable without
reading or printing its value. Full recordings remain under ignored
`data-private/standard-agent-dev/`; they are neither committed nor used as a
test set. No push, PR, merge, hosted trace or real external write occurred.

### Next milestone

M13b will adapt eligible new recordings into Trace2Flow and add a conservative
versioned router: only reviewed, fully resolved cases may choose a verified
workflow, while ambiguity and unsupported cases fall back to this Agent. M13c
will freeze a new disjoint paired evaluation before measuring accuracy, unsafe
writes, failures, calls, provider-reported tokens, latency and workflow
coverage. No human intervention is required to start the offline M13b
implementation; explicit approval will be required before any new paid corpus
collection or publication.

## M12 completed demo handoff

Implemented the existing Streamlit demo's public-only, offline DeepSeek mode;
kept the original synthetic/tau upload/compile/verification mode selectable.
No model requests, key/environment reads, pushes, PRs or merges. Private local
recordings were read only to extract/check the four public task/tool projections;
the demo and its automated regressions never open private recording files.

- Added tested `live_demo.py` archive helpers and `live_demo_ui.py` rendering.
  Default story: historical recording, occurrence DAG and declared bindings,
  fresh isolated execution with complete-state field diff, failures and limits.
- Published four **lossy original task/tool projections**, not complete raw
  messages or normalized traces: compile-01, test-01, repeated-failure
  compile-10 and zero-call test-11. They retain exact run/call IDs, types,
  results, failure types and original private-file hashes. Chat/prompt/state
  snapshots/credentials/provider payloads are omitted. Public demo never
  opens private raw files and works without them.
- Added `demo-index.json` byte-integrity inventory plus frozen plan, pipeline,
  workflow/source/scorer, report inventory and safe Prefect-export checks.
  Stop displaying scores if archive or pipeline identities differ. The new
  index is a post-experiment UI integrity index, not a pre-test freeze or
  provider-authenticity attestation. Four display selections do not filter the
  full historical thirty-task evaluation denominator.
- Exposed all fifteen AI-declared parameter bindings and occurrence evidence
  for the five-node/three-edge DAG. Fixed a presentation-only DOT newline escape
  so node alignment labels render as a second line, with a regression assertion.
  No upstream/compiler/IR/mining/scoring change.
- All twelve known test tasks can execute in new local states. Explicit
  existence/ownership admission is unchanged. Compare actual business output
  and all customers/orders/tickets with the independently declared oracle;
  display actual state changes and retain failures. Returned state cannot
  contaminate the next run. These are known-fixture regressions, not new
  model/holdout results; archived reports remain unchanged.
- Kept coverage **8/12 (66.7%)**, accepted correctness **8/8**, four safe
  refusals, and matched model requests **40 → 0** separate. Tools **40 → 40**;
  no tool reduction, cost benefit, chat quality, generalization or self-evolution
  claim. AI-reviewed contract / synthetic business labels remain prominent.
- Added 19 helper/UI tests: privacy/offline behavior, checksum/core identity,
  typed loss labels, distinct repeated failures, zero-call preservation,
  occurrence evidence, isolated output/full-state checks, refusal, corruption,
  exception-text omission, unknown tools and real Streamlit widget interactions.
  Existing six demo tests still run their original pipeline assertions by
  explicitly selecting the retained legacy source; no assertion was lowered.
- Added Chinese three-minute walkthrough and seven real Chromium screenshots
  in `docs/LIVE_DEMO_WALKTHROUGH.md`. Optional local-only capture script checks
  five DAG nodes/three edges, actual execution, refusal, failure and zero-call.
  Screenshot tools were installed only in `/tmp/trace2flow-m12-browser`, not
  project dependencies. Initial capture preceded async graph/table rendering;
  fixed waits for actual SVG/grids/skeleton completion and regenerated images.

### Actual M12 verification

```text
$ .venv/bin/python -m unittest discover -s tests -p test_live_demo.py -v
Ran 19 tests in 2.149s; OK

$ .venv/bin/python -m unittest discover -s tests -p test_demo.py -v
Ran 6 tests in 1.629s; OK (final, including DOT newline assertion)

$ PYTHONPATH=src PREFECT_SERVER_ALLOW_EPHEMERAL_MODE=true .venv/bin/python -m unittest discover -s tests -v
Ran 141 tests in 19.354s; OK; no skips (final, after presentation fix)

$ .venv/bin/ruff check src/trace2flow tests streamlit_app.py scripts/capture_m12_demo.py
All checks passed!

$ PYTHONPATH=src .venv/bin/python -m compileall -q src tests streamlit_app.py scripts
exit 0

$ uv lock --check --offline
Resolved 202 packages; exit 0 (lock unchanged)

$ uv build --out-dir /tmp/trace2flow-m12-build
Successfully built sdist and wheel containing both new live-demo modules

$ /tmp/trace2flow-m12-browser/bin/python scripts/capture_m12_demo.py
7 screenshots; successful update, safe refusal, failures and zero-call checked

$ git diff --exit-code b168d6760213b489e2fb2f5571f5d4e6d648dee8 -- src/compile.py src/benchmark.py src/codegen.py rules LICENSE
exit 0

$ git diff --exit-code a35049e -- src/trace2flow/{agent_corpus,agent_collect,agent_review,agent_evaluation,agent_build,candidate,ir,runtime,simulation,agent_contract_review,agent_report,agent_final_freeze}.py examples/customer-support-agent/live-v1/artifacts examples/customer-support-agent/live-v1/{final-freeze,review-plan,compile-report,development-report,test-report}.json
exit 0

$ git diff --exit-code -- uv.lock pyproject.toml
exit 0

$ git diff --check
exit 0
```

Initial lint found an unused test import and nested context manager; fixed the
test syntax without weakening assertions. Existing offline suite includes real
temporary local Prefect execution. No new paid collection or hosted CI was run.
The screenshot script blocks off-machine resource requests. See the walkthrough
for the exact tested Streamlit server command and screenshot reproduction.

### Next step and human intervention

No human intervention was needed for M12's local simulated implementation.
The next step is release handoff: review the Chinese script, rehearse a short
recording, then explicitly authorize publication if wanted. Push / PR / merge /
release tag are not authorized by this milestone. Hosted CI remains unrun for
these local commits. More algorithm tuning is not required for M12; future
business-policy/generalization work needs separately declared data and holdout.
The frozen upstream/mining/IR/scorer boundary remains intact.

## M11b completed experiment

Completed the entire predeclared thirty-task local-model experiment with the
user's existing DeepSeek credential. Only variable availability was checked;
no `.bashrc`, `.env`, key value, request headers or provider exception text was
read/output. Continued the existing LangChain `create_agent` + middleware
pattern under the selected skills, not a new Agent/LangGraph framework. No
push, PR, merge or hosted-CI run was performed.

- Collected compile 10, development 8 and test 12 **once each**, with all raw
  recordings in ignored `data-private/agent-corpus-v1/`. Preserved repeated
  failed reads and the zero-call raw-only `test-11`; no invented trace steps.
- AI inspected each compile occurrence/typed argument/result. The exact-ID
  review plan covers all ten tasks: nine included, one foreign-order run
  excluded from compilation only, retained in scoring with both failed reads.
  Explicit future execution contract: six task inputs, nine tool-output paths,
  zero constants. No human review or automatic model-lineage discovery is
  claimed. AI reasoning effort is unmeasured; machine check time is labeled as
  machine time (included compile records only), not human/AI reading effort.
- Actual upstream-backed mining produced five nodes and three declared evidence
  edges. Customer/order queries have no invented dependency. Frozen IR has no
  execution blockers. Upstream core/rules/license remain unchanged.
- Saved pre-test source checkpoint `81acf50`, then froze exact plan, selected
  pipeline sources, review population/plan, workflow/compile and report source.
  No test model result had been collected or inspected at that point. Sources,
  declarations and scorer stayed unchanged after test inspection (`git diff`
  against the checkpoint exited 0 for all those paths).
- Executed frozen workflow against fresh local state, not recorded responses;
  compared business output and the entire customers/orders/tickets snapshot.
  Added independently checked call/timing measurements and archived normalized
  compile data/candidate/resolution/IR/fixed Prefect target plus all three
  complete reports and pre-test freeze. Raw provider recordings remain private.
- Added eight contract/report unit tests and three archive integrity/regression
  tests. Initial archive-test import used a nonexistent convenience loader;
  corrected it to Pydantic parsing. No scoring code or assertions were weakened.

### Actual results and limitations

| Partition | Planned / recorded | Correct output or safe outcome | Model requests | Tool calls / failed |
| --- | --- | --- | --- | --- |
| Compile | 10 / 10 | 10 | 48 | 48 / 2 |
| Development | 8 / 8 | 8 | 29 | 27 / 5 |
| Frozen test | 12 / 12 | 12 | 48 | 45 / 3 |

Test outcomes are **8 correct updates + 4 safe unchanged outcomes**, not twelve
successful update runs. All three reports have zero pending cases. Test unsafe
write attempts: zero. Final customer-facing chat quality and all instruction-
following aspects are unmeasured; a blocked invalid read is still a failed call
even when its safe business outcome matches.

Workflow test admission: **8/12 (66.7% coverage)**; accepted output/full-state
correctness 8/8; four safely refused; unsafe acceptances zero. Admission is an
explicit customer/order existence/ownership guard, not automatically compiled
branch logic. On the same eight accepted tasks: Agent model calls 40 versus
workflow 0; **both execute 40 tool calls**, so no tool-call reduction is claimed.
The extra local measurement pass also matches all expected outputs/states.

All thirty live attempts report 155,992 input and 13,597 output tokens (complete
provider usage), 125 requests, 120 tool calls and ten failed calls. No money or
cost benefit was estimated. Descriptive accepted-test median elapsed times are
13.0929277184 seconds for Agent collection and 0.0000969685 seconds for local
workflow execution. Timer scopes differ and these must not be advertised as a
production acceleration factor.

Actual generated Prefect flow ran `test-01` on a real temporary local server:
five nodes Completed, output and full-state assertions passed. Generated source
SHA: `a10bfac7ad3a2566ba5cb2541587c275212df945c97f09431d72c56427cd2278`.
The command is reproduced in `examples/customer-support-agent/live-v1/SOURCE.md`.

This is **recorded model orchestration in synthetic business state** with
deterministic classification/recommendation, AI-declared binding contracts and
one attempt per task. It is not real-customer evidence, a general success-rate
estimate, automatic workflow policy discovery or self-evolution. Public hashes
and operator confirmation do not attest provider authenticity or access control.
Without private raw records, others can reproduce workflow/state verification,
not verify historical provider requests. These tasks are now known regression
fixtures; future tuning requires a newly declared untouched holdout.

### Actual validation

```text
$ .venv/bin/python -m unittest discover -s tests -p test_agent_report.py -v
Ran 8 tests in 0.482s; OK (before final freeze)

$ PYTHONPATH=src PREFECT_SERVER_ALLOW_EPHEMERAL_MODE=true .venv/bin/python -m unittest discover -s tests -v
Ran 119 tests in 16.831s; OK (before test model collection)
Ran 122 tests in 17.312s; OK (final, no skips)

$ .venv/bin/python -m unittest discover -s tests -p test_agent_live_artifacts.py -v
Ran 3 tests in 0.035s; OK

$ .venv/bin/python -m trace2flow validate examples/customer-support-agent/live-v1/artifacts/compile.json
valid=true, partition=compile, runs=9, steps=45

$ .venv/bin/python -m trace2flow.agent_report examples/customer-support-agent/corpus-plan.json data-private/agent-corpus-v1/test --partition test --unlock-test --manifest examples/customer-support-agent/live-v1/final-freeze.json --workflow examples/customer-support-agent/live-v1/artifacts/workflow.json --compile examples/customer-support-agent/live-v1/artifacts/compile.json --output examples/customer-support-agent/live-v1/test-report.json
planned=12, evaluated=12, correct=12, score_final=true

$ .venv/bin/ruff check src/trace2flow tests streamlit_app.py
All checks passed!

$ PYTHONPATH=src .venv/bin/python -m compileall -q src tests streamlit_app.py examples/customer-support-agent/live-v1/artifacts/prefect_flow.py
exit 0

$ uv lock --check --offline
Resolved 202 packages

$ uv build --out-dir /tmp/trace2flow-m11b-build.AiiDYT
Successfully built sdist and wheel including the three new M11b modules

$ git diff --exit-code b168d6760213b489e2fb2f5571f5d4e6d648dee8 -- src/compile.py src/benchmark.py src/codegen.py rules LICENSE
exit 0
```

Collection used the case CLI in `docs/AGENT_EXPERIMENT.md` with every exact
predeclared ID, original baseline manifest for compile/development and final
`report-freeze.json` for test. There was no hidden retry or dropped directory.
Validation in the automated suite is offline, not another paid evaluation.
Streamlit bare-mode warnings/temporary Prefect server logs are expected.

### Next milestone

No human intervention is needed for the completed simulated experiment. Unknown
future business policy/lineage/effects still require declarations or approval;
these results do not authorize guessing. M12 should expose this actual recorded
evidence, review labels, DAG/bindings and complete-state result in the existing
lightweight demo with a Chinese walkthrough. Do not introduce a new frontend,
real customer integration or self-evolution loop. Publication still requires
explicit user direction.

## M11b pre-test source checkpoint

Working branch: `feat/m11-live-evaluation`. Current inherited environment has
`DEEPSEEK_API_KEY`; only presence was checked. The user authorized proceeding
with live DeepSeek evaluation. No `.bashrc`, `.env` or credential value was read.

Collected all 10 compile and 8 development cases once using the frozen M11a
plan/prompt/pipeline. Nine complete compile runs are AI-reviewed using exact
occurrence IDs and an explicit execution contract. The foreign-order run retains
both failed order occurrences and is excluded only from compilation. No human
review is claimed. Policy version binds to the task input; no historical value
is promoted to a constant. Manual AI effort is unmeasured, machine checks are
timed separately. Added an exhaustive checked contract intake, source-pinned
final freeze, usage/call/timing report and eight offline tests.

Actual pre-test observations: compile safety/output/state 10/10; development
8/8. Workflow independently admits and correctly executes 4/8 development tasks,
safely refuses 4/8, with zero unsafe acceptances. Four accepted development tasks
have 20 Agent model calls versus zero workflow model calls; both execute 20 tool
calls. These are descriptive controlled-simulator facts, not cost or production
speedup claims. No test model run or result inspection has occurred at this
source checkpoint. Next: freeze the final workflow and report code, then run
each of the twelve test tasks once without tuning. No push/PR/merge.

## M11a update

Implemented the next testable engineering baseline, not a fabricated empirical
result. No paid calls were made in this iteration, no new model-test results
were collected or inspected, and no credentials or `.env` files were read.
No push, PR or merge was performed. Upstream core, rules and MIT license remain
byte-for-byte unchanged from the audited baseline.

- Added a committed 30-task synthetic plan: compile 10, development 8, test 12.
  Freeze and validate complete groups, entity identities, typed input/state and
  explicit independent business expectations. The Agent receives only inputs;
  expected answers, scenario labels and state snapshots are not model context.
- Allow an isolated case simulator to be injected into the existing collector,
  preserving its framework loop, guards, typed recording and zero-call policy.
  Record task-group and plan/case context without treating it as model input.
- Added source/plan/prompt freeze and final workflow/compile artifact pinning.
  The local manifest is a logical seal, not access control or authenticity
  attestation, and does not claim it can detect prior human test inspection.
- Added deliberately unapproved review drafts and exhaustive checked review
  intake: every occurrence and parameter, typed sources, preceding edges,
  registered effects, reviewer/effort/rationale and hashes. Incomplete or failed
  recordings stay out of executable mining but remain evaluation cases.
- Added `agent_build`: combine only one reviewed compile role/plan, call the
  real upstream-backed miner, translate only agreeing declarations and preserve
  conflicts as IR blockers. Save source, candidate, resolution and Workflow IR.
- Added planned-task Agent scoring and fresh-state workflow scoring. Pending,
  failed and zero-call runs are not dropped; repeat trials must be predeclared.
  Compare final business output and all customer/order/ticket state. Report
  coverage, accepted correctness and unsafe attempts/acceptances separately.
  Customer/order admission is explicitly declared, not a synthesized branch;
  final-chat quality remains unmeasured.
- Added 20 offline tests and `docs/AGENT_EVALUATION.md`. Skills used for this
  extension preserve the existing LangChain Agent loop and middleware-based
  guard boundary; no parallel Agent architecture or new framework was built.

### Actual validation (final implementation)

```text
$ PYTHONPATH=src PREFECT_SERVER_ALLOW_EPHEMERAL_MODE=true .venv/bin/python -m unittest discover -s tests -v
Ran 111 tests in 17.493s
OK (no skips, no paid calls)

$ .venv/bin/python -m unittest discover -s tests -p test_agent_corpus.py -v
Ran 20 tests in 0.422s
OK

$ .venv/bin/ruff check src/trace2flow tests streamlit_app.py
All checks passed!

$ PYTHONPATH=src .venv/bin/python -m compileall -q src tests streamlit_app.py
exit 0

$ uv lock --check --offline
Resolved 202 packages

$ uv build --out-dir /tmp/trace2flow-m11-build.X5kecW
Successfully built sdist and wheel, including all four new M11 modules

$ .venv/bin/python -m trace2flow.agent_corpus examples/customer-support-agent/corpus-plan.json
{"compile": 10, "development": 8, "test": 12}

$ .venv/bin/python -m trace2flow.agent_corpus examples/customer-support-agent/corpus-plan.json --freeze data-private/agent-corpus-v1-freeze
exit 0: 30 tasks, 9 selected source hashes, logical-only test seal
plan SHA-256: 801f17d3eb5d3cad7295de86cae0c40b9723fdaf1812e257df18da9510d46225

$ .venv/bin/python -m trace2flow.agent_evaluation examples/customer-support-agent/corpus-plan.json data-private/agent-corpus-v1/development --partition development --manifest data-private/agent-corpus-v1-freeze/manifest.json
planned=8, evaluated=0, pending=8, score_final=false

$ git diff --exit-code b168d6760213b489e2fb2f5571f5d4e6d648dee8 -- src/compile.py src/benchmark.py src/codegen.py rules LICENSE
exit 0
```

The offline integration creates three explicitly scripted compile recordings,
uses actual Clingo mining and checked declarations, and independently executes
the resulting five-node workflow on eight development fixtures: four admitted
and correct, four safely refused, zero unsafe acceptances, coverage 4/8. This
is a controlled regression result, not a DeepSeek success rate or holdout claim.
The empty live inventory deliberately has no final score. Streamlit bare-mode
warnings and a temporary local Prefect server during existing tests are
expected; all assertions passed. `uv` uses the absolute path noted under M10.

### Remaining work / next milestone (M11b)

No engineering blocker was encountered. Full empirical M11 acceptance is not
complete: collect all compile/development DeepSeek cases once, review actual
occurrences and record honest reviewer effort, resolve only justified bindings
and effects, then freeze a final workflow/source before unlocking all 12 test
cases. Any ambiguous business binding requires reviewer clarification; do not
invent a human approval or infer lineage just to finish. Report all failures and
unsupported structures. The corpus remains simulated business evidence, not
real customer-system traces. No publication is authorized by this implementation
request; hosted CI for this branch has not run.

## M10 update

The user selected DeepSeek and authorized model spend for the small producer
extension. Only presence of `DEEPSEEK_API_KEY` was checked; its value was never
printed. No `.env` or credential file was read. No push/PR/merge was performed.

- Added optional locked `agent` dependencies: LangChain 1.4.0, core 1.6.3,
  DeepSeek integration 1.1.0. Installed a fresh isolated `.venv`; upstream
  dependencies and compiler sources remain preserved.
- Added `agent_collect`: actual `create_agent` loop with five fixed local
  simulator tools, task/ownership/fact/policy/write guards, strict local JSON
  parameter types, bounded calls, sanitized errors and no automatic retries.
- Default DeepSeek V4 Pro uses non-thinking mode and the standard official
  endpoint, not beta native strict mode. The model alias is explicitly unpinned.
  LangSmith cloud tracing is disabled, including inherited tracing settings.
- Save raw task/prompt/producer hash/model events/call IDs/typed arguments and
  results/usage/ending/full state to new ignored local directories. Capture
  failures and partial runs. Zero-call runs are raw-only, never fabricated.
- Preserve read-batch requests while serially dispatching only audited
  independent customer/order queries. Compute/write/unknown batches stop.
  Keep repeated occurrences distinct and do not infer dependencies from order.
- Normalized traces are quarantined until explicit review. Added a fixed
  development-pilot checker, content/state corruption tests and two committed
  synthetic input tasks without Agent-visible expected answers.
- Added 18 offline tests and collector documentation. CI installs the optional
  Agent dependencies, but no paid call is part of the automated suite. Hosted
  M10 CI has not run because this branch has not been pushed.

### Actual DeepSeek development pilot

Five recordings remain under ignored `data-private/agent-pilot/`:

| Recording | Observed ending | Model requests | Dispatched tool calls |
|---|---|---:|---:|
| m10-delivery-001 (prompt v1.0) | stopped read batch | 1 | 0 |
| m10-delivery-002 (prompt v1.1) | stopped read batch | 1 | 0 |
| m10-foreign-001 (prompt v1.1) | stopped read batch | 1 | 0 |
| m10-delivery-003 (prompt v1.2) | model finished, correct ticket update | 5 | 5 |
| m10-foreign-002 (prompt v1.2) | model finished, failed foreign-order lookup, no write | 3 | 3 |

Initial attempts exposed the overly restrictive single-call interface. Adding
only a prompt instruction did not fix it. The minimal code extension allows
audited independent read batches, preserves their original grouping, and does
not invent data edges. Tests retain strict-mode batch rejection and additionally
verify allowed read batches and rejected mixed write batches.

The final delivery output exactly matches `carrier_investigation` and
`pending_carrier`; the complete customer/order/ticket state matches independently
fixed expectations, including an unchanged unrelated ticket. The final
foreign-order run has no successful update and its entire state is unchanged.
Its normalized run is partial, not business-successful. All three initial
stops have no tool dispatch and unchanged state. Checker assertions passing for
stops are safety observations, not successful task executions.

Available usage across all five attempts: 11 model requests, 12,680 input
tokens and 1,271 output tokens. No paid run was discarded. This is development
evidence, not a holdout rate, cost-savings measurement, customer-data claim or
general automatic workflow discovery. Model final-chat claim correctness is
not scored. Business classification and recommendations remain deterministic
existing simulator rules; raw recordings still require dependency/binding
review. Frozen corpus collection and independent evaluation are M11.

Raw SHA-256 inventory (no raw recordings are committed):

```text
m10-delivery-001 215b14d5c3db8db62d1bd9d6db628e20d8a6674fcdb480e14fdfd782ef6f992e
m10-delivery-002 ec29324984968a5c350b3d84521e6bdf983aa4342aa463a2cd69150e14c610ac
m10-foreign-001  7ed565a09fb6cab283a3498b06e3e7cef0ab509abb7be375c6195617db220df0
m10-delivery-003 2410f71630f111a2b53bf1fcb74e43a99383bbb9965ccfc073a251291e7a25c0
m10-foreign-002  eb71a4fb9128ca0f1bcc166f25e088c7664799e85b10e5305266d01c1ac5436e
```

### Actual validation

```text
$ uv sync --locked --extra agent --group dev
Resolved 202 packages; installed isolated locked environment

$ PYTHONPATH=src PREFECT_SERVER_ALLOW_EPHEMERAL_MODE=true .venv/bin/python -m unittest discover -s tests -v
Ran 91 tests in 16.106s
OK (no skips)

$ .venv/bin/ruff check src/trace2flow tests streamlit_app.py
All checks passed!

$ PYTHONPATH=src .venv/bin/python -m compileall -q src tests streamlit_app.py
exit 0

$ uv lock --check --offline
Resolved 202 packages

$ uv build --out-dir /tmp/trace2flow-m10-build.TCNp1Q
Successfully built sdist and wheel, including both producer modules

$ .venv/bin/python -m trace2flow.agent_pilot data-private/agent-pilot
passed=true; scope=fixed_development_pilot_not_holdout

$ .venv/bin/python -m trace2flow validate data-private/agent-pilot/m10-delivery-003/normalized.quarantine.json
valid=true; runs=1; steps=5

$ .venv/bin/python -m trace2flow mine data-private/agent-pilot/m10-delivery-003/normalized.quarantine.json --output /tmp/trace2flow-m10-quarantine-candidate.json
exit 2 (expected): complete import review required

$ git diff --exit-code b168d6760213b489e2fb2f5571f5d4e6d648dee8 -- src/compile.py src/benchmark.py src/codegen.py rules LICENSE
exit 0: audited upstream core and MIT license unchanged
```

`uv` was invoked at `/media/E/dodo/conda_envs/trace2flow-m0/bin/uv` because it
was not on the current shell PATH. The shell's default Python was not used for
tests. Live invocations used the command in `docs/AGENT_COLLECTOR.md` with the
five new output directories listed above. Streamlit bare-mode warnings during
tests are expected; all assertions passed.

## M9 update

M9 turns the M8 recorded structure into an honestly bounded executable
workflow and completes the scoped MVP:

- Added `declared_runtime_contract` evidence for typed task-input paths that
  were not structured fields in the recorded natural-language inputs. All nine
  retail parameters use this explicit mode; none is promoted to a constant.
- Added declared `output_node_ids`. The order-modification node is the business
  result while the independent authentication read remains a structural sink;
  no false data-dependency edge was invented to force a single sink.
- Added four allowlisted in-memory retail tools and two fresh local cases with
  entities and state unrelated to the recorded corpus. Recorded responses are
  never replayed. The verifier compares the selected business output and the
  complete mutable order map.
- Added `trace2flow verify-retail`, real Prefect execution coverage, separate
  output/state corruption tests, a three-level evidence display in Streamlit,
  a portfolio walkthrough, and locked clean-install GitHub Actions CI.

Actual recorded-derived execution result:

```text
workflow: 4 nodes, 3 evidence edges, 9 task-input bindings, 0 constants
execution blockers: 0
declared business output: modify_pending_order_items node
Prefect required tools: 4 registered local tools
fresh local cases: 2/2 passed
final output matches: 2/2
complete order-state matches: 2/2
recorded response replay used: false
validation scope: independent_local_simulation_of_recorded_structure
```

The executable contract requires the caller to supply `product_id`, original
`item_ids`, and selected `new_item_ids`. The source traces do not justify a
general natural-language product-selection policy, so that Agent decision was
not silently synthesized.

Full validation results:

```text
$ PYTHONPATH=src PREFECT_SERVER_ALLOW_EPHEMERAL_MODE=true python -m unittest discover -s tests -v
Ran 73 tests in 16.332s
OK

$ ruff check src/trace2flow tests streamlit_app.py
All checks passed!

$ PYTHONPATH=src python -m compileall -q src tests streamlit_app.py
completed with exit code 0

$ uv lock --check --offline
Resolved 180 packages

$ uv build --out-dir /tmp/trace2flow-build.*
Successfully built sdist and wheel; the wheel includes the trace2flow CLI entry point
```

The GitHub Actions workflow is committed locally but cannot have a hosted run
until the branch is pushed. Pushing remains intentionally outside the current
authorization.

## M8 update

M8 adds the first checked-in non-hand-authored trace corpus and a disjoint,
claim-limited evaluation path:

- Selected the narrow tau retail family “modify one item in a pending order.”
  Compile contains three successful recorded trials from source task 44; test
  contains four successful trials from task 60. The simulated customers,
  orders, and products differ across the boundary.
- Rejected task 61 despite its distinct task ID because it reuses task 60's
  customer/order/product entities. Excluded task 44 trial 2 because its extra
  `calculate` call falls outside the selected exact structure. Every inclusion
  and exclusion is recorded in `examples/tau-retail-recorded/selection.json`.
- Explicitly reviewed all 28 call occurrences for redaction, data dependency,
  side effect, and alignment. Authentication and order lookup remain separate
  roots: required policy order is not mislabeled as data lineage.
- Added `structure-evaluation/1.0` and `trace2flow evaluate-structure`. It
  verifies candidate source identity, compile/test group disjointness,
  occurrence alignment, candidate node coverage, accepted-edge support, and
  unseen held-out dependencies. The report always sets
  `execution_equivalence_claimed=false`.
- Added deterministic corpus reproduction, redaction, provenance, selection,
  and negative unseen-tool tests.

Actual recorded-corpus result:

```text
source results SHA-256: 6d6badb43b716adca31591b0b40e15fd493b49adddaa8e2c47035bb557549257
source producing commit: ade39493be54aad326a4c65295f77fe09780329b
compile: task group 44, 3 runs, 12 calls
test: task group 60, 4 runs, 16 calls
candidate: 4 aligned nodes, 3 edges, 0 unresolved dependencies
edge evidence: 3 compile occurrences for each edge
held-out structure: 4/4 runs covered
validation scope: held_out_structure_only
execution equivalence claimed: false
```

The audited upstream compiler classified the same four tools as core but put
all of them in phase 0 because these imported calls have no `spawned_by`
hierarchy. Trace2Flow's three data edges come only from reviewed occurrence
dependencies; this is a concrete observed difference between upstream
tool-level mining and the new evidence DAG.

Full validation results:

```text
$ PYTHONPATH=src python -m unittest discover -s tests -v
Ran 64 tests in 14.201s
OK

$ ruff check src/trace2flow tests streamlit_app.py
All checks passed!

$ PYTHONPATH=src python -m compileall -q src tests streamlit_app.py
completed with exit code 0

$ uv lock --check --offline
Resolved 179 packages in 2ms
```

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
