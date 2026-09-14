# Recorded Trace Data Guide

Trace2Flow does not describe public benchmark records as production customer
data. The supported M7 source is a **recorded agent execution in a public
benchmark simulator**: the interaction really ran, while the customer,
orders, tools, and environment are simulated.

## Audited source

The adapter targets the text `results.json` format from
[`sierra-research/tau2-bench`](https://github.com/sierra-research/tau2-bench),
whose current project name is tau3-bench. The repository provides a retail
policy, registered tools, tasks, and recorded simulations under the MIT
license.

M7 inspected repository commit
`2174a603f6d014ef94473ffa95957f6ce27100db`. The checked historical retail
result embeds its own producing revision
`ade39493be54aad326a4c65295f77fe09780329b`; the importer records the embedded
revision because it identifies the actual run artifact.

Do not use the old `sierra-research/tau-bench` repository as the primary
source. Its own README marks those retail and airline tasks as outdated.

## Why import starts in quarantine

Tau text results contain typed tool arguments and occurrence IDs, but observed
tool results are serialized in message strings. They do not contain complete
before/after database snapshots, and their message order is not evidence of a
data dependency.

Consequently an unreviewed import:

- preserves tool result content as a string after redaction;
- leaves every `depends_on` and `side_effects` list empty;
- records that state snapshots are unavailable;
- drops provider payloads, prompts, timestamps, token/cost fields, and audio;
- applies deterministic, type-preserving pseudonyms to structured identity
  fields and replaces those values in free text; and
- sets `metadata.import_review_status` to `required`, which makes `mine`
  refuse the dataset.

Automatic redaction is not a substitute for manual inspection. Raw source
files should stay under the ignored `data-private/` directory and must never
be committed.

## Reproducible collection procedure

Clone and pin the external source separately; it is not a Trace2Flow runtime
dependency:

```bash
git clone https://github.com/sierra-research/tau2-bench.git data-private/tau2-bench
git -C data-private/tau2-bench rev-parse HEAD
```

Either run tau3-bench using credentials and cost approval, or reuse its public
historical retail results. Import only explicitly selected simulations or task
groups:

```bash
PYTHONPATH=src python -m trace2flow import-tau \
  data-private/tau2-bench/data/tau2/results/final/RESULTS.json \
  --dataset-id tau3_retail_quarantine \
  --task-id TASK_ID \
  --successful-only \
  --output data-private/tau3_retail_quarantine.json
```

The `--all` flag exists for deliberate bulk imports; selection is otherwise
mandatory so an accidental command cannot copy an entire result file.

Explicitly review every selected source call using a strict artifact shaped like
`tests/fixtures/tau_retail_review.json`. It must contain every source call ID,
including calls with no dependencies, and explicitly declare:

- data dependencies, based on parameter provenance rather than call order;
- read/write/none side effects and their targets;
- alignment keys where repeated tools have distinct logical roles; and
- `redaction_reviewed: true` only after manually reading the normalized file.

Re-import with the review:

```bash
PYTHONPATH=src python -m trace2flow import-tau \
  data-private/tau2-bench/data/tau2/results/final/RESULTS.json \
  --dataset-id tau3_retail_reviewed \
  --task-id TASK_ID \
  --successful-only \
  --review review.json \
  --output reviewed.json
```

Finally, split by source task group rather than individual trial. This keeps
all repeated trials of one tau task on the same side of the boundary:

```bash
PYTHONPATH=src python -m trace2flow split reviewed.json \
  --test-group-id HELD_OUT_TASK_ID \
  --compile-output compile.json \
  --test-output test.json
```

Trace2Flow also rejects a manually assembled compile/test pair when the same
`source + task_group_id` occurs in both partitions.

## Evidence language for the portfolio

Use:

> We evaluate on recorded agent executions from the public tau3-bench retail
> simulator. Customer and order records are simulated; no production customer
> data is included.

Do not call this a real-company trace corpus. Also do not interpret tau's DB
reward as a Trace2Flow state-equivalence result: independent local state
verification remains a separate requirement.

The fixture files under `tests/fixtures/tau_retail_*` are deliberately small,
schema-shaped synthetic regression fixtures. They test the adapter and are not
benchmark evidence.

The separate `examples/tau-retail-recorded/` directory is a reviewed recorded
benchmark corpus. Its `selection.json` pins the source file and explains every
exclusion; compile task 44 and test task 60 use different simulated entities.
Its committed structural report makes no execution-equivalence claim.

M9 adds `resolution.json` and `execution-cases.json` beside that corpus. The
former is an explicit typed runtime contract over the recorded structure; the
latter contains newly authored synthetic simulator states. They must not be
described as additional recorded traces or as recorded-response replay.
