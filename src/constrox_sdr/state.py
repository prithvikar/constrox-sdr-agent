"""LangGraph state schema + structured LLM I/O models.

Two kinds of types live here:
  * Pydantic models  -> structured LLM output / tool args (validated)
  * SalesState (TypedDict) -> the LangGraph graph state, with reducers

Commission/invoice records intentionally live OUTSIDE SalesState (see
commission.py): they are an async side-loop keyed by deal_id, not part of the
linear prospect thread.
"""
from __future__ import annotations

from operator import add
from typing import Annotated, Literal, Optional, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Enums / literals                                                            #
# --------------------------------------------------------------------------- #
Channel = Literal["email", "call", "linkedin"]
Jurisdiction = Literal["US", "UK", "AU"]
Tier = Literal["A", "B", "C", "disqualify"]
Stage = Literal[
    "research", "score", "suppress", "outreach", "await_reply", "reply",
    "discovery", "demo", "negotiate", "close", "handoff",
    "crm_sync", "done", "disqualified", "blocked",
]
ICPSegment = Literal["fabricator", "gc", "consultancy", "precast_rebar", "other", "unknown"]
EntityType = Literal["company", "llp", "plc", "sole_trader", "partnership", "gov", "unknown"]
PhoneType = Literal["business_landline", "mobile", "unknown"]


# --------------------------------------------------------------------------- #
# Pydantic: structured LLM I/O & tool args (NOT graph state)                   #
# --------------------------------------------------------------------------- #
class Prospect(BaseModel):
    lead_id: str
    company: str
    domain: Optional[str] = None
    contact_name: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    phone_type: PhoneType = "unknown"
    linkedin_url: Optional[str] = None
    jurisdiction: Optional[Jurisdiction] = None
    timezone: Optional[str] = None
    entity_type: EntityType = "unknown"
    firmographics: dict = Field(default_factory=dict)
    research_notes: str = ""
    icp_segment: ICPSegment = "unknown"
    # consent / lawful-basis flags used by the compliance gate
    has_consent: bool = False
    has_soft_optin: bool = False


class LeadScore(BaseModel):
    fit: int = Field(ge=0, le=100)
    intent: int = Field(ge=0, le=100)
    tier: Tier
    rationale: str


ReplyIntent = Literal[
    "interested", "not_interested", "objection", "referral",
    "ooo_autoreply", "unsubscribe", "meeting_request",
]
ObjectionType = Literal[
    "quality_qa", "code_familiarity", "timezone", "software_compat",
    "liability_ip", "incumbent", "pricing", "trust_references",
]


class ReplyClass(BaseModel):
    intent: ReplyIntent
    sentiment: Literal["positive", "neutral", "negative"]
    objection_type: Optional[ObjectionType] = None
    suggested_next: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class BANT(BaseModel):
    budget: Optional[str] = None
    authority: Optional[str] = None
    need: Optional[str] = None
    timeline: Optional[str] = None
    pain: Optional[str] = None
    qualified: bool = False


class ComplianceResult(BaseModel):
    passed: bool
    channel: Channel
    jurisdiction: Optional[Jurisdiction] = None
    failing_rule: Optional[str] = None
    lawful_basis: Optional[str] = None
    scrub_fresh: bool = False
    record: dict = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Graph state (TypedDict)                                                      #
# --------------------------------------------------------------------------- #
class DraftArtifact(TypedDict, total=False):
    channel: Channel
    subject: Optional[str]
    body: str
    model_used: str
    approved: bool          # human approved (call/linkedin/tier-a)
    sent: bool              # email=actually sent; call/linkedin=queued-for-human
    compliance: Optional[dict]
    created_at: str
    step_index: int


class DealRecord(TypedDict, total=False):
    deal_id: Optional[str]
    stage: Literal["open", "discovery", "demo", "negotiation", "won", "lost"]
    pipeline_value: float   # expected MONTHLY billing
    recurring: bool
    expected_close: Optional[str]
    won_amount: float
    lost_reason: Optional[str]


class SalesState(TypedDict, total=False):
    prospect: Prospect
    messages: Annotated[list[AnyMessage], add_messages]
    score: Optional[LeadScore]
    drafts: Annotated[list[DraftArtifact], add]
    cadence: Optional[list[dict]]
    inbound_reply: Optional[str]
    reply_class: Optional[ReplyClass]
    bant: Optional[BANT]
    deal: Optional[DealRecord]
    stage: Stage
    crm_synced: bool
    compliance_results: Annotated[list[dict], add]
    human_decision: Optional[dict]
    error: Optional[str]


def initial_state(prospect: Prospect) -> SalesState:
    """Build a fresh SalesState for a prospect entering the graph."""
    return {
        "prospect": prospect,
        "messages": [],
        "score": None,
        "drafts": [],
        "cadence": None,
        "inbound_reply": None,
        "reply_class": None,
        "bant": None,
        "deal": None,
        "stage": "research",
        "crm_synced": False,
        "compliance_results": [],
        "human_decision": None,
        "error": None,
    }
