# Public dataset expansion protocol

Trace2Flow now has a reproducible path from the full public τ³ retail task
inventory to future Agent recordings. The important distinction is:

```text
public task + reference oracle
             │ run Agent in official simulator
             ▼
actual conversation/tool trajectory
             │ conservative tau importer + occurrence review
             ▼
normalized Trace2Flow run
```

The 114 task specifications expand scenario coverage; they do not themselves
expand the trace corpus. Only observed tool calls from completed simulator runs
may enter `trace2flow.tau_import`, and imports stay quarantined until their
dependencies and side effects are reviewed.

## Frozen inventory

The source revision and five source-file hashes are checked before an inventory
can be built. The official split contributes 74 train tasks and a sealed
40-task test set. Test IDs are public because they are part of the upstream
split, but Trace2Flow's manifest deliberately omits their content and oracle.

The 74 train tasks are separated into:

- 48 compile tasks for future trace collection and workflow mining;
- 26 development tasks for integration checks, prompt/policy fixes and
  admission design;
- 35 entity-connected groups, none crossing compile/development.

Because task 105 was already observed during provider integration, its complete
19-task shared-entity group is forcibly development-only before the split is
materialized. This explicit pre-exposure rule takes precedence over hash-based
assignment and prevents the pilot from contaminating compile data.

These are planning roles, not successful run counts. A future collection must
retain every declared attempt, including infrastructure failures, tool
failures, no-write results and zero-call conversations.

## First integration result

One development task was attempted three times while integrating the current
DeepSeek endpoint. The first two attempts are retained as infrastructure
failures. The third was evaluable and failed the task (`reward=0.0`) despite a
correct unchanged DB state. It used 10 Agent model messages with usage, 8 tool
calls, and 74,471 reported Agent prompt/output tokens combined. This high count
includes the growing τ³ Agent context; user-simulator and evaluator consumption
must be reported separately and must not be mislabeled as Agent tokens.

The result means the dataset path works, while the current external baseline is
not yet suitable for a resume accuracy claim. Before paid expansion:

1. enforce the retail one-tool-call-at-a-time policy in the Agent integration;
2. make the evaluator model/provider explicit without patching upstream files;
3. predeclare a small development batch spanning write/no-write families;
4. retain all attempts and validate the current τ³ result format through the
   existing conservative importer;
5. only after fixing the experiment contract, freeze a new test evaluation and
   open the 40 official test tasks once.

The M14b development contract is now frozen in
`examples/tau3-retail-v1/development-plan.json`. The runner registers a local
τ³ Agent adapter without changing upstream files, requests provider-side
`parallel_tool_calls=false`, and independently fails a task if the model still
proposes more than one assistant tool call. It never truncates a batch into a
different trajectory. Paid execution needs `--allow-paid-call`, a new output
name and the pinned source checkout. Agent, simulated-user and NL-evaluator
token usage are collected separately where the provider returns metadata.

## M14b result

The six planned attempts completed exactly once and were all retained. Four
ended as official `agent_error` results after DeepSeek returned both text and a
single tool call in one assistant message. Two ended at the Trace2Flow
single-call guard after proposing multiple tools. Therefore:

- retained: 6/6;
- evaluated by τ³'s premature-termination reward path: 4;
- successful: 0;
- mean available reward: 0.0;
- protocol/policy violations: 6/6;
- NL-evaluator calls: 0;
- reported Agent usage: 71,091 prompt + 1,440 completion tokens;
- reported user-simulator usage: 4,995 prompt + 1,356 completion tokens.

The upstream cost display showed zero only because LiteLLM lacks the model
price mapping; `development-report.json` correctly labels monetary cost as not
computed. This batch fails the gate for opening the official test. A second
development contract may tune only the provider/protocol adapter and must use
previously untouched development tasks; these six outcomes cannot be retried.

The final compatibility plan is `development-plan-v2.json`. Its six tasks are
disjoint from all seven previously attempted task IDs. The plan binds the exact
runner source hash and predecessor report hash, so changing the prompt or
publication logic after seeing results fails verification. The official test
may be opened only if at least four of six tasks succeed with zero mixed-message
or multi-tool policy violations.

## Final compatibility result

The second six-task batch also retained every attempt exactly once:

- successful: 1/6;
- evaluated: 5/6;
- mean available reward: 0.2;
- protocol/policy violations: 5/6;
- termination: one normal user stop, four Agent errors, one guarded
  infrastructure error;
- reported Agent usage: 158,235 prompt + 4,913 completion tokens;
- reported user-simulator usage: 7,310 prompt + 1,892 completion tokens;
- reported NL-evaluator usage: one call, 4,456 prompt + 205 completion tokens.

The successful run completed the expected local write and received DB=1 and
NL=1. It is still only one development case. The test-open gate required at
least four successes and zero policy violations, so it failed decisively. No
official test task was executed. M14 is therefore complete as a reproducible
negative compatibility result, not as a benchmark improvement claim.

Across both frozen six-task batches, tasks were never retried or selected by
outcome. The existing importer accepted the five M14c results containing calls
as 18 distinct occurrences (one completed and four failed runs), all still
quarantined with review required and empty inferred dependencies. The no-call
guard failure remains represented in the public inventory rather than being
converted into a fake trace.

## Claims allowed now

It is accurate to say the project audits and partitions all 114 public τ³
retail tasks, seals 40 test oracles, retains all 15 provider-integration and
development attempts, and records one successful official development task.
It is also accurate to say a predeclared compatibility gate failed and the
official test was deliberately not opened. It is not accurate to claim a τ³
test success rate, cost saving, production generalization, or benefit from
Trace2Flow on this dataset.
