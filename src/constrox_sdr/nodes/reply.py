"""Reply-handling nodes: classify inbound replies and draft objection rebuttals.

`classify_reply` routes inbound text to a ReplyClass (LLM-first, heuristic
fallback). `handle_objection` drafts a tailored rebuttal email selling Constrox's
QA / process, with the compliance elements every email must carry.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import models
from ..config import CODE_STANDARDS, ORG
from ..state import (
    DraftArtifact,
    ObjectionType,
    Prospect,
    ReplyClass,
    SalesState,
)
from ..adapters.base import Deps

try:  # prompts.py is owned by another agent; tolerate absence.
    from .. import prompts  # type: ignore
except Exception:  # pragma: no cover - import-safety only
    prompts = None  # type: ignore


# --------------------------------------------------------------------------- #
# Heuristic fallback                                                          #
# --------------------------------------------------------------------------- #
_OBJECTION_KEYWORDS: list[tuple[tuple[str, ...], ObjectionType]] = [
    (("aisc", "code", "eurocode", "standard"), "code_familiarity"),
    (("quality", "qa", "qc"), "quality_qa"),
    (("price", "cost", "expensive", "budget"), "pricing"),
    (("already use", "incumbent", "current provider", "existing vendor"), "incumbent"),
    (("samples", "references", "case stud", "portfolio"), "trust_references"),
    (("timezone", "turnaround", "time zone", "lead time"), "timezone"),
    (("tekla", "revit", "sds2", "sds/2", "software", "autocad", "advance steel"), "software_compat"),
    (("liability", "ip", "intellectual property", "indemnif"), "liability_ip"),
]


def _guess_objection_type(text: str) -> ObjectionType | None:
    low = text.lower()
    for keywords, otype in _OBJECTION_KEYWORDS:
        if any(k in low for k in keywords):
            return otype
    return None


def classify_reply_heuristic(text: str) -> ReplyClass:
    """Deterministic keyword classifier used when the LLM is unavailable."""
    low = (text or "").lower()

    if "unsubscribe" in low or "stop" in low:
        return ReplyClass(intent="unsubscribe", sentiment="negative",
                          suggested_next="suppress and stop all outreach", confidence=0.9)
    if "not interested" in low or "no thanks" in low or "no thank you" in low:
        return ReplyClass(intent="not_interested", sentiment="negative",
                          suggested_next="nurture or terminate", confidence=0.8)
    if "out of office" in low or "ooo" in low or "on leave" in low or "annual leave" in low:
        return ReplyClass(intent="ooo_autoreply", sentiment="neutral",
                          suggested_next="retry after return date", confidence=0.9)
    if any(k in low for k in ("call me", "interested", "book", "demo", "let's talk",
                              "lets talk", "schedule", "meeting")):
        return ReplyClass(intent="interested", sentiment="positive",
                          suggested_next="book a discovery call", confidence=0.8)

    otype = _guess_objection_type(low)
    if otype or "?" in low:
        return ReplyClass(intent="objection", sentiment="neutral",
                          objection_type=otype, suggested_next="handle objection",
                          confidence=0.6)

    return ReplyClass(intent="not_interested", sentiment="neutral",
                      suggested_next="nurture or terminate", confidence=0.4)


# --------------------------------------------------------------------------- #
# Nodes                                                                       #
# --------------------------------------------------------------------------- #
def classify_reply(state: SalesState, deps: Deps) -> dict:
    """Classify the inbound reply into a ReplyClass (LLM-first, heuristic fallback)."""
    text = state.get("inbound_reply") or ""
    try:
        prompt = prompts.reply_classification_prompt(text) if prompts else text
        rc = models.structured("classify_reply", ReplyClass).invoke(prompt)
    except Exception:
        rc = classify_reply_heuristic(text)
    if not isinstance(rc, ReplyClass):
        rc = classify_reply_heuristic(text)
    return {"reply_class": rc, "stage": "reply"}


def _objection_angle(otype: ObjectionType | None, prospect: Prospect) -> str:
    """Return the QA/process selling angle for a given objection type."""
    std = CODE_STANDARDS.get(prospect.jurisdiction or "US", "AISC")
    angles: dict[str, str] = {
        "quality_qa": (
            "every package runs through a three-stage internal QA gate (detailer -> "
            "checker -> senior reviewer) with a documented error log before it reaches you"
        ),
        "code_familiarity": (
            f"our detailers work to {std} day to day and we map every connection to the "
            f"governing code clause on the drawing"
        ),
        "timezone": (
            "our offshore shift overlaps your morning hours, so RFIs raised at end-of-day "
            "are answered before your next start — effectively a 24-hour turnaround"
        ),
        "software_compat": (
            "we model natively in Tekla, SDS2, Revit and Advance Steel and deliver in your "
            "preferred format, so there is no rework on import"
        ),
        "liability_ip": (
            "all work is covered by a signed IP-assignment and confidentiality agreement, and "
            "we carry professional indemnity cover on every engagement"
        ),
        "incumbent": (
            "most clients start us on overflow or a single trial package alongside their "
            "current provider — no switching cost, you just compare the output"
        ),
        "pricing": (
            "our per-tonne rate typically lands 30-40% below in-house cost once you account "
            "for overhead, and we scale up or down with no idle-bench charge"
        ),
        "trust_references": (
            "I can send anonymised sample packages and connect you with two reference clients "
            "in your segment before you commit a dollar"
        ),
    }
    if otype and otype in angles:
        return angles[otype]
    return angles["quality_qa"]


def _compliance_footer(prospect: Prospect) -> str:
    """Build the jurisdiction-correct legal footer the compliance gate requires."""
    jur = prospect.jurisdiction
    lines = ["", "Reply STOP to opt out."]
    if jur == "AU":
        lines.append(f"{ORG.name} | ABN {ORG.abn}")
    elif jur == "UK":
        lines.append(
            f"{ORG.name} — you are receiving this because we came across "
            f"{prospect.company} while researching steel fabricators in your region."
        )
    else:  # US (default)
        lines.append(ORG.address)
    return "\n".join(lines)


def handle_objection(state: SalesState, deps: Deps) -> dict:
    """Draft a tailored rebuttal email for the classified objection type."""
    prospect: Prospect = state["prospect"]
    rc = state.get("reply_class")
    otype = rc.objection_type if rc else None
    angle = _objection_angle(otype, prospect)
    name = prospect.contact_name or "there"
    footer = _compliance_footer(prospect)

    subject = f"Re: {prospect.company} — addressing your question"

    fallback_body = (
        f"Hi {name},\n\n"
        f"Thanks for the candid response — it's a fair point to raise.\n\n"
        f"On that specifically: {angle}.\n\n"
        f"Happy to put numbers and proof behind that with a sample package, no commitment. "
        f"Would a short call next week work to walk through it?\n\n"
        f"Best,\nThe Constrox team"
        f"{footer}"
    )

    body = fallback_body
    try:
        prompt = getattr(prompts, "HANDLE_OBJECTION_PROMPT", None) if prompts else None
        if prompt is not None:
            instruction = prompt.format(
                contact_name=name, company=prospect.company,
                objection_type=otype or "general", angle=angle,
                jurisdiction=prospect.jurisdiction or "US",
            )
        else:
            instruction = (
                f"Write a concise, warm rebuttal email to {name} at {prospect.company}. "
                f"They raised an objection of type '{otype or 'general'}'. "
                f"Lead with this proof point: {angle}. End with a soft call-to-action for a "
                f"short call. Do NOT include any signature, legal footer, or unsubscribe line — "
                f"those are appended separately. Keep it under 120 words."
            )
        resp = models.llm("handle_objection").invoke(instruction)
        text = (getattr(resp, "content", "") or "").strip()
        if text:
            body = f"{text}{footer}"
    except Exception:
        body = fallback_body

    draft: DraftArtifact = {
        "channel": "email",
        "subject": subject,
        "body": body,
        "model_used": "handle_objection",
        "approved": False,
        "sent": False,
        "compliance": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "step_index": len(state.get("drafts") or []),
    }
    # Consume the reply so the next await_reply waits for a NEW inbound message
    # instead of re-classifying this same objection (which would loop forever).
    return {"drafts": [draft], "inbound_reply": None, "stage": "outreach"}
