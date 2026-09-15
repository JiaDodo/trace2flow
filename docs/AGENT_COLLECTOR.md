# DeepSeek customer-support trace producer

This is a Trace2Flow addition, not upstream AutoCompile capability. Its purpose
is to generate inspectable model-executed tool traces and a future evaluation
baseline. The original Clingo compiler and rules are unchanged.

## Boundaries

- Use LangChain `create_agent` with five fixed wrappers around the existing
  `CustomerSupportSimulator`/`ToolRegistry`. No shell, dynamic imports from
  traces, refunds, messaging, cloud tracing, or real customer systems.
- The model chooses calls; there is no hard-coded five-step sequence. Tool
  guards enforce task identity, observed facts and policy recommendations,
  not a required invocation of every tool. Independent customer queries may
  be omitted/repeated. This controlled policy still constrains allowed paths;
  it is not evidence of unconstrained general workflow discovery.
- Classification and recommendations are deterministic existing tool rules.
  `classify_issue` ignores complaint text and classifies verified order flags.
  The model orchestrates tools and communicates outcomes; natural-language
  business classification is not a newly verified capability.
- Default: `deepseek-v4-pro`, non-thinking mode, standard official endpoint,
  2,048 maximum output tokens/request, 30-second request timeout, no retries,
  10 model calls and 12 dispatched tool calls/run. These are execution bounds,
  not a whole-run token or monetary guarantee. Independent registered customer
  and order read batches are preserved in model events and dispatched serially
  (`max_concurrency=1`), without inferring any dependency. Compute/write/unknown
  tool batches stop before execution. Three initial v1.0/v1.1 pilots stopped
  on read batches and remain in the inventory. v1.2 supports only these audited
  independent reads; this adjustment is development, not a held-out result.
- Use strict local Pydantic schemas. DeepSeek strict tool mode requires the
  beta endpoint; this producer does not silently enable beta or claim native
  strict mode. Invalid model arguments are recorded and cannot mutate state.

## Run one development task

```bash
uv sync --locked --extra agent --group dev
# Configure DEEPSEEK_API_KEY securely in your process; do not paste it into Git.
uv run --extra agent python -m trace2flow.agent_collect \
  examples/customer-support-agent/delivery-delay.json \
  --allow-paid-call --output data-private/agent-pilot/delivery-001
```

The output directory must be new. The two committed task files contain only
synthetic development inputs, not expected answers. They are not a test-set
estimate and are not independent of previously committed simulator examples.

`raw.json` retains the supplied task, prompt/hash/version, producer hash,
requested model, model messages, tool request IDs/arguments/results/errors,
available usage, stopping reason, elapsed time and complete local state. It
excludes credentials, headers, arbitrary provider payloads and reasoning.
Model aliases are not immutable snapshots; the recording explicitly marks
the model snapshot as unpinned. Provider-reported model labels are retained
when available, but do not establish reproducibility by themselves.

`normalized.quarantine.json` preserves all dispatched occurrences and JSON
types. Provenance is `recorded` for actual model runs in a synthetic local
simulator, or `synthetic` for scripted offline responses. Every dependency is
empty and explicitly requires review. Dataset `import_review_status=required`
blocks mining. Registered tool effects describe capability, not proof that
a rejected call performed an effect. Zero-call runs remain raw-only instead
of inventing an occurrence to satisfy the schema.

A model finishing is not business success. The normalized business output is
the last successful ticket-update result; the final chat message is not an
oracle. Even a completed update has `business_success_verified=false` until
an independent expected-state/output check is performed. Failure endings and
state after partial execution remain saved. Directory reuse is rejected
before any CLI live call; missing credentials and an absent paid flag fail
before network access.

Check the five saved M10 development recordings, including all three stopped
attempts, without another model request:

```bash
uv run --extra agent python -m trace2flow.agent_pilot data-private/agent-pilot
```

This checker has fixed independent expectations for these development inputs:
the delivery case returns `carrier_investigation`/`pending_carrier` and only
the target ticket changes; the foreign-order case must have a failed order
lookup and no write; initial read-batch stops must leave state unchanged.
It checks the entire local state and recorded business output, not just file
existence. It does not score chat wording or general Agent/workflow capability.
No raw pilot files are committed; hashes and observed results are in STATUS.

## Evaluation next

Prepare compile/development/untouched-test partitions by full task group before
larger collection. Specify expected recommendations, target ticket states,
and unchanged unrelated entities independently of Agent answers. Keep failed
and unsupported trajectories. Use a separate exhaustive reviewer artifact
before mining; the producer does not automatically infer data lineage from
common-value matches or execution guards. Report review effort, coverage,
accepted-case correctness and unsafe acceptance separately. A reviewed corpus
and general collector-review intake are M11, not delivered by this pilot.

## Official references checked 2026-09-15

- [DeepSeek API entrypoint and model names](https://api-docs.deepseek.com/)
- [DeepSeek tool calls and beta strict schemas](https://api-docs.deepseek.com/guides/tool_calls/)
- [DeepSeek thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/)
- [LangChain DeepSeek integration](https://docs.langchain.com/oss/python/integrations/chat/deepseek)
- [LangChain Agent loop](https://docs.langchain.com/oss/python/langchain/agents)
- [LangChain middleware hooks](https://docs.langchain.com/oss/python/langchain/middleware/custom)

Some integration examples use old DeepSeek aliases and historical capability
notes; rely on the current provider documentation and live pilot instead.
