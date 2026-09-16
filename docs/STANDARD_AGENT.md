# Standard Customer-Support Agent

This is the runnable conversational Agent that produces traces for the next
Trace2Flow iteration. It is deliberately separate from the frozen M11
experiment and from the workflow compiler. The Agent handles a request; the
recorder observes what happened; Trace2Flow will later decide whether repeated
observations contain a safe reusable workflow.

## What the user actually sends

`SupportRequest` contains only the authenticated session identifiers and the
user's natural message:

```json
{
  "thread_id": "demo-1",
  "ticket_id": "T-100",
  "authenticated_customer_id": "C-100",
  "message": "我上周买的蓝牙耳机咋还没到啊？物流好几天没动了",
  "channel": "web",
  "locale": "zh-CN"
}
```

The message is what the customer says. It is not a scenario label, expected
answer, order ID, policy result, or trusted fact. Authentication and the active
ticket would normally come from the host application; the demo passes them on
the command line. The model cannot provide or alter those values in tool calls.

```text
natural user turn + authenticated runtime context
                    |
                    v
          LangChain create_agent loop
             /       |        \
       read tools   policy   ask a question
             \       |        /
              evidence checks
                    |
             update_ticket request
                    |
              human approve/reject
                    |
        local state change + passive trace
```

The in-memory synthetic service provides three independent examples:

| Login / ticket | Natural issue available in local state |
| --- | --- |
| `C-100` / `T-100` | delayed Bluetooth-headset delivery |
| `C-200` / `T-200` | delivered thermos reported damaged |
| `C-300` / `T-300` | two successful keyboard captures |

These labels describe test data for developers. They are not sent to the model.

## Safety boundary

The model can call exactly seven typed tools: trusted support context, recent
orders, one order, shipping facts, payment events, policy lookup, and ticket
update. Tools enforce customer ownership. A foreign order and a nonexistent
order return the same generic failure, so the Agent cannot enumerate another
customer's data.

`update_ticket` is the only side effect. It is local, idempotent, limited to one
attempt per run, checked against facts and current policy, and interrupted for
an explicit approve/reject decision before mutation. The demo never sends a
message, contacts a carrier, refunds money, executes trace code, or connects to
a customer system. The prompt also forbids presenting the local record as an
external investigation or promising an automatic notification. Model and
total-tool call budgets stop runaway loops. After a successful write, the
application replaces the model's final wording with a fact-derived completion
notice. The raw model wording remains in the private audit trace, so unsupported
promises are neither shown to the user nor hidden from review.

LangSmith cloud tracing is disabled. The local trace records model/tool events,
typed arguments/results, usage metadata when reported, before/after state,
prompt hash and producer hash. It omits credentials, request headers, provider
raw payloads, reasoning content and provider exception text.

## Run it

Install the optional Agent dependencies and run the tests first:

```bash
uv sync --locked --extra agent --group dev
.venv/bin/python -m unittest tests.test_support_agent -v
```

With `DEEPSEEK_API_KEY` already exported, an explicitly authorized local demo
is:

```bash
PYTHONPATH=src .venv/bin/python -m trace2flow.support_agent \
  --customer-id C-100 \
  --ticket-id T-100 \
  --thread-id demo-delivery-1 \
  --message '我上周买的蓝牙耳机咋还没到啊？物流好几天没动了' \
  --approve-local-write \
  --allow-paid-call \
  --trace-output data-private/standard-agent-demo/delivery.json
```

The two explicit switches are intentional. Without `--allow-paid-call`, the
program exits before creating the model or output file. Without
`--approve-local-write`, it returns `approval_required` and leaves state
unchanged. Output paths are exclusive and will not overwrite an earlier run.

The CLI uses an in-memory checkpointer, so an approval cannot be resumed after
terminating and restarting the process. An application can keep one
`CustomerSupportAgent` instance alive and call `resume(thread_id, decision)`;
same-thread follow-up turns retain conversation state for that process.

## Current evidence and limits

Scripted-model tests validate the real framework loop, typed tool schemas,
conversation memory, authorization, ambiguity/follow-up behavior, approval and
rejection, evidence gates, idempotency, error redaction and CLI fail-closed
behavior. A paid development run is useful integration evidence, but it is not
a benchmark: one successful conversation says nothing about general accuracy.

This baseline does not yet route successful traces through Trace2Flow, select a
compiled workflow, persist conversations across restarts, evaluate final-chat
quality, or operate on real systems. M13b will add the trace adapter and a
conservative Agent/workflow router. M13c will freeze a new paired test set
before measuring task accuracy, unsafe writes, tool/model calls, tokens and
latency. Token reduction is an empirical question, not an assumed outcome.

The framework choices follow the official LangChain documentation for
[`create_agent`](https://docs.langchain.com/oss/python/langchain/agents),
[runtime context](https://docs.langchain.com/oss/python/langchain/runtime),
[short-term memory](https://docs.langchain.com/oss/python/langchain/short-term-memory),
and [human-in-the-loop middleware](https://docs.langchain.com/oss/python/langchain/human-in-the-loop).
