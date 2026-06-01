"""Assemble the Constrox SDR LangGraph StateGraph.

build_graph(deps, checkpointer) wires all nodes + edges and returns a compiled
graph. Nodes are referenced through their modules (not imported by name) so
tests can monkeypatch a node before building. deps is bound to each node via
functools.partial; routing functions are pure (state -> str).

Channel flows:
  email    : email_draft   -> compliance_gate -> (email_send   | blocked)
  call     : call_script   -> call_human_gate -> compliance_gate -> (queue_dialer  | blocked)
  linkedin : linkedin_draft-> linkedin_human_gate -> compliance_gate -> (queue_linkedin| blocked)
Reply/close: await_reply -> classify_reply -> {book_discovery|handle_objection|nurture}
             discovery -> demo -> negotiate -> (pricing_gate?) -> close -> handoff -> crm_sync
"""
from __future__ import annotations

from functools import partial
from typing import Optional

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from .state import SalesState
from .adapters.base import Deps
from .nodes import research, scoring, outreach, gates, reply, close, sync, routing


# --------------------------------------------------------------------------- #
# Event-wait node (parks until an inbound reply arrives; passthrough if seeded)#
# --------------------------------------------------------------------------- #
def await_reply(state: SalesState, deps: Deps) -> dict:
    if state.get("inbound_reply"):
        return {"stage": "reply"}
    received = interrupt({
        "type": "await_event", "event": "inbound_reply",
        "lead_id": state["prospect"].lead_id,
    })
    return {"inbound_reply": received, "stage": "reply"}


# --------------------------------------------------------------------------- #
# Combined post-compliance router: block on fail, else route by draft channel  #
# --------------------------------------------------------------------------- #
def route_after_compliance(s: SalesState) -> str:
    if not s["compliance_results"][-1].get("passed"):
        return "blocked"
    channel = s["drafts"][-1].get("channel")
    return {"email": "email_send", "call": "queue_dialer", "linkedin": "queue_linkedin"}[channel]


def route_after_pricing(s: SalesState) -> str:
    """Human rejected the price -> deal already marked lost -> sync, don't close as won."""
    action = (s.get("human_decision") or {}).get("action")
    return "crm_sync" if action == "reject" else "close_deal"


def route_after_human_gate(s: SalesState) -> str:
    """Human rejected a call script / LinkedIn message -> abort the touch; never queue."""
    action = (s.get("human_decision") or {}).get("action")
    return "nurture_or_terminate" if action == "reject" else "compliance_gate"


def build_graph(deps: Deps, checkpointer=None):
    if checkpointer is None:
        from .checkpoint import memory_checkpointer
        checkpointer = memory_checkpointer()

    g = StateGraph(SalesState)

    def add(name, fn):
        g.add_node(name, partial(fn, deps=deps))

    # --- nodes ---
    add("research", research.research)
    add("score", scoring.score)
    add("suppress", scoring.suppress)
    add("plan_cadence", outreach.plan_cadence)
    add("email_draft", outreach.email_draft)
    add("call_script", outreach.call_script)
    add("linkedin_draft", outreach.linkedin_draft)
    add("call_human_gate", gates.call_human_gate)
    add("linkedin_human_gate", gates.linkedin_human_gate)
    add("compliance_gate", outreach.compliance_gate)
    add("email_send", outreach.email_send)
    add("queue_dialer", outreach.queue_dialer)
    add("queue_linkedin", outreach.queue_linkedin)
    add("await_reply", await_reply)
    add("classify_reply", reply.classify_reply)
    add("handle_objection", reply.handle_objection)
    add("book_discovery", close.book_discovery)
    add("run_discovery", close.run_discovery)
    add("schedule_demo", close.schedule_demo)
    add("negotiate", close.negotiate)
    add("pricing_gate", gates.pricing_gate)
    add("close_deal", close.close_deal)
    add("onboarding_handoff", close.onboarding_handoff)
    add("crm_sync", sync.crm_sync)
    add("blocked_node", sync.blocked_node)
    add("nurture_or_terminate", sync.nurture_or_terminate)

    # --- entry + qualify ---
    g.add_edge(START, "research")
    g.add_edge("research", "score")
    g.add_conditional_edges("score", routing.route_after_score,
                            {"suppress": "suppress", "disqualify": "crm_sync"})
    g.add_conditional_edges("suppress", routing.route_after_suppress,
                            {"plan_cadence": "plan_cadence", "blocked": "blocked_node"})

    # --- channel fan-out (first cadence step) ---
    g.add_conditional_edges("plan_cadence", routing.route_channel,
                            {"email": "email_draft", "call": "call_script",
                             "linkedin": "linkedin_draft"})

    # email: draft -> compliance
    g.add_edge("email_draft", "compliance_gate")
    # call: script -> human gate -> (compliance | abort)
    g.add_edge("call_script", "call_human_gate")
    g.add_conditional_edges("call_human_gate", route_after_human_gate,
                            {"compliance_gate": "compliance_gate",
                             "nurture_or_terminate": "nurture_or_terminate"})
    # linkedin: draft -> human gate -> (compliance | abort)
    g.add_edge("linkedin_draft", "linkedin_human_gate")
    g.add_conditional_edges("linkedin_human_gate", route_after_human_gate,
                            {"compliance_gate": "compliance_gate",
                             "nurture_or_terminate": "nurture_or_terminate"})

    # compliance -> send/queue or blocked
    g.add_conditional_edges("compliance_gate", route_after_compliance,
                            {"email_send": "email_send", "queue_dialer": "queue_dialer",
                             "queue_linkedin": "queue_linkedin", "blocked": "blocked_node"})

    g.add_edge("email_send", "await_reply")
    g.add_edge("queue_dialer", "await_reply")
    g.add_edge("queue_linkedin", "await_reply")

    # --- reply handling ---
    g.add_edge("await_reply", "classify_reply")
    g.add_conditional_edges("classify_reply", routing.route_after_reply,
                            {"book_discovery": "book_discovery",
                             "handle_objection": "handle_objection",
                             "nurture_or_terminate": "nurture_or_terminate"})
    # objection already drafted a rebuttal email -> straight to compliance/send
    g.add_edge("handle_objection", "compliance_gate")

    # --- full-cycle close ---
    g.add_edge("book_discovery", "run_discovery")
    g.add_conditional_edges("run_discovery", routing.route_after_discovery,
                            {"schedule_demo": "schedule_demo",
                             "nurture_or_terminate": "nurture_or_terminate"})
    g.add_edge("schedule_demo", "negotiate")
    g.add_conditional_edges("negotiate", routing.route_after_negotiate,
                            {"pricing_gate": "pricing_gate", "close_deal": "close_deal"})
    g.add_conditional_edges("pricing_gate", route_after_pricing,
                            {"close_deal": "close_deal", "crm_sync": "crm_sync"})
    g.add_edge("close_deal", "onboarding_handoff")
    g.add_edge("onboarding_handoff", "crm_sync")

    # --- terminals ---
    g.add_edge("nurture_or_terminate", "crm_sync")
    g.add_edge("blocked_node", "crm_sync")
    g.add_edge("crm_sync", END)

    return g.compile(checkpointer=checkpointer)
