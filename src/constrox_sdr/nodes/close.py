"""Closing-loop nodes: discovery booking, BANT discovery, demo, negotiation,
close, and onboarding handoff.

These nodes drive a prospect from a positive reply through a won deal. They
mutate the DealRecord in state and book calendar slots via the calendar adapter.
Routing decisions (pricing gate vs close, demo vs nurture) live in routing.py.
"""
from __future__ import annotations

from .. import models
from ..state import BANT, DealRecord, Prospect, SalesState
from ..adapters.base import Deps

try:  # prompts.py is owned by another agent; tolerate absence.
    from .. import prompts  # type: ignore
except Exception:  # pragma: no cover - import-safety only
    prompts = None  # type: ignore


# Default monthly retainer assumed for a qualified opportunity (expected MONTHLY
# billing, matches DealRecord.pipeline_value semantics).
DEFAULT_MONTHLY_VALUE = 6000.0


def _deal(state: SalesState) -> DealRecord:
    """Return a shallow copy of the current deal (or an empty dict)."""
    return dict(state.get("deal") or {})


# --------------------------------------------------------------------------- #
# Discovery                                                                   #
# --------------------------------------------------------------------------- #
def book_discovery(state: SalesState, deps: Deps) -> dict:
    """Book the first discovery slot and open the deal record."""
    prospect: Prospect = state["prospect"]
    slots = deps.cal.availability()
    if slots:
        deps.cal.book(prospect.lead_id, slots[0], "discovery")
    prev = _deal(state)
    deal: DealRecord = {
        "deal_id": None,
        "stage": "discovery",
        "pipeline_value": prev.get("pipeline_value", 0.0),
        "recurring": False,
    }
    return {"deal": deal, "stage": "discovery"}


def _bant_heuristic(notes: str) -> BANT:
    """Cheap keyword-based BANT extraction used when the LLM is unavailable."""
    low = (notes or "").lower()
    budget = "mentioned" if any(k in low for k in ("budget", "$", "per tonne", "spend")) else None
    authority = "decision maker" if any(
        k in low for k in ("owner", "i decide", "my call", "ceo", "president", "director")
    ) else None
    need = "expressed" if any(
        k in low for k in ("backlog", "overflow", "capacity", "need", "behind", "short-staffed")
    ) else None
    timeline = "near-term" if any(
        k in low for k in ("this month", "next month", "asap", "soon", "q1", "q2", "q3", "q4")
    ) else None
    pain = "capacity / turnaround pressure" if need else None
    qualified = bool(need) and (bool(authority) or bool(timeline))
    return BANT(budget=budget, authority=authority, need=need, timeline=timeline,
                pain=pain, qualified=qualified)


def run_discovery(state: SalesState, deps: Deps) -> dict:
    """Extract BANT from the call notes and set the deal's expected value."""
    notes = state.get("inbound_reply") or ""
    try:
        bant = models.structured("run_discovery", BANT).invoke(notes)
        if not isinstance(bant, BANT):
            bant = _bant_heuristic(notes)
    except Exception:
        bant = _bant_heuristic(notes)

    deal = _deal(state)
    if bant.qualified:
        deal["pipeline_value"] = deal.get("pipeline_value") or DEFAULT_MONTHLY_VALUE
        deal["recurring"] = True
        deal["stage"] = "demo"
        next_stage = "demo"
    else:
        deal["stage"] = "discovery"
        next_stage = "discovery"

    return {"bant": bant, "deal": deal, "stage": next_stage}


def schedule_demo(state: SalesState, deps: Deps) -> dict:
    """Book the demo slot and advance toward negotiation."""
    prospect: Prospect = state["prospect"]
    slots = deps.cal.availability()
    if len(slots) > 1:
        deps.cal.book(prospect.lead_id, slots[1], "demo")
    elif slots:
        deps.cal.book(prospect.lead_id, slots[0], "demo")
    deal = _deal(state)
    deal["stage"] = "demo"
    return {"deal": deal, "stage": "negotiate"}


# --------------------------------------------------------------------------- #
# Negotiation & close                                                         #
# --------------------------------------------------------------------------- #
def negotiate(state: SalesState, deps: Deps) -> dict:
    """Produce proposed commercial terms and move the deal into negotiation."""
    prospect: Prospect = state["prospect"]
    deal = _deal(state)
    monthly = deal.get("pipeline_value", 0.0)

    try:
        prompt = getattr(prompts, "NEGOTIATE_PROMPT", None) if prompts else None
        if prompt is not None:
            instruction = prompt.format(company=prospect.company, monthly=monthly)
        else:
            instruction = (
                f"Draft concise proposed commercial terms for {prospect.company}: a recurring "
                f"monthly steel-detailing retainer of approximately ${monthly:,.0f}/month, "
                f"a 30-day trial package, and standard IP-assignment. Keep it to 4-5 bullet points."
            )
        resp = models.llm("negotiate").invoke(instruction)
        terms = (getattr(resp, "content", "") or "").strip()
    except Exception:
        terms = (
            f"Proposed: ${monthly:,.0f}/month recurring retainer, 30-day trial package, "
            f"IP-assignment + PI cover included."
        )

    deal["stage"] = "negotiation"
    deal["expected_close"] = "2026-06-30"
    deal.setdefault("terms", terms)  # informational; tolerated by total=False DealRecord
    return {"stage": "negotiate", "deal": deal}


def close_deal(state: SalesState, deps: Deps) -> dict:
    """Mark the deal won and hand off to onboarding."""
    deal = _deal(state)
    deal["stage"] = "won"
    deal["won_amount"] = deal.get("pipeline_value", 0.0)
    return {"deal": deal, "stage": "handoff"}


def onboarding_handoff(state: SalesState, deps: Deps) -> dict:
    """Log the onboarding handoff activity and route to CRM sync."""
    prospect: Prospect = state["prospect"]
    deps.crm.log_activity(
        prospect.lead_id,
        {"type": "onboarding_handoff", "deal": state.get("deal")},
    )
    return {"stage": "crm_sync"}
