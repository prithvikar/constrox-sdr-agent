"""Outreach nodes: cadence planning, multi-channel drafting, compliance gate, send.

Every node follows the mandatory contract:

    def node(state: SalesState, deps: Deps) -> dict:  # returns a partial state update

`deps` is bound via functools.partial at graph build time. Drafts and
compliance_results are additive list reducers: return a single-item list to
append one item.

LLM calls go through constrox_sdr.models (so tests can monkeypatch). Each
drafting node ships a deterministic local fallback so it works without an LLM.
"""
from __future__ import annotations

from typing import Optional

from .. import config, models
from ..adapters.base import Deps
from ..state import DraftArtifact, Prospect, SalesState

try:  # prompts.py is owned by another agent and may not exist yet.
    from .. import prompts  # type: ignore
except Exception:  # pragma: no cover - tolerated during parallel build
    prompts = None  # type: ignore


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def last_draft(state: SalesState) -> DraftArtifact:
    """Return the most recently appended draft."""
    return state["drafts"][-1]


def _prompt(name: str, default: str) -> str:
    """Reference prompts.<NAME> if present, else fall back to a local string."""
    return getattr(prompts, name, default) if prompts is not None else default


def _tier(state: SalesState) -> Optional[str]:
    score = state.get("score")
    return getattr(score, "tier", None)


def _segment(prospect: Prospect) -> str:
    return prospect.icp_segment or "unknown"


def _code_standard(prospect: Prospect) -> str:
    jur = prospect.jurisdiction
    return config.CODE_STANDARDS.get(jur or "", "AISC")


def _software(prospect: Prospect) -> str:
    """Pick a detailing-software mention (deterministic, segment-flavored)."""
    fw = (prospect.firmographics or {}).get("software")
    if isinstance(fw, str) and fw:
        return fw
    return config.DETAILING_SOFTWARE[0]  # Tekla


def _objection_preempt(prospect: Prospect) -> str:
    """One relevant objection pre-empt keyed off jurisdiction/segment."""
    jur = prospect.jurisdiction
    std = _code_standard(prospect)
    if jur == "US":
        return (f"Our detailers work to {std} and your GC/EOR standards daily, so "
                "connection design and shop drawings come back review-ready, not re-work.")
    if jur == "UK":
        return (f"We detail to {std} conventions and BS EN execution classes, so QA and "
                "code familiarity are not a gamble.")
    if jur == "AU":
        return (f"We work to {std} standards with local-equivalent QA sign-off, so quality "
                "and code familiarity are covered.")
    return ("Our QA process and code familiarity mean drawings come back review-ready, "
            "not as re-work.")


def _compliance_tail(prospect: Prospect) -> str:
    """Jurisdiction-correct legal footer so the compliance gate passes."""
    jur = prospect.jurisdiction
    if jur == "US":
        return f"\n\n{config.ORG.name}\n{config.ORG.address}\nReply STOP to opt out."
    if jur == "AU":
        return (f"\n\n{config.ORG.name} (ABN {config.ORG.abn}).\n"
                "Reply STOP to opt out.")
    if jur == "UK":
        return (f"\n\n{config.ORG.name}. We are reaching out because we noticed your "
                "steel detailing and fabrication work publicly listed.\n"
                "Reply STOP to opt out.")
    # Unknown jurisdiction: include everything we can.
    return (f"\n\n{config.ORG.name} (ABN {config.ORG.abn})\n{config.ORG.address}\n"
            "Reply STOP to opt out.")


# --------------------------------------------------------------------------- #
# Local fallback composers (no LLM)                                            #
# --------------------------------------------------------------------------- #
def compose_email_body(prospect: Prospect) -> str:
    name = prospect.contact_name or "there"
    company = prospect.company
    seg = _segment(prospect)
    std = _code_standard(prospect)
    sw = _software(prospect)
    body = (
        f"Hi {name},\n\n"
        f"I work with {company} and other {seg}s to add offshore steel detailing, BIM, "
        f"and estimation capacity without the overhead of new in-house hires.\n\n"
        f"Our team produces {std}-compliant shop and erection drawings in {sw}, plus "
        f"connection design support and quantity take-offs, on overnight turnarounds that "
        f"effectively extend your week.\n\n"
        f"{_objection_preempt(prospect)}\n\n"
        f"Worth a 15-minute call to see if we can take pressure off your detailing or "
        f"estimating queue?\n\n"
        f"Best,\nConstrox Team"
    )
    return body + _compliance_tail(prospect)


def compose_call_script(prospect: Prospect) -> str:
    name = prospect.contact_name or "there"
    company = prospect.company
    seg = _segment(prospect)
    std = _code_standard(prospect)
    sw = _software(prospect)
    return (
        f"COLD CALL SCRIPT — {company}\n\n"
        f"OPENER:\n"
        f"Hi {name}, this is Constrox. I'll be quick. We give {seg}s like {company} extra "
        f"steel detailing and estimation capacity in {sw}, {std}-compliant, on overnight "
        f"turnarounds. Did I catch you at an okay moment?\n\n"
        f"TALK TRACK:\n"
        f"- Most shops your size hit a wall when detailing backs up but hiring a detailer "
        f"is a 6-month commitment. We flex up and down per project.\n"
        f"- We act as an extension of your team in {sw}, to your {std} and EOR standards.\n"
        f"- You stay in control of QA and final sign-off.\n\n"
        f"OBJECTION CARDS:\n"
        f"1) QUALITY/QA: 'How do I know the drawings are good?' -> Every job runs a "
        f"two-stage internal QA to {std} before it reaches you; first job can be a paid "
        f"pilot so you judge the output, not a pitch.\n"
        f"2) CODE FAMILIARITY: 'Do you know our codes?' -> We detail to {std} and your GC/EOR "
        f"standards daily; we'll mirror your title blocks and conventions.\n"
        f"3) TIMEZONE: 'Offshore means delays.' -> Timezone is the advantage — you hand off "
        f"end of day, drawings are progressed overnight, back on your desk by morning.\n\n"
        f"CLOSE:\n"
        f"Can we put 15 minutes on the calendar this week to scope one live job?"
    )


def compose_linkedin(prospect: Prospect) -> str:
    name = (prospect.contact_name or "there").split(" ")[0]
    company = prospect.company
    seg = _segment(prospect)
    sw = _software(prospect)
    connect = (
        f"Hi {name}, I work with {seg}s on offshore steel detailing and estimation "
        f"capacity — would love to connect."
    )
    first_msg = (
        f"Thanks for connecting, {name}. We help teams like {company} flex detailing and "
        f"estimating capacity in {sw} without new hires — code-compliant drawings on "
        f"overnight turnarounds. Open to a quick 15-minute chat to see if it fits your "
        f"current pipeline?"
    )
    return f"CONNECTION NOTE:\n{connect}\n\nFIRST MESSAGE:\n{first_msg}"


# --------------------------------------------------------------------------- #
# Cadence planning                                                             #
# --------------------------------------------------------------------------- #
_CADENCE_BY_TIER = {
    "A": ["email", "linkedin", "call", "email"],
    "B": ["email", "email", "linkedin"],
    "C": ["email", "email"],
}

_PURPOSE = {
    "email": "value intro / re-touch",
    "linkedin": "social proof connection",
    "call": "live discovery conversation",
}


def plan_cadence(state: SalesState, deps: Deps) -> dict:
    """Build a channel cadence from tier + segment."""
    tier = _tier(state) or "C"
    channels = _CADENCE_BY_TIER.get(tier, _CADENCE_BY_TIER["C"])
    steps = [
        {"channel": ch, "step": i, "purpose": _PURPOSE.get(ch, "outreach")}
        for i, ch in enumerate(channels)
    ]
    return {"cadence": steps, "stage": "outreach"}


# --------------------------------------------------------------------------- #
# Drafting nodes                                                               #
# --------------------------------------------------------------------------- #
def _step_index(state: SalesState, channel: str) -> int:
    """Index of this draft among existing drafts of the same channel."""
    return sum(1 for d in state.get("drafts", []) if d.get("channel") == channel)


def email_draft(state: SalesState, deps: Deps) -> dict:
    """Draft a personalized email; LLM with deterministic local fallback."""
    prospect: Prospect = state["prospect"]
    tier = _tier(state)
    model_id = config.model_for("email_draft", tier)

    fallback = compose_email_body(prospect)
    system = _prompt(
        "EMAIL_DRAFT_SYSTEM",
        "You are an SDR for Constrox, an offshore steel detailing, BIM, and estimation "
        "partner. Write a concise, specific cold email. You MUST keep the legal footer "
        "(org identity, postal/ABN line, and opt-out) exactly as given.",
    )
    subject = f"Extra steel detailing capacity for {prospect.company}"
    body = fallback
    try:
        prompt = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Prospect: {prospect.contact_name} ({prospect.title}) at "
                    f"{prospect.company}. Segment: {_segment(prospect)}. "
                    f"Jurisdiction/code: {prospect.jurisdiction}/{_code_standard(prospect)}. "
                    f"Software: {_software(prospect)}. "
                    f"Pre-empt this objection: {_objection_preempt(prospect)}. "
                    f"Research notes: {prospect.research_notes or 'n/a'}.\n\n"
                    f"You MUST end the email with EXACTLY this footer (verbatim):"
                    f"{_compliance_tail(prospect)}\n\n"
                    f"Here is a known-good draft to improve on:\n{fallback}"
                ),
            },
        ]
        resp = models.llm("email_draft", tier=tier).invoke(prompt)
        text = getattr(resp, "content", None)
        if isinstance(text, str) and text.strip():
            body = text.strip()
    except Exception:
        body = fallback

    # Guarantee compliance elements survive any LLM rewrite.
    tail = _compliance_tail(prospect)
    if tail.strip() not in body:
        body = body + tail

    draft: DraftArtifact = {
        "channel": "email",
        "subject": subject,
        "body": body,
        "model_used": model_id,
        "approved": False,
        "sent": False,
        "step_index": _step_index(state, "email"),
    }
    return {"drafts": [draft]}


def call_script(state: SalesState, deps: Deps) -> dict:
    """Generate a cold-call script + talk track + 3 objection cards."""
    prospect: Prospect = state["prospect"]
    tier = _tier(state)
    model_id = config.model_for("call_script", tier)

    fallback = compose_call_script(prospect)
    system = _prompt(
        "CALL_SCRIPT_SYSTEM",
        "You write tight, natural cold-call scripts for Constrox SDRs selling offshore "
        "steel detailing and estimation capacity. Include an opener, a talk track, and "
        "exactly three objection cards.",
    )
    body = fallback
    try:
        prompt = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Prospect: {prospect.contact_name} ({prospect.title}) at "
                    f"{prospect.company}. Segment: {_segment(prospect)}. "
                    f"Code standard: {_code_standard(prospect)}. "
                    f"Software: {_software(prospect)}.\n\n"
                    f"Known-good draft to improve on:\n{fallback}"
                ),
            },
        ]
        # Tier A routes to the premium model via task="call_script".
        resp = models.llm("call_script", tier=tier).invoke(prompt)
        text = getattr(resp, "content", None)
        if isinstance(text, str) and text.strip():
            body = text.strip()
    except Exception:
        body = fallback

    draft: DraftArtifact = {
        "channel": "call",
        "subject": None,
        "body": body,
        "model_used": model_id,
        "approved": False,
        "sent": False,
        "step_index": _step_index(state, "call"),
    }
    return {"drafts": [draft]}


def linkedin_draft(state: SalesState, deps: Deps) -> dict:
    """Short connection note + first message."""
    prospect: Prospect = state["prospect"]
    tier = _tier(state)
    model_id = config.model_for("linkedin_draft", tier)

    fallback = compose_linkedin(prospect)
    system = _prompt(
        "LINKEDIN_DRAFT_SYSTEM",
        "You write short, human LinkedIn connection notes and first messages for a "
        "Constrox SDR. Output a connection note (under 300 chars) and a first message. "
        "Never sound automated.",
    )
    body = fallback
    try:
        prompt = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Prospect: {prospect.contact_name} ({prospect.title}) at "
                    f"{prospect.company}. Segment: {_segment(prospect)}. "
                    f"Software: {_software(prospect)}.\n\n"
                    f"Known-good draft to improve on:\n{fallback}"
                ),
            },
        ]
        resp = models.llm("linkedin_draft", tier=tier).invoke(prompt)
        text = getattr(resp, "content", None)
        if isinstance(text, str) and text.strip():
            body = text.strip()
    except Exception:
        body = fallback

    draft: DraftArtifact = {
        "channel": "linkedin",
        "subject": None,
        "body": body,
        "model_used": model_id,
        "approved": False,
        "sent": False,
        "step_index": _step_index(state, "linkedin"),
    }
    return {"drafts": [draft]}


# --------------------------------------------------------------------------- #
# Compliance gate node                                                         #
# --------------------------------------------------------------------------- #
def compliance_gate(state: SalesState, deps: Deps) -> dict:
    """Run the deterministic compliance gate on the last draft."""
    from ..compliance import run_compliance_gate

    prospect: Prospect = state["prospect"]
    draft = last_draft(state)
    result = run_compliance_gate(prospect, draft, deps)
    if result.passed:
        return {"compliance_results": [result.record], "stage": "outreach"}
    return {
        "compliance_results": [result.record],
        "stage": "blocked",
        "error": result.failing_rule,
    }


# --------------------------------------------------------------------------- #
# Dispatch nodes                                                               #
# --------------------------------------------------------------------------- #
def email_send(state: SalesState, deps: Deps) -> dict:
    """Send the last (email) draft and append a sent marker."""
    prospect: Prospect = state["prospect"]
    draft = last_draft(state)
    deps.email.send(
        prospect.email or "",
        draft.get("subject") or "",
        draft.get("body", ""),
        headers={"From": config.ORG.name},
    )
    return {"drafts": [{**draft, "sent": True}], "stage": "await_reply"}


def queue_dialer(state: SalesState, deps: Deps) -> dict:
    """Queue the last (call) draft for a human dialer."""
    prospect: Prospect = state["prospect"]
    draft = last_draft(state)
    deps.dialer.queue_call(prospect.lead_id, draft.get("body", ""))
    return {"drafts": [{**draft, "sent": True}], "stage": "await_reply"}


def queue_linkedin(state: SalesState, deps: Deps) -> dict:
    """Queue the last (linkedin) draft for a human to send in LinkedIn's UI."""
    prospect: Prospect = state["prospect"]
    draft = last_draft(state)
    deps.linkedin.queue_draft(prospect.lead_id, "message", draft.get("body", ""))
    return {"drafts": [{**draft, "sent": True}], "stage": "await_reply"}
