"""Human-in-the-loop gate nodes using LangGraph `interrupt()`.

Each gate calls `interrupt(payload)` which pauses the graph; the value passed to
`Command(resume=...)` becomes the return value of `interrupt()`. The resumed
value is expected to be a decision dict, e.g.:

    {"action": "approve", "body": "<optional edited body>"}
    {"action": "reject"}

Node contract (mandatory): (state, deps) -> partial state update. `deps` is
bound via functools.partial at graph build time; unused here but kept in the
signature.
"""
from __future__ import annotations

from langgraph.types import interrupt

from .. import config
from ..adapters.base import Deps
from ..state import DraftArtifact, SalesState


def _last_draft(state: SalesState) -> DraftArtifact:
    return state["drafts"][-1]


# --------------------------------------------------------------------------- #
# Cold-call script approval                                                    #
# --------------------------------------------------------------------------- #
def call_human_gate(state: SalesState, deps: Deps) -> dict:
    """Require a human to approve / edit / reject the cold-call script."""
    prospect = state["prospect"]
    d = _last_draft(state)
    decision = interrupt(
        {
            "type": "approval_required",
            "gate": "cold_call_script",
            "channel": "call",
            "lead_id": prospect.lead_id,
            "body": d["body"],
            "actions": ["approve", "edit", "reject"],
        }
    )
    if decision.get("action") == "reject":
        return {"human_decision": decision, "stage": "done"}
    body = decision.get("body", d["body"])
    return {
        "drafts": [{**d, "body": body, "approved": True}],
        "human_decision": decision,
    }


# --------------------------------------------------------------------------- #
# LinkedIn message approval                                                     #
# --------------------------------------------------------------------------- #
def linkedin_human_gate(state: SalesState, deps: Deps) -> dict:
    """Require a human to approve / edit / reject the LinkedIn message."""
    prospect = state["prospect"]
    d = _last_draft(state)
    decision = interrupt(
        {
            "type": "approval_required",
            "gate": "linkedin_message",
            "channel": "linkedin",
            "lead_id": prospect.lead_id,
            "body": d["body"],
            "actions": ["approve", "edit", "reject"],
        }
    )
    if decision.get("action") == "reject":
        return {"human_decision": decision, "stage": "done"}
    body = decision.get("body", d["body"])
    return {
        "drafts": [{**d, "body": body, "approved": True}],
        "human_decision": decision,
    }


# --------------------------------------------------------------------------- #
# Pricing / terms approval                                                      #
# --------------------------------------------------------------------------- #
def pricing_gate(state: SalesState, deps: Deps) -> dict:
    """Require a human to approve / counter / reject proposed deal terms."""
    prospect = state["prospect"]
    decision = interrupt(
        {
            "type": "approval_required",
            "gate": "pricing_approval",
            "lead_id": prospect.lead_id,
            "proposed_terms": state.get("deal"),
            "actions": ["approve", "counter", "reject"],
        }
    )
    if decision.get("action") == "reject":
        deal = {**(state.get("deal") or {}), "stage": "lost", "lost_reason": "pricing_rejected"}
        return {"human_decision": decision, "deal": deal, "stage": "close"}
    return {"human_decision": decision, "stage": "close"}


# --------------------------------------------------------------------------- #
# Optional high-value email gate (config-toggled)                              #
# --------------------------------------------------------------------------- #
def tier_a_email_gate(state: SalesState, deps: Deps) -> dict:
    """Gate high-value (Tier A) emails only when explicitly enabled in config."""
    if not config.high_value_email_gate_enabled():
        return {}
    prospect = state["prospect"]
    d = _last_draft(state)
    decision = interrupt(
        {
            "type": "approval_required",
            "gate": "high_value_email",
            "channel": "email",
            "lead_id": prospect.lead_id,
            "subject": d.get("subject"),
            "body": d.get("body"),
            "actions": ["approve", "edit", "reject"],
        }
    )
    if decision.get("action") == "reject":
        return {"human_decision": decision, "stage": "done"}
    body = decision.get("body", d.get("body", ""))
    return {
        "drafts": [{**d, "body": body, "approved": True}],
        "human_decision": decision,
    }
