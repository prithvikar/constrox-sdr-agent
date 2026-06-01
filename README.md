# Constrox Sales Development Agent

A full-cycle **AI Sales Development agent** for [Constrox](https://constrox.com)
(ASISA Technologies LLP) — an offshore structural-engineering services firm
(steel detailing, BIM, estimation, rebar/precast/connection design). The agent
sources AEC prospects (steel fabricators, GCs, structural consultancies,
precast/rebar suppliers) across **US / UK / Australia**, scores them against the
ICP, runs **compliant automated email outreach**, drafts **human-gated** cold-call
scripts and LinkedIn messages, and drives qualified opportunities through
**discovery → demo → negotiation → onboarding handoff**, tracking pipeline and
paid-invoice commission.

Built on **LangChain + LangGraph**. LLM provider defaults to **Google Gemini**
(runs on a single Gemini Flash key); set `MODEL_PROVIDER=anthropic` for Claude.

## Why this shape

Three things about the listing drove the design:

1. **Constrox's CRM + dialer are proprietary** (no public API). Every external
   system sits behind a **pluggable adapter** (`adapters/base.py`). Mocks ship
   now; real Constrox adapters drop in behind the identical interface with zero
   node changes.
2. **Compliance is non-negotiable** across three jurisdictions. A deterministic
   **compliance gate** (`compliance.py`, no LLM) enforces CAN-SPAM, TCPA/DNC,
   UK GDPR+PECR/TPS-CTPS, the AU Spam Act + DNCR, and LinkedIn's
   no-automation rule. *No audit log → no send.*
3. **An AI agent shouldn't autonomously cold-dial or auto-send LinkedIn.** Those
   are **human-in-the-loop** gates (`interrupt()`): the agent drafts and queues;
   a human dials/sends. Email is the only fully-automated send channel.

## Architecture

```
LangGraph StateGraph (Postgres-checkpointed, interrupt()-gated)

 research → score → suppress → plan_cadence ─┬─ email_draft ─────────────→ compliance_gate ─→ email_send ─┐
                                             ├─ call_script → [HUMAN GATE] → compliance_gate ─→ queue_dialer┤→ await_reply
                                             └─ linkedin_draft → [HUMAN GATE] → compliance_gate ─→ queue_linkedin┘     │
                                                                                                                       ▼
   crm_sync ← onboarding_handoff ← close_deal ← [PRICING GATE?] ← negotiate ← schedule_demo ← run_discovery ← book_discovery ← classify_reply
```

- **Models** (`models.py`): provider-agnostic factory. Nodes call `models.llm(task)`
  / `models.structured(task, Schema)` and never touch a provider SDK — switching
  Gemini ↔ Claude is a config change.
- **State** (`state.py`): `SalesState` TypedDict + Pydantic I/O models
  (`Prospect`, `LeadScore`, `ReplyClass`, `BANT`, `ComplianceResult`).
- **HITL gates** (`nodes/gates.py`): cold-call script, LinkedIn message, pricing.
- **Commission** (`commission.py`): 7–13% recurring, re-fires on each paid
  invoice; pipeline-coverage + conversion math against the listing's targets.

## How we architected this with LangChain + LangGraph

The whole sales motion is modeled as a **LangGraph `StateGraph`** — a directed
graph of typed nodes connected by conditional edges, with durable checkpointing
and human-in-the-loop interrupts. LangChain provides the model abstraction,
structured output, and tool plumbing underneath. Here's the design, layer by
layer.

### 1. Typed graph state (`state.py`)

The single source of truth flowing through the graph is `SalesState`, a
`TypedDict` with **reducer-annotated** accumulator fields so parallel/iterative
node returns merge instead of clobber:

```python
class SalesState(TypedDict, total=False):
    prospect: Prospect                                   # pydantic model
    messages: Annotated[list[AnyMessage], add_messages]  # LangChain message reducer
    score: Optional[LeadScore]
    drafts: Annotated[list[DraftArtifact], add]          # append-only outbound log
    compliance_results: Annotated[list[dict], add]       # append-only audit trail
    reply_class: Optional[ReplyClass]
    bant: Optional[BANT]
    deal: Optional[DealRecord]
    stage: Stage
    human_decision: Optional[dict]                       # filled by Command(resume=...)
```

Nodes return *partial* updates (`return {"score": ...}`); LangGraph applies the
reducers. `drafts` and `compliance_results` use `operator.add`, so every email,
call script, and compliance decision is preserved as an immutable record.

### 2. Nodes as pure-ish functions with injected dependencies

Every node has the signature `def node(state, deps) -> dict`. `deps` is a
dataclass of **adapter Protocols** (CRM, dialer, email, LinkedIn, enrichment,
calendar, register-scrubber). At graph-build time we bind it with
`functools.partial`, so nodes never reach for a global or a vendor SDK:

```python
def add(name, fn):
    g.add_node(name, partial(fn, deps=deps))   # deps pre-bound; node receives (state)
```

This is what makes the agent testable and swappable: tests inject mock adapters;
production injects real Constrox adapters; the node code is identical.

### 3. Routing as pure functions on conditional edges

Control flow lives in small, unit-testable routing functions wired with
`add_conditional_edges`:

```python
def route_after_reply(s) -> str:
    rc = s.get("reply_class")
    if rc and rc.intent in ("interested", "meeting_request"): return "book_discovery"
    if rc and rc.intent in ("objection", "referral"):         return "handle_objection"
    return "nurture_or_terminate"

g.add_conditional_edges("classify_reply", route_after_reply, {
    "book_discovery": "book_discovery",
    "handle_objection": "handle_objection",
    "nurture_or_terminate": "nurture_or_terminate",
})
```

Because routers are pure `(state) -> str`, the entire decision logic is covered
by fast table-driven tests with no graph or LLM in the loop.

### 4. Human-in-the-loop via `interrupt()` + checkpointing

Cold-call dialing, LinkedIn sending, and out-of-band pricing **pause the graph
mid-run** and wait for a human. LangGraph's `interrupt()` suspends the node and
persists state to the checkpointer; a later `Command(resume=...)` rehydrates the
exact thread and continues:

```python
def call_human_gate(state, deps):
    decision = interrupt({                       # graph suspends here
        "gate": "cold_call_script", "channel": "call",
        "body": state["drafts"][-1]["body"], "actions": ["approve", "edit", "reject"],
    })
    if decision["action"] == "reject":
        return {"human_decision": decision, "stage": "done"}
    body = decision.get("body", state["drafts"][-1]["body"])
    return {"drafts": [{**state["drafts"][-1], "body": body, "approved": True}],
            "human_decision": decision}
```

Driving it:

```python
app.invoke(initial_state(prospect), cfg)         # runs until the interrupt
snap = app.get_state(cfg)                         # snap.next == ("call_human_gate",)
intr = snap.tasks[0].interrupts[0].value          # the approval payload for the UI
app.invoke(Command(resume={"action": "approve"}), cfg)   # human approves -> continues
```

The same mechanism models the **inbound-reply wait**: `await_reply` interrupts
until a webhook resumes the thread with the prospect's reply. Threads survive
process restarts because state is checkpointed (`MemorySaver` in dev,
`PostgresSaver` in prod, both in `checkpoint.py`).

### 5. Structured output + model routing via LangChain

Classification and scoring use LangChain's `with_structured_output` to force the
model to emit a validated Pydantic object — no brittle parsing:

```python
def structured(task, schema, tier=None, temperature=0.0):
    return llm(task, tier=tier, temperature=temperature).with_structured_output(schema)

# in a node:
rc: ReplyClass = models.structured("classify_reply", ReplyClass).invoke(reply_text)
```

`models.llm(task, tier)` is a thin factory that maps a *task name* to a model and
constructs the LangChain chat client lazily. Provider is config-driven —
`ChatGoogleGenerativeAI` (Gemini, default) or `ChatAnthropic` (Claude) — and
because every node calls `models.llm` / `models.structured` and never imports a
provider SDK, **switching providers is a one-line env change**. Every LLM node
also has a deterministic fallback, so the graph runs end-to-end even with no API
key (great for CI and demos).

### 6. Compiling and running

```python
app = build_graph(deps, checkpointer)   # StateGraph.compile(checkpointer=...)
for update in app.stream(initial_state(prospect), cfg, stream_mode="updates"):
    ...                                  # observe each node's output as it runs
```

The result: a sales agent where **the business logic is the graph topology**, the
**compliance + HITL guarantees are structural** (not prompt-hopes), and the
**LLM, CRM, and dialer are all swappable** behind typed seams.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run the agent end-to-end on mock adapters (works with NO API key — falls back
# to deterministic templates):
python scripts/run_local.py          # email → discovery → demo → won deal
python scripts/run_local.py --call   # shows the cold-call HUMAN gate (never auto-dials)
```

### Using a Gemini key

```bash
export MODEL_PROVIDER=google
export GOOGLE_API_KEY=...             # or GEMINI_API_KEY
export GEMINI_MODEL=gemini-2.5-flash  # your exact model id
python scripts/run_local.py
```

## Tests

```bash
pytest -m "not eval"     # 73 offline tests (mocks + fake LLM): pipeline e2e,
                         # HITL gates, compliance table, routing, commission
pytest -m eval           # live LLM eval (needs an API key): reply-classification
                         # accuracy ≥0.85, lead-scoring tier precision ≥0.80
```

## Going to production (when Constrox shares access)

Implement the real adapters in `adapters/constrox.py` against whatever Constrox
exposes (webhook/API/CSV/RPA): CRM, dialer (click-to-dial + call logs), email
sender, LinkedIn tool of record, billing `invoice.paid`. Swap `MemorySaver` for
`PostgresSaver` (`checkpoint.py`), run `db/schema.sql`, and serve `webhooks.py`.
No node or graph changes required.

**Open items to confirm with Constrox:** CRM/dialer integration surface; billing
system that emits `invoice.paid`; LinkedIn tool of record; commission "recurring"
duration + churn clawback terms.
