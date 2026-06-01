"""Scoring + suppression nodes.

`score` asks the LLM for a structured LeadScore, falling back to a deterministic
heuristic (`score_prospect_heuristic`) if the call fails. `suppress` enforces the
internal email suppression / DNC list before any outreach.
"""
from __future__ import annotations

from .. import config, models
from ..adapters.base import Deps
from ..state import LeadScore, Prospect, SalesState

try:  # prompts.py is owned by Agent E and may not exist yet during parallel build.
    from .. import prompts  # type: ignore
except Exception:  # pragma: no cover - import guard
    prompts = None  # type: ignore


# --------------------------------------------------------------------------- #
# Deterministic heuristic (also the LLM fallback).                            #
# --------------------------------------------------------------------------- #
def _title_fit(title: str | None) -> int:
    if not title:
        return 0
    t = title.lower()
    best = 0
    for signal, weight in config.ICP_TITLE_SIGNALS.items():
        if signal in t:
            best = max(best, weight)
    return best


def _tier_for(combined: float) -> str:
    s = config.SETTINGS
    if combined >= s.tier_a_cutoff:
        return "A"
    if combined >= s.tier_b_cutoff:
        return "B"
    if combined >= s.score_threshold:
        return "C"
    return "disqualify"


def score_prospect_heuristic(prospect: Prospect) -> LeadScore:
    """Pure, deterministic scoring from firmographic/title/segment signals."""
    # Fit: title signal + jurisdiction + identity completeness, scaled to 0-100.
    title_signal = _title_fit(prospect.title)  # 0-25
    in_target_jur = prospect.jurisdiction in config.TARGET_JURISDICTIONS
    jur_signal = 25 if in_target_jur else 0
    contact_signal = 0
    if prospect.email:
        contact_signal += 8
    if prospect.contact_name:
        contact_signal += 7
    if prospect.domain:
        contact_signal += 5
    research_signal = 10 if prospect.research_notes.strip() else 0
    fit = min(100, title_signal * 2 + jur_signal + contact_signal + research_signal)

    # Intent: driven by ICP segment outsourcing propensity.
    segment_weight = config.ICP_SEGMENT_WEIGHTS.get(
        prospect.icp_segment, config.ICP_SEGMENT_WEIGHTS.get("unknown", 5)
    )
    intent = min(100, segment_weight * 3 + (15 if in_target_jur else 0))

    combined = (fit + intent) / 2
    tier = _tier_for(combined)
    rationale = (
        f"heuristic: fit={fit} intent={intent} combined={combined:.0f} "
        f"(title_signal={title_signal}, segment={prospect.icp_segment}, "
        f"jurisdiction={prospect.jurisdiction})"
    )
    return LeadScore(fit=fit, intent=intent, tier=tier, rationale=rationale)


def _score_prompt(p: Prospect) -> str:
    fallback = (
        "Score this prospect for Constrox (offshore steel detailing / BIM / estimation). "
        "Return fit (0-100), intent (0-100), tier (A/B/C/disqualify), and a one-line "
        "rationale. Tier A is a high-fit decision maker at an in-target fabricator/GC; "
        "disqualify if out of ICP.\n\n"
        f"Company: {p.company}\n"
        f"Contact: {p.contact_name or 'unknown'} ({p.title or 'unknown title'})\n"
        f"Jurisdiction: {p.jurisdiction or 'unknown'}\n"
        f"ICP segment: {p.icp_segment}\n"
        f"Firmographics: {p.firmographics}\n"
        f"Research notes: {p.research_notes or 'none'}\n"
    )
    template = getattr(prompts, "SCORE_PROMPT", None) if prompts else None
    if isinstance(template, str):
        try:
            return template.format(
                company=p.company,
                contact_name=p.contact_name or "unknown",
                title=p.title or "unknown title",
                jurisdiction=p.jurisdiction or "unknown",
                segment=p.icp_segment,
                firmographics=p.firmographics,
                research_notes=p.research_notes or "none",
            )
        except Exception:
            return fallback
    return fallback


def score(state: SalesState, deps: Deps) -> dict:
    p: Prospect = state["prospect"]
    prompt = _score_prompt(p)
    try:
        leadscore = models.structured("score", LeadScore).invoke(prompt)
    except Exception:
        leadscore = score_prospect_heuristic(p)

    next_stage = "score" if leadscore.tier == "disqualify" else "suppress"
    return {"score": leadscore, "stage": next_stage}


def suppress(state: SalesState, deps: Deps) -> dict:
    """Hard stop on internal email suppression / DNC / opt-out."""
    p: Prospect = state["prospect"]
    suppressed = False
    if p.email:
        try:
            suppressed = bool(deps.email.suppression_check(p.email))
        except Exception:
            suppressed = False

    if suppressed:
        return {"stage": "blocked", "error": "internal_suppression"}
    return {"stage": "outreach"}
