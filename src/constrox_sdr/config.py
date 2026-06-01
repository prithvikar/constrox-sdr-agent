"""Central configuration: model routing, gate toggles, ICP constants, org identity.

All values are environment-overridable so the same code runs in dev (mocks) and
prod (real Constrox adapters) without edits.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Model routing — task -> model id.                                            #
# Default provider is Google Gemini (see models.py). A single Gemini Flash key #
# runs the whole agent: all three tiers default to GEMINI_MODEL. Override any  #
# tier via env (MODEL_CLASSIFY / MODEL_DRAFT / MODEL_PREMIUM) — e.g. point the #
# premium tier at gemini-2.5-pro if your key supports it.                      #
#                                                                              #
# Set GEMINI_MODEL to your exact model id (e.g. "gemini-2.5-flash" or          #
# "gemini-3.5-flash" if that is what your key exposes). For Anthropic, set     #
# MODEL_PROVIDER=anthropic and override the three model ids with claude-* ids. #
# --------------------------------------------------------------------------- #
_GEMINI_DEFAULT = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MODEL_CLASSIFY = os.getenv("MODEL_CLASSIFY", _GEMINI_DEFAULT)
MODEL_DRAFT = os.getenv("MODEL_DRAFT", _GEMINI_DEFAULT)
# Premium tier defaults to Flash too, so a Flash-only key works end-to-end.
MODEL_PREMIUM = os.getenv("MODEL_PREMIUM", _GEMINI_DEFAULT)

# task name -> model id
MODEL_MAP: dict[str, str] = {
    "score": MODEL_CLASSIFY,
    "classify_reply": MODEL_CLASSIFY,
    "route": MODEL_CLASSIFY,
    "research": MODEL_DRAFT,
    "plan_cadence": MODEL_DRAFT,
    "email_draft": MODEL_DRAFT,
    "linkedin_draft": MODEL_DRAFT,
    "handle_objection": MODEL_DRAFT,
    "run_discovery": MODEL_DRAFT,
    "schedule_demo": MODEL_DRAFT,
    "negotiate": MODEL_DRAFT,
    "call_script": MODEL_PREMIUM,        # may downgrade to Sonnet for non-Tier-A (see models.py)
    "email_draft_tier_a": MODEL_PREMIUM,
}

DEFAULT_MODEL = MODEL_DRAFT


def model_for(task: str, tier: str | None = None) -> str:
    """Resolve the model id for a task, with Tier-aware premium routing."""
    if task == "call_script":
        return MODEL_PREMIUM if tier == "A" else MODEL_DRAFT
    if task == "email_draft" and tier == "A":
        return MODEL_PREMIUM
    return MODEL_MAP.get(task, DEFAULT_MODEL)


# --------------------------------------------------------------------------- #
# Human-in-the-loop gate toggles.                                             #
# --------------------------------------------------------------------------- #
def high_value_email_gate_enabled() -> bool:
    return os.getenv("GATE_HIGH_VALUE_EMAIL", "false").lower() in ("1", "true", "yes")


# --------------------------------------------------------------------------- #
# Org identity (compliance: injected/validated in every email).               #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OrgIdentity:
    name: str = os.getenv("ORG_NAME", "Constrox (ASISA Technologies LLP)")
    address: str = os.getenv("ORG_ADDRESS", "Constrox, 123 Example St, City, Country")
    abn: str = os.getenv("ORG_ABN", "00 000 000 000")


ORG = OrgIdentity()


# --------------------------------------------------------------------------- #
# Commission tiers (7-13% recurring on paid invoices). Config-tunable.         #
# --------------------------------------------------------------------------- #
COMMISSION_RECURRING_PREMIUM_RATE = 0.13   # recurring retainer >= threshold
COMMISSION_RECURRING_RATE = 0.10           # recurring retainer < threshold
COMMISSION_ONEOFF_RATE = 0.07              # one-off project package
COMMISSION_PREMIUM_MONTHLY_THRESHOLD = 8000.0

# Pipeline targets (success criteria from the listing).
MONTHLY_REVENUE_TARGET = 30_000.0
PIPELINE_COVERAGE_MULTIPLE = 3.0           # >= 3x monthly target in open pipeline
MIN_QUALIFIED_OPPS = 30
TARGET_CONVERSION_RATE = 0.10              # qualified lead -> closed


# --------------------------------------------------------------------------- #
# ICP definition (Constrox = offshore steel detailing / BIM / estimation).     #
# --------------------------------------------------------------------------- #
ICP_SEGMENTS = ("fabricator", "gc", "consultancy", "precast_rebar")

# Title -> weight signal for scoring (higher = stronger buyer).
ICP_TITLE_SIGNALS: dict[str, int] = {
    "owner": 25, "president": 25,
    "chief estimator": 24, "estimating manager": 22,
    "detailing manager": 24, "chief detailer": 24, "drafting manager": 22,
    "preconstruction manager": 20, "vdc": 20, "bim manager": 20,
    "director of operations": 20, "vp operations": 20,
    "principal": 18, "project manager": 16, "project engineer": 15,
    "procurement manager": 14, "purchasing manager": 14,
}

# Segment -> base intent weight (fabricators have the highest outsourcing intent).
ICP_SEGMENT_WEIGHTS: dict[str, int] = {
    "fabricator": 25, "precast_rebar": 20, "gc": 18, "consultancy": 16, "other": 5, "unknown": 5,
}

TARGET_JURISDICTIONS = ("US", "UK", "AU")

# Software the buyer cares about (used in personalization + objection handling).
DETAILING_SOFTWARE = ("Tekla", "SDS2", "Revit", "AutoCAD", "ProSteel", "Advance Steel")

# Code standards by jurisdiction (for credibility in messaging).
CODE_STANDARDS = {"US": "AISC", "UK": "BS/Eurocode", "AU": "AS"}


@dataclass
class Settings:
    """Runtime settings bundle (handy for tests / overrides)."""
    org: OrgIdentity = field(default_factory=OrgIdentity)
    score_threshold: int = 50           # below this -> disqualify
    tier_a_cutoff: int = 75             # combined fit+intent/2 >= this -> Tier A
    tier_b_cutoff: int = 50


SETTINGS = Settings()
