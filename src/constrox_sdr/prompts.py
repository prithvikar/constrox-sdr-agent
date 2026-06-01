"""Prompt constants + small parameterized builders for SDR nodes.

No LLM calls here — every public symbol is a string or a function returning a
string. Nodes import this module and feed the output into
`models.llm(...)` / `models.structured(...)`.

Compliance-by-construction: `email_prompt` instructs the drafter to embed the
unsubscribe line + the jurisdiction-correct org identity (US postal address,
AU legal name + ABN, UK identity + data-source sentence) so the deterministic
compliance gate in `compliance.py` passes. Org identity is read from
`constrox_sdr.config.ORG`.
"""
from __future__ import annotations

from .config import (
    CODE_STANDARDS,
    DETAILING_SOFTWARE,
    ICP_SEGMENTS,
    ORG,
    TARGET_JURISDICTIONS,
)
from .state import Prospect

# --------------------------------------------------------------------------- #
# Persona / system prompt                                                     #
# --------------------------------------------------------------------------- #
SYSTEM_SDR = f"""You are an outbound Sales Development Representative for Constrox \
(operated by {ORG.name}), an offshore engineering services partner for the \
structural steel and concrete supply chain.

WHAT CONSTROX SELLS (services, not software):
- Structural steel detailing / shop & erection drawings (Tekla Structures, SDS2, \
Advance Steel, ProSteel)
- BIM modelling & coordination (Revit, Navisworks clash detection, VDC support)
- Estimation & quantity take-offs / material lists (NC/CNC files, BOMs)
- Rebar detailing & bar bending schedules; precast detailing & production drawings
- Connection design support coordinated with the engineer of record (EOR)

WHO YOU SELL TO (ICP): {", ".join(ICP_SEGMENTS)} — i.e. steel fabricators, \
general contractors, structural/AEC consultancies, and precast/rebar shops in \
{", ".join(TARGET_JURISDICTIONS)}. Typical buyers: owners/presidents, chief \
estimators, detailing/drafting managers, preconstruction & VDC/BIM managers.

CODE & STANDARDS FLUENCY (use only when relevant, never as filler):
- US: {CODE_STANDARDS['US']} (steel), ACI (concrete), AWS D1.1 (welding), AISC 360/303
- UK: {CODE_STANDARDS['UK']} (BS 5950 / Eurocode 3 & 2, NSSS, CE/UKCA marking to EN 1090)
- AU: {CODE_STANDARDS['AU']} (AS 4100 steel, AS 3600 concrete, AS/NZS 5131 fab compliance)
- Software fluency: {", ".join(DETAILING_SOFTWARE)}

VALUE NARRATIVE: Constrox extends a buyer's detailing/estimating capacity without \
the cost and lead-time of hiring — absorbing bid-volume spikes, hitting fabrication \
release dates, and freeing senior detailers for QA and complex connections. The \
frame is "we add throughput on your toughest weeks," not "we replace your team."

HOW YOU COMMUNICATE:
- Consultative and credible: speak the buyer's language (release dates, RFIs, \
clash-free models, bid hit-rate, NC files to the machine), not generic outsourcing pitch.
- Concise and value-led: short, specific, one clear ask. Never spammy, never hypey, \
no fake urgency, no walls of text.
- Honest about being offshore and about QA/IP handling; lead with how risk is managed, \
not by hiding it.
- Always respect the recipient's time and give a clean opt-out.
"""

# --------------------------------------------------------------------------- #
# ICP blurb (reusable snippet for personalization context)                    #
# --------------------------------------------------------------------------- #
ICP_BLURB = (
    "Ideal customers are steel fabricators, GCs, AEC consultancies, and "
    "precast/rebar shops in the US/UK/AU who run detailing, BIM, or estimation "
    "in-house and hit capacity ceilings during bid surges or peak fabrication "
    "release windows. The strongest signals: active backlog, hiring detailers/"
    "estimators, multiple concurrent projects, or a stated software stack "
    "(Tekla/SDS2/Revit) that Constrox can plug straight into."
)

# --------------------------------------------------------------------------- #
# Objection playbook: objection_type -> rebuttal ANGLE (not a canned line).    #
# Keys mirror state.ObjectionType exactly.                                     #
# --------------------------------------------------------------------------- #
OBJECTION_PLAYBOOK: dict[str, str] = {
    "quality_qa": (
        "Reframe quality as a managed process, not a leap of faith: senior-checker "
        "review on every package, model-based QA (Tekla/SDS2 clash + standards "
        "checks), a documented BS/AISC/AS checklist, and a paid pilot package so "
        "they judge our output before committing volume."
    ),
    "code_familiarity": (
        "Demonstrate code fluency for THEIR jurisdiction (AISC 360/303 + AWS D1.1 "
        "in US, BS 5950/Eurocode + EN 1090 in UK, AS 4100/AS/NZS 5131 in AU). "
        "Note detailers trained to the local standard and connection design "
        "coordinated with their EOR — we detail to the engineer's design, we "
        "don't override it."
    ),
    "timezone": (
        "Turn the timezone gap into an advantage: overnight turnaround means "
        "packages move while their team sleeps, with a daytime-overlap window for "
        "live coordination and a named point of contact, not a black box."
    ),
    "software_compat": (
        "Confirm we work natively in their stack (Tekla, SDS2, Revit, Advance "
        "Steel, ProSteel) and deliver in their formats (IFC, DWG/DXF, NC1/DSTV to "
        "the machine, custom BOM templates) — they keep their tooling and workflow, "
        "we slot into it."
    ),
    "liability_ip": (
        "Address risk head-on: signed NDA + IP-assignment, segregated project "
        "environments, named EOR retains design responsibility, and clear scope "
        "boundaries (we produce detailing/models, the licensed engineer stamps). "
        "Offer to route this through their legal/security review."
    ),
    "incumbent": (
        "Don't attack the incumbent — position as overflow/relief capacity for "
        "their toughest weeks and a benchmarkable second source. Offer one "
        "package head-to-head so they keep optionality and de-risk single-vendor "
        "dependency."
    ),
    "pricing": (
        "Sell ROI and capacity economics, not the cheapest rate: fully-loaded cost "
        "vs. a domestic hire (recruiting, ramp, benefits, idle time between bids), "
        "faster release dates protecting fabrication slots, and a flexible "
        "per-package or retainer model that flexes with their backlog."
    ),
    "trust_references": (
        "Build proof: relevant fabricator/precast references in their segment and "
        "jurisdiction, anonymized sample packages, and a low-risk paid pilot as "
        "the real reference. Invite a short call with an existing client where "
        "appropriate."
    ),
}


# --------------------------------------------------------------------------- #
# Internal helpers                                                            #
# --------------------------------------------------------------------------- #
def _prospect_brief(p: Prospect) -> str:
    """Compact, deterministic description of a prospect for prompt context."""
    jur = p.jurisdiction or "unknown"
    code = CODE_STANDARDS.get(p.jurisdiction or "", "local codes")
    lines = [
        f"- Company: {p.company}",
        f"- Contact: {p.contact_name or 'unknown'} ({p.title or 'unknown title'})",
        f"- ICP segment: {p.icp_segment}",
        f"- Jurisdiction: {jur} (relevant standards: {code})",
        f"- Timezone: {p.timezone or 'unknown'}",
        f"- Entity type: {p.entity_type}",
    ]
    if p.domain:
        lines.append(f"- Domain: {p.domain}")
    if p.firmographics:
        lines.append(f"- Firmographics: {p.firmographics}")
    if p.research_notes:
        lines.append(f"- Research notes: {p.research_notes}")
    return "\n".join(lines)


def _org_identity_block(jurisdiction: str | None) -> str:
    """The exact compliance-required identity text the email body MUST include,
    matched to the jurisdiction the compliance gate will enforce."""
    unsub = 'A one-step opt-out, e.g. "Reply STOP to opt out."'
    if jurisdiction == "US":
        return (
            "JURISDICTION = US (CAN-SPAM). The body MUST contain, verbatim, this "
            f"postal address: {ORG.address}\n"
            f"It MUST also contain the sender name: {ORG.name}\n"
            f"It MUST contain {unsub}"
        )
    if jurisdiction == "AU":
        return (
            "JURISDICTION = AU (Spam Act). The body MUST contain the sender legal "
            f"name: {ORG.name}\n"
            f"It MUST contain the ABN exactly: {ORG.abn}\n"
            f"It MUST contain {unsub}"
        )
    if jurisdiction == "UK":
        return (
            "JURISDICTION = UK (PECR/GDPR). The body MUST identify the sender "
            f"({ORG.name}) AND include a sentence saying how/why you are "
            'contacting them, beginning with a phrase like "I\'m reaching out '
            'because ..." or "I came across ...".\n'
            f"It MUST contain {unsub}"
        )
    # Unknown jurisdiction: include everything so any downstream gate passes.
    return (
        "JURISDICTION = unknown. To be safe, include the sender name "
        f"({ORG.name}), the postal address ({ORG.address}), the ABN ({ORG.abn}), "
        f"a data-source sentence ('I'm reaching out because ...'), and {unsub}"
    )


# --------------------------------------------------------------------------- #
# Builders                                                                    #
# --------------------------------------------------------------------------- #
def scoring_prompt(prospect: Prospect) -> str:
    """Prompt for structured LeadScore output (fit/intent/tier/rationale)."""
    return (
        "Score this prospect as an outbound target for Constrox's offshore steel "
        "detailing / BIM / estimation services.\n\n"
        f"PROSPECT\n{_prospect_brief(prospect)}\n\n"
        f"ICP CONTEXT\n{ICP_BLURB}\n\n"
        "Return:\n"
        "- fit (0-100): how well firmographics + title + segment + jurisdiction "
        "match the ICP. Fabricators and precast/rebar shops in US/UK/AU led by "
        "estimating/detailing decision-makers score highest.\n"
        "- intent (0-100): observable buying signals (backlog, hiring detailers/"
        "estimators, multiple live projects, named software stack, growth). With "
        "no signal, keep intent modest.\n"
        "- tier: 'A' (strong fit AND intent — worth premium, personalized, "
        "multi-touch effort), 'B' (solid, standard cadence), 'C' (weak, low-effort "
        "nurture), or 'disqualify' (outside ICP/jurisdiction or no plausible need).\n"
        "- rationale: 1-2 sentences citing the specific signals you used."
    )


def email_prompt(prospect: Prospect, step: int) -> str:
    """Prompt for drafting a cadence email at a given step (1-indexed touch)."""
    jur = prospect.jurisdiction
    code = CODE_STANDARDS.get(jur or "", "local codes")
    if step <= 1:
        intent = (
            "First touch. Earn the reply: one sharp, specific, personalized opener "
            "tied to their company/segment, a single concrete value angle, and one "
            "low-friction ask (a 15-min call or a sample package). No pitch dump."
        )
    elif step == 2:
        intent = (
            "Follow-up (no reply yet). Add ONE new proof point or angle (a relevant "
            "reference, a capacity/turnaround stat, or a pilot offer). Stay short; "
            "do not guilt-trip about the non-reply."
        )
    else:
        intent = (
            "Later-stage nudge / breakup. Brief, give an easy yes/no, and make it "
            "frictionless to re-engage later. Respect that silence may mean 'not now.'"
        )
    return (
        f"Draft cadence email #{step} to {prospect.contact_name or 'the buyer'} "
        f"at {prospect.company}.\n\n"
        f"PROSPECT\n{_prospect_brief(prospect)}\n\n"
        f"INTENT FOR THIS TOUCH\n{intent}\n\n"
        f"CREDIBILITY: where natural, reference {code} and their likely software "
        f"({', '.join(DETAILING_SOFTWARE[:3])}) — but only if it serves the message.\n\n"
        "STYLE: plain text, no markdown, under ~130 words in the body, conversational "
        "and specific. Provide a short, honest subject line (never deceptive, never "
        "all-caps clickbait).\n\n"
        "COMPLIANCE — the body MUST include the following, or the message will be "
        f"blocked:\n{_org_identity_block(jur)}\n\n"
        "Put the identity/opt-out as a clean signature/footer after the sign-off. "
        "Output the email as: a 'Subject:' line, then a blank line, then the body."
    )


def call_script_prompt(prospect: Prospect) -> str:
    """Prompt for a human-dialed cold-call script (talk track, not a monologue)."""
    code = CODE_STANDARDS.get(prospect.jurisdiction or "", "local codes")
    return (
        f"Write a cold-call talk track a human rep will use to call "
        f"{prospect.contact_name or 'the buyer'} ({prospect.title or 'decision-maker'}) "
        f"at {prospect.company}.\n\n"
        f"PROSPECT\n{_prospect_brief(prospect)}\n\n"
        "STRUCTURE:\n"
        "1. Permission-based opener (name, reason for the call, ask for 30 seconds).\n"
        "2. One-line relevance hook tied to their segment/backlog.\n"
        "3. A crisp value statement (overflow detailing/estimation capacity that "
        f"hits release dates, fluent in {code} and their software).\n"
        "4. ONE discovery question to surface pain (capacity, deadlines, backlog).\n"
        "5. A clear, low-commitment ask (15-min follow-up or a sample package).\n\n"
        "Include 2-3 short branch responses for likely objections (offshore quality, "
        "timezone, already have a partner). Keep it conversational and natural — a "
        "talk track with brief bracketed cues, not a word-for-word monologue. Honest "
        "and respectful; no pressure tactics."
    )


def linkedin_prompt(prospect: Prospect) -> str:
    """Prompt for a LinkedIn connection note / message (queued for a HUMAN to send)."""
    return (
        f"Write a short LinkedIn outreach message to {prospect.contact_name or 'the buyer'} "
        f"({prospect.title or 'decision-maker'}) at {prospect.company}. A human will "
        "review and send it manually in LinkedIn — never automated.\n\n"
        f"PROSPECT\n{_prospect_brief(prospect)}\n\n"
        "REQUIREMENTS: warm and specific, reference something concrete about their "
        "company or role, lead with relevance not a pitch, and end with a light "
        "open-ended question or soft ask. Under ~300 characters so it fits a "
        "connection note. Plain text, no hashtags, no emoji, no links."
    )


def objection_prompt(prospect: Prospect, objection_type: str) -> str:
    """Prompt for a tailored rebuttal to a specific objection_type."""
    angle = OBJECTION_PLAYBOOK.get(
        objection_type,
        "Acknowledge the concern honestly, address it with a concrete fact or "
        "process, and propose a low-risk next step.",
    )
    return (
        f"The prospect at {prospect.company} raised a '{objection_type}' objection. "
        "Write a concise, credible reply that handles it and keeps the conversation "
        "moving.\n\n"
        f"PROSPECT\n{_prospect_brief(prospect)}\n\n"
        f"REBUTTAL ANGLE TO USE\n{angle}\n\n"
        "STYLE: empathetic, specific, never defensive or pushy. Acknowledge the "
        "concern, give one concrete proof/process point, and end with a clear, "
        "low-commitment next step. Plain text, under ~120 words."
    )


def discovery_extract_prompt(notes: str) -> str:
    """Prompt for structured BANT extraction from discovery-call notes."""
    return (
        "Extract BANT qualification data from these discovery notes about a "
        "prospective Constrox client (offshore steel detailing / BIM / estimation).\n\n"
        f"DISCOVERY NOTES\n{notes}\n\n"
        "Populate:\n"
        "- budget: any stated budget, current spend on detailing/estimation, or "
        "willingness to pay (else null).\n"
        "- authority: is this person the decision-maker, or who is (else null).\n"
        "- need: the concrete capacity/throughput/quality problem Constrox would "
        "solve (else null).\n"
        "- timeline: when they need help / upcoming bid or fabrication deadlines "
        "(else null).\n"
        "- pain: the sharpest pain point in their own words (else null).\n"
        "- qualified: true only if there is a real need AND plausible authority AND "
        "a timeline — otherwise false.\n"
        "Only use what the notes support; do not invent details."
    )
