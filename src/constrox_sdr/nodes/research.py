"""Research node: enrich a prospect and write LLM research notes.

Deterministic (no tool/ReAct loop) so it stays testable. Uses the enrichment
adapter to backfill contact/firmographic fields, derives jurisdiction/timezone/
entity_type/icp_segment, then asks the LLM for a short steel-detailing-pitch
research summary stored on the prospect.
"""
from __future__ import annotations

from typing import Optional

from .. import models
from ..adapters.base import Deps
from ..state import ICPSegment, Jurisdiction, Prospect, SalesState

try:  # prompts.py is owned by Agent E and may not exist yet during parallel build.
    from .. import prompts  # type: ignore
except Exception:  # pragma: no cover - import guard
    prompts = None  # type: ignore


# Jurisdiction -> a plausible default IANA timezone.
_JUR_TZ: dict[str, str] = {
    "US": "America/Chicago",
    "UK": "Europe/London",
    "AU": "Australia/Sydney",
}

_VALID_JUR = ("US", "UK", "AU")
_VALID_SEGMENTS = ("fabricator", "gc", "consultancy", "precast_rebar", "other", "unknown")


def _coerce_jurisdiction(value: Optional[str]) -> Optional[Jurisdiction]:
    if isinstance(value, str) and value.upper() in _VALID_JUR:
        return value.upper()  # type: ignore[return-value]
    return None


def _coerce_segment(value: Optional[str]) -> Optional[ICPSegment]:
    if isinstance(value, str) and value.lower() in _VALID_SEGMENTS:
        return value.lower()  # type: ignore[return-value]
    return None


def _research_prompt(p: Prospect, company_info: dict, jurisdiction: Optional[str],
                     segment: Optional[str]) -> str:
    fallback = (
        "You are a sales researcher for Constrox, an offshore steel detailing / BIM / "
        "estimation partner. In 4-6 sentences, summarize the prospect company for a "
        "steel-detailing outsourcing pitch: their likely steel-detailing workload, "
        "outsourcing pain points, and one tailored hook.\n\n"
        f"Company: {p.company}\n"
        f"Domain: {p.domain or 'unknown'}\n"
        f"Contact: {p.contact_name or 'unknown'} ({p.title or 'unknown title'})\n"
        f"Jurisdiction: {jurisdiction or 'unknown'}\n"
        f"ICP segment: {segment or 'unknown'}\n"
        f"Firmographics: {company_info or p.firmographics}\n"
    )
    template = getattr(prompts, "RESEARCH_PROMPT", None) if prompts else None
    if isinstance(template, str):
        try:
            return template.format(
                company=p.company,
                domain=p.domain or "unknown",
                contact_name=p.contact_name or "unknown",
                title=p.title or "unknown title",
                jurisdiction=jurisdiction or "unknown",
                segment=segment or "unknown",
                firmographics=company_info or p.firmographics,
            )
        except Exception:
            return fallback
    return fallback


def research(state: SalesState, deps: Deps) -> dict:
    p: Prospect = state["prospect"]

    company_info = deps.enrich.company(p.domain or "") or {}
    contact_info = deps.enrich.contact(p.contact_name or "", p.company) or {}

    updates: dict = {}

    # Backfill contact-bound fields only when missing.
    if not p.email and contact_info.get("email"):
        updates["email"] = contact_info["email"]
    if not p.phone and contact_info.get("phone"):
        updates["phone"] = contact_info["phone"]
    if not p.title and contact_info.get("title"):
        updates["title"] = contact_info["title"]
    if not p.linkedin_url and contact_info.get("linkedin_url"):
        updates["linkedin_url"] = contact_info["linkedin_url"]

    # Merge firmographics from enrichment.
    merged_firmographics = {**p.firmographics, **company_info}
    if merged_firmographics != p.firmographics:
        updates["firmographics"] = merged_firmographics

    # Phone type (use freshly-resolved phone if any).
    resolved_phone = updates.get("phone", p.phone)
    if resolved_phone:
        try:
            pt = deps.enrich.phone_type(resolved_phone)
        except Exception:
            pt = None
        if pt in ("business_landline", "mobile", "unknown"):
            updates["phone_type"] = pt

    # Jurisdiction: prefer existing, else firmographics/enrichment.
    jurisdiction = p.jurisdiction
    if jurisdiction is None:
        jurisdiction = _coerce_jurisdiction(
            company_info.get("jurisdiction") or merged_firmographics.get("jurisdiction")
        )
        if jurisdiction is not None:
            updates["jurisdiction"] = jurisdiction

    # Timezone: derive a plausible default for the jurisdiction when missing.
    if not p.timezone and jurisdiction in _JUR_TZ:
        updates["timezone"] = _JUR_TZ[jurisdiction]

    # Entity type: default to "company" if still unknown.
    if p.entity_type == "unknown":
        updates["entity_type"] = "company"

    # ICP segment from enrichment 'segment'.
    if p.icp_segment == "unknown":
        seg = _coerce_segment(company_info.get("segment") or merged_firmographics.get("segment"))
        if seg is not None:
            updates["icp_segment"] = seg

    # Compute the "current view" for the prompt (applies pending updates).
    effective_jur = updates.get("jurisdiction", jurisdiction)
    effective_seg = updates.get("icp_segment", p.icp_segment)
    prompt = _research_prompt(p, company_info, effective_jur, effective_seg)

    try:
        resp = models.llm("research").invoke(prompt)
        notes = getattr(resp, "content", "") or ""
    except Exception:
        notes = ""
    if notes:
        updates["research_notes"] = notes

    updated = p.model_copy(update=updates)
    return {"prospect": updated, "stage": "score"}
