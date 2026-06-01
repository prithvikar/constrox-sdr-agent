"""Deterministic compliance gate. No LLM. The legal backbone.

`run_compliance_gate()` implements the 10-step checklist for US/UK/AU email +
calls and the LinkedIn no-automation rule. It returns a ComplianceResult whose
`.record` is the immutable audit payload. Rule: *no log -> no send*.

`now` is injectable so call-window checks are deterministic in tests.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from .config import ORG
from .state import ComplianceResult, DraftArtifact, Prospect
from .adapters.base import Deps

# Jurisdiction -> register scrub freshness ceiling (days).
SCRUB_FRESHNESS_DAYS = {"US": 31, "UK": 28, "AU": 31}

# Permitted local calling window (inclusive start hour, exclusive end hour).
CALL_WINDOW = {"US": (8, 21), "UK": (8, 21), "AU": (9, 20)}


# --------------------------------------------------------------------------- #
# Result helpers                                                              #
# --------------------------------------------------------------------------- #
def _result(passed: bool, channel: str, jur, rule: Optional[str], rec: dict,
            lawful_basis: Optional[str] = None, scrub_fresh: bool = False) -> ComplianceResult:
    rec = {**rec, "passed": passed, "failing_rule": rule, "lawful_basis": lawful_basis}
    return ComplianceResult(
        passed=passed, channel=channel, jurisdiction=jur,
        failing_rule=rule, lawful_basis=lawful_basis, scrub_fresh=scrub_fresh, record=rec,
    )


def _block(channel, jur, rule, rec) -> ComplianceResult:
    return _result(False, channel, jur, rule, rec)


def _pass(channel, jur, rec, lawful_basis="n/a", scrub_fresh=True) -> ComplianceResult:
    return _result(True, channel, jur, None, rec, lawful_basis, scrub_fresh)


# --------------------------------------------------------------------------- #
# Content checks (string-presence; drafting nodes inject these elements)      #
# --------------------------------------------------------------------------- #
def has_one_step_unsubscribe(body: str) -> bool:
    b = body.lower()
    return ("unsubscribe" in b) or ("opt out" in b) or ("opt-out" in b) or ("reply stop" in b)


def has_physical_address(body: str) -> bool:
    # CAN-SPAM: the configured postal address must appear verbatim.
    return bool(ORG.address) and ORG.address in body


def has_sender_legalname_abn(body: str) -> bool:
    # AU Spam Act: legal name + ABN present.
    return (ORG.name.split(" (")[0] in body or ORG.name in body) and (ORG.abn in body)


def has_sender_identity_and_source(body: str) -> bool:
    # UK PECR/GDPR: identify sender AND say how/why they're contacted.
    b = body.lower()
    org_present = (ORG.name in body) or (ORG.name.split(" (")[0] in body)
    source_present = any(k in b for k in
                         ("you are receiving", "we found", "reaching out because",
                          "came across", "noticed", "we obtained", "publicly"))
    return org_present and source_present


def deceptive_headers(draft: DraftArtifact) -> bool:
    subject = (draft.get("subject") or "").strip().lower()
    if draft.get("channel") == "email":
        # crude relevance/honesty heuristics: empty subject or known spam-bait
        if not subject:
            return True
        if any(b in subject for b in ("re: your payment", "you won", "urgent!!!", "free money")):
            return True
    return False


def caller_id_ok(deps: Deps) -> bool:
    # Real adapter would assert a non-spoofed, registered outbound caller id.
    # Mock: org identity present == acceptable.
    return bool(ORG.name)


def within_call_window(tz_name: Optional[str], jur, now: datetime) -> bool:
    start, end = CALL_WINDOW.get(jur, (8, 21))
    if not tz_name:
        return False  # unknown local time -> cannot prove compliance -> block
    try:
        local = now.astimezone(ZoneInfo(tz_name))
    except Exception:
        return False
    return start <= local.hour < end


def _has_consent(p: Prospect) -> bool:
    return bool(p.has_consent)


def _has_consent_or_soft_optin(p: Prospect) -> bool:
    return bool(p.has_consent or p.has_soft_optin)


# --------------------------------------------------------------------------- #
# The gate                                                                    #
# --------------------------------------------------------------------------- #
def run_compliance_gate(
    prospect: Prospect,
    draft: DraftArtifact,
    deps: Deps,
    org_address: Optional[str] = None,
    now: Optional[datetime] = None,
) -> ComplianceResult:
    now = now or datetime.now(timezone.utc)
    org_address = org_address if org_address is not None else ORG.address
    ch = draft.get("channel")
    jur = prospect.jurisdiction
    rec = {
        "lead_id": prospect.lead_id, "channel": ch, "jurisdiction": jur,
        "checked_at": now.isoformat(), "approver": (draft.get("compliance") or {}).get("approver"),
    }

    # 1. Unknown channel/jurisdiction -> human review.
    if ch not in ("email", "call", "linkedin"):
        return _block(ch, jur, "unknown_channel", rec)
    if jur is None and ch != "linkedin":
        return _block(ch, jur, "unknown_jurisdiction", rec)

    # 2. LinkedIn: only 'draft pending human send' is legal. Programmatic send -> hard block.
    if ch == "linkedin":
        if draft.get("sent") and not draft.get("approved"):
            return _block(ch, jur, "linkedin_programmatic_send_forbidden", rec)
        if not draft.get("approved"):
            return _block(ch, jur, "linkedin_requires_human_approval", rec)
        return _pass(ch, jur, rec, lawful_basis="human_gated_linkedin")

    # 3. Suppression / register scrub freshness.
    if ch == "email" and deps.email.suppression_check(prospect.email or ""):
        return _block(ch, jur, "email_on_internal_suppression", rec)
    if ch == "call":
        scrub = deps.scrub.scrub(prospect.phone or "", jur)
        rec["scrub"] = scrub
        if scrub.get("listed"):
            return _block(ch, jur, "number_on_dnc_register", rec)
        if not scrub.get("fresh"):
            return _block(ch, jur, "stale_register_scrub", rec)

    # 4. Consent / lawful basis.
    lawful_basis = "n/a"
    if ch == "email":
        if jur == "AU" and not _has_consent(prospect):
            return _block(ch, jur, "au_no_recorded_consent", rec)
        if jur == "UK":
            if prospect.entity_type in ("sole_trader", "partnership") and not _has_consent_or_soft_optin(prospect):
                return _block(ch, jur, "uk_individual_subscriber_no_consent", rec)
            lawful_basis = "legitimate_interest_LIA_on_file"
        if jur == "US":
            lawful_basis = "can_spam_no_prior_consent_required"
        if jur == "AU":
            lawful_basis = "consent_recorded"

    # 5. Call-specific gates.
    if ch == "call":
        if prospect.phone_type == "mobile" and not _has_consent(prospect):
            return _block(ch, jur, "us_cell_no_consent_for_autodial", rec)
        if not within_call_window(prospect.timezone, jur, now):
            return _block(ch, jur, "outside_local_call_window", rec)
        if not caller_id_ok(deps):
            return _block(ch, jur, "caller_id_invalid", rec)
        lawful_basis = "human_dialed_after_scrub"

    # 6. Email content gates.
    if ch == "email":
        body = draft.get("body", "")
        if jur == "US" and not (org_address and org_address in body):
            return _block(ch, jur, "missing_physical_postal_address", rec)
        if jur == "AU" and not has_sender_legalname_abn(body):
            return _block(ch, jur, "missing_sender_identity_abn", rec)
        if jur == "UK" and not has_sender_identity_and_source(body):
            return _block(ch, jur, "missing_sender_identity_or_datasource", rec)
        if not has_one_step_unsubscribe(body):
            return _block(ch, jur, "missing_functional_unsubscribe", rec)

    # 7. Content honesty (all channels).
    if deceptive_headers(draft):
        return _block(ch, jur, "deceptive_subject_or_headers", rec)

    # 8-10. Release.
    return _pass(ch, jur, rec, lawful_basis=lawful_basis,
                 scrub_fresh=bool(rec.get("scrub", {}).get("fresh", True)))
