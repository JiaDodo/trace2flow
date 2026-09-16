# Agent-Integrated Trace2Flow Router

M13b connects the standard support Agent to Trace2Flow without turning an
observed pattern into automatic execution permission. It adds two separate
boundaries:

1. `support_trace` converts saved standard-Agent sessions into the existing
   typed `TraceDataset` schema.
2. `support_router` may select an explicitly promoted Workflow IR for a narrow
   request; all uncertainty falls back to the standard Agent.

## Trace intake and review

The CLI output produced by `trace2flow.support_agent` can be parsed directly:

```python
from trace2flow.io import loads_json_document
from trace2flow.support_trace import normalize_support_session

raw = loads_json_document(open("data-private/run.json", encoding="utf-8").read())
quarantine = normalize_support_session(
    raw,
    dataset_id="support-agent-new-recordings",
    source="private-local-recordings",
)
```

The initial result has `import_review_status=required`. Every call remains a
distinct occurrence and JSON types are preserved, but dependencies and side
effects are empty. Call order, equal values and a state diff are not silently
converted into lineage.

`SupportRecordingReview` must be hash-bound to the exact recording and provide
an exhaustive entry for every call's dependencies, side effects and optional
alignment key. Reviews identify whether the reviewer was human, AI, or an
automated test. The library never labels AI review as human review. Only fully
successful, completely reviewed runs can be merged into a promotion-eligible
compile dataset; failed runs remain valid evidence but cannot enter that helper.

The reviewed dataset then uses the normal Trace2Flow path:

```text
reviewed normalized runs
  -> pinned upstream compiler
  -> occurrence-aware candidate DAG
  -> explicit ResolutionPlan
  -> Workflow IR
  -> independent development verification
  -> explicit promotion review
  -> append-only registry
```

## Registry gate

A `WorkflowRegistration` embeds the Workflow IR and a narrow route contract.
Registration succeeds only when all of the following agree:

- the recomputed Workflow IR SHA-256;
- a development verification record that declares both output and full-state
  comparison;
- an explicit promotion review and reviewer kind;
- no unresolved workflow dependency, occurrence, binding, branch, or side
  effect;
- exactly the five local delivery tools and their reviewed parameter bindings;
- required evidence edges and the ticket update as the business output.

The in-process registry is append-only. The same name/version cannot be
replaced, and two matching registrations are treated as ambiguity and cause an
Agent fallback. A verification/promotion object is an auditable attestation,
not cryptographic proof that its author was honest; M13c artifacts will bind it
to a reproducible scorer and manifest.

## Routing behavior

The first supported contract is intentionally narrow: one explicit `O-...`
order ID, clear delivery language, clear delay language, and no conflicting
refund, billing, damage, exchange, cancellation, or second-order intent. The
router does not ask an LLM to classify eligibility. Missing/multiple IDs,
ambiguous wording, unknown/foreign orders, preflight failures, registry
conflicts, and unsupported tasks invoke the unchanged standard Agent.

For a matched request, the workflow first runs in a cloned local backend. This
checks current ownership, recent-order membership, shipping facts and policy
without changing live state. The router then returns `approval_required`.
Approval reruns every read and evidence check against current live state before
the idempotent ticket write; stale facts fail rather than using the preview.
Rejection leaves state unchanged. Agent-fallback approvals resume through the
same router API.

```python
from trace2flow.support_agent import CustomerSupportAgent, SupportRequest
from trace2flow.support_backend import SupportBackend
from trace2flow.support_router import AdaptiveSupportRouter, WorkflowRegistry

backend = SupportBackend.demo()
registry = WorkflowRegistry()
registry.register(registration)  # validated WorkflowRegistration
router = AdaptiveSupportRouter(agent=agent, backend=backend, registry=registry)

turn = router.invoke(SupportRequest(
    thread_id="demo",
    ticket_id="T-100",
    authenticated_customer_id="C-100",
    message="订单 O-1001 的物流没更新，而且还没到。",
))
if turn.status == "approval_required":
    turn = router.resume("demo", "approve")
```

No default production registration is silently installed. The offline tests
create two fresh scripted compile runs, review them explicitly, invoke the real
upstream compiler and Workflow IR builder, register the resulting workflow,
and compare its complete state with the standard Agent on a paired development
case. This proves the integration mechanics, not general routing accuracy.

## Current limits

- Only a narrow explicit-order delivery-delay contract is supported.
- Registry and pending approvals are in memory and do not survive restart.
- A workflow-routed turn does not seed the fallback Agent's conversational
  memory; ambiguous follow-up turns are safe but may need to restate context.
- The lexical route contract is deliberately conservative and is not a general
  Chinese intent classifier.
- No production registration, real customer backend, automatic learning, or
  automatic workflow replacement exists.
- Token/accuracy/error improvements have not been measured. M13c must freeze a
  paired evaluation before making those comparisons.
