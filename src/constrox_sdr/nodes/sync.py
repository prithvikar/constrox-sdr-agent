"""Terminal-side nodes: CRM persistence, blocked logging, and nurture/terminate.

These are the graph's sinks. `crm_sync` is the canonical persistence step;
`blocked_node` records why a prospect was halted; `nurture_or_terminate` is the
soft-exit for non-converting threads.
"""
from __future__ import annotations

from ..state import Prospect, SalesState
from ..adapters.base import Deps


def crm_sync(state: SalesState, deps: Deps) -> dict:
    """Persist the lead, any deal, and a sync activity to the CRM."""
    prospect: Prospect = state["prospect"]
    deps.crm.upsert_lead(prospect.model_dump())
    if state.get("deal"):
        deps.crm.upsert_deal(state["deal"])
    deps.crm.log_activity(
        prospect.lead_id,
        {"type": "sync", "stage": state.get("stage")},
    )
    return {"crm_synced": True}


def blocked_node(state: SalesState, deps: Deps) -> dict:
    """Record the block reason and mark the thread blocked."""
    prospect: Prospect = state["prospect"]
    deps.crm.log_activity(
        prospect.lead_id,
        {"type": "blocked", "reason": state.get("error")},
    )
    return {"stage": "blocked"}


def nurture_or_terminate(state: SalesState, deps: Deps) -> dict:
    """Soft exit for non-converting prospects."""
    return {"stage": "done"}
