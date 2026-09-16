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

## Claims allowed now

It is accurate to say the project audits and partitions all 114 public τ³
retail tasks, seals 40 test oracles, and has run one valid DeepSeek development
simulation through the official environment. It is not accurate to claim a
τ³ success rate, cost saving, production generalization, or benefit from
Trace2Flow on this dataset yet.
