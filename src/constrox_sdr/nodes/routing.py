"""Pure routing functions: (state) -> next-node name.

These are conditional-edge predicates for the LangGraph build. They take only the
state (no deps) and must be side-effect free and deterministic.
"""
from __future__ import annotations

from .. import config
from ..state import SalesState


# --------------------------------------------------------------------------- #
# Scoring / suppression                                                       #
# --------------------------------------------------------------------------- #
def route_after_score(s: SalesState) -> str:
    score = s.get("score")
    if score is None or score.tier == "disqualify":
        return "disqualify"
    return "suppress"


def route_after_suppress(s: SalesState) -> str:
    return "blocked" if s.get("stage") == "blocked" else "plan_cadence"


# --------------------------------------------------------------------------- #
# Channel / compliance                                                        #
# --------------------------------------------------------------------------- #
def route_channel(s: SalesState) -> str:
    return s["cadence"][0]["channel"]


def route_after_email_compliance(s: SalesState) -> str:
    return "email_send" if s["compliance_results"][-1]["passed"] else "blocked"


def route_after_call_compliance(s: SalesState) -> str:
    return "queue_dialer" if s["compliance_results"][-1]["passed"] else "blocked"


# --------------------------------------------------------------------------- #
# Reply / discovery / negotiation                                            #
# --------------------------------------------------------------------------- #
def route_after_reply(s: SalesState) -> str:
    rc = s.get("reply_class")
    if rc is None:
        return "nurture_or_terminate"
    if rc.intent in ("interested", "meeting_request"):
        return "book_discovery"
    if rc.intent in ("objection", "referral"):
        return "handle_objection"
    return "nurture_or_terminate"


def route_after_discovery(s: SalesState) -> str:
    bant = s.get("bant")
    return "schedule_demo" if bant and bant.qualified else "nurture_or_terminate"


def needs_pricing_approval(s: SalesState) -> bool:
    """True when a deal's monthly value is below the human-approval floor."""
    deal = s.get("deal")
    return bool(deal and deal.get("pipeline_value", 0) < 2000)


def route_after_negotiate(s: SalesState) -> str:
    return "pricing_gate" if needs_pricing_approval(s) else "close_deal"
