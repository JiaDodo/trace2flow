# tau3-bench recorded retail corpus

This directory contains seven redacted, reviewed execution records selected
from the public MIT-licensed
[`sierra-research/tau2-bench`](https://github.com/sierra-research/tau2-bench)
historical retail results. The repository calls its current release
tau3-bench.

The executions are real recorded runs in a simulated benchmark environment.
The customers, orders, products, and tools are simulated; this is not company
production data and contains no real customer data.

## Selection boundary

- Workflow family: modify one item in a pending retail order.
- Compile: three successful trials from source task `44`.
- Test: four successful trials from source task `60`.
- Task `61` was rejected because it reuses task `60`'s customer, order, and
  product entities. A different task ID was not treated as sufficient evidence
  of independence.
- Task `44` trial 2 was excluded because it contains an extra `calculate` call
  and falls outside the exact selected structure.

See `selection.json` for simulation IDs, revisions, the exact source-relative
path, and source-file SHA-256. `review.json` records every occurrence-level
dependency, side effect, and alignment declaration.

The declared edges express data provenance only:

- order lookup and authentication are independent roots because the order ID
  comes from task input, not the authentication tool output;
- product lookup consumes the product ID observed in the order result; and
- item modification consumes the target item/payment context from the order
  result and replacement item from the product result.

Authentication is still a required business-policy step, but policy order is
not misrepresented as a data dependency.

## Reproduction

Keep the raw external clone under ignored `data-private/`, verify the exact
source hash, and import the seven `simulation_ids` from `selection.json` in one
command with repeated `--simulation-id` options and `--review review.json`.
Then split task `60` as holdout:

```bash
PYTHONPATH=src python -m trace2flow split reviewed.json \
  --test-group-id 60 \
  --compile-output compile.json \
  --test-output holdout.json

PYTHONPATH=src python -m trace2flow mine compile.json \
  --output candidate.json --rule-profile strict

PYTHONPATH=src python -m trace2flow evaluate-structure candidate.json \
  --compile compile.json \
  --test holdout.json \
  --output structural-report.json
```

The committed normalized artifacts contain pseudonyms and omit prompts,
provider payloads, timestamps, token usage, and costs. Tool outputs remain
strings because that is how tau recorded them. The report is structural only;
it explicitly makes no output/state execution-equivalence claim.
