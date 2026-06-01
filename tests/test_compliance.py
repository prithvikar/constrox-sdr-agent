"""Table-driven tests for the deterministic compliance gate."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from constrox_sdr.compliance import run_compliance_gate
from constrox_sdr.config import ORG
from constrox_sdr.state import Prospect
from constrox_sdr.adapters.mock import mock_deps

# 11:00 US Central / 17:00 UTC — inside every call window.
NOON = datetime(2026, 6, 1, 16, 0, tzinfo=timezone.utc)


def _prospect(**kw):
    base = dict(lead_id="L1", company="Acme Steel", email="a@acme.com",
                phone="+12145551234", phone_type="business_landline",
                timezone="America/Chicago")
    base.update(kw)
    return Prospect(**base)


def email(body, subject="Detailing capacity for your shop"):
    return {"channel": "email", "subject": subject, "body": body}


# --------------------------- US CAN-SPAM email ----------------------------- #
def test_us_email_missing_postal_address_blocks():
    d = mock_deps()
    r = run_compliance_gate(_prospect(jurisdiction="US"),
                            email("Hi. Reply STOP to opt out."), d, now=NOON)
    assert not r.passed and r.failing_rule == "missing_physical_postal_address"


def test_us_email_missing_unsubscribe_blocks():
    d = mock_deps()
    r = run_compliance_gate(_prospect(jurisdiction="US"),
                            email(f"Hi. {ORG.address}."), d, now=NOON)
    assert not r.passed and r.failing_rule == "missing_functional_unsubscribe"


def test_us_email_compliant_passes():
    d = mock_deps()
    r = run_compliance_gate(_prospect(jurisdiction="US"),
                            email(f"Hi. {ORG.address}. Reply STOP to opt out."), d, now=NOON)
    assert r.passed and r.record["passed"] is True


def test_us_email_on_suppression_blocks():
    d = mock_deps()
    d.email.suppressed.add("a@acme.com")
    r = run_compliance_gate(_prospect(jurisdiction="US"),
                            email(f"Hi. {ORG.address}. Reply STOP to opt out."), d, now=NOON)
    assert not r.passed and r.failing_rule == "email_on_internal_suppression"


# --------------------------- AU Spam Act ----------------------------------- #
def test_au_email_no_consent_blocks():
    d = mock_deps()
    body = f"Hi. {ORG.name}. ABN {ORG.abn}. Reply STOP to opt out."
    r = run_compliance_gate(_prospect(jurisdiction="AU", has_consent=False), email(body), d, now=NOON)
    assert not r.passed and r.failing_rule == "au_no_recorded_consent"


def test_au_email_with_consent_and_abn_passes():
    d = mock_deps()
    body = f"Hi. {ORG.name}. ABN {ORG.abn}. Reply STOP to opt out."
    r = run_compliance_gate(_prospect(jurisdiction="AU", has_consent=True), email(body), d, now=NOON)
    assert r.passed


def test_au_email_missing_abn_blocks():
    d = mock_deps()
    body = f"Hi. {ORG.name}. Reply STOP to opt out."  # no ABN
    r = run_compliance_gate(_prospect(jurisdiction="AU", has_consent=True), email(body), d, now=NOON)
    assert not r.passed and r.failing_rule == "missing_sender_identity_abn"


# --------------------------- UK GDPR/PECR ---------------------------------- #
def test_uk_sole_trader_no_consent_blocks():
    d = mock_deps()
    body = f"Hi from {ORG.name}. reaching out because we noticed your work. Reply STOP to opt out."
    r = run_compliance_gate(
        _prospect(jurisdiction="UK", entity_type="sole_trader", has_consent=False),
        email(body), d, now=NOON)
    assert not r.passed and r.failing_rule == "uk_individual_subscriber_no_consent"


def test_uk_company_passes_with_lia():
    d = mock_deps()
    body = f"Hi from {ORG.name}. reaching out because we noticed your projects. Reply STOP to opt out."
    r = run_compliance_gate(_prospect(jurisdiction="UK", entity_type="company"),
                            email(body), d, now=NOON)
    assert r.passed and r.lawful_basis == "legitimate_interest_LIA_on_file"


# --------------------------- Calls (DNC / window / cell) ------------------- #
def test_call_on_dnc_blocks():
    d = mock_deps()
    d.scrub.listed.add("+12145551234")
    r = run_compliance_gate(_prospect(jurisdiction="US"), {"channel": "call", "body": "script"}, d, now=NOON)
    assert not r.passed and r.failing_rule == "number_on_dnc_register"


def test_call_stale_scrub_blocks():
    d = mock_deps()
    d.scrub.force_stale = True
    r = run_compliance_gate(_prospect(jurisdiction="US"), {"channel": "call", "body": "s"}, d, now=NOON)
    assert not r.passed and r.failing_rule == "stale_register_scrub"


def test_call_outside_window_blocks():
    d = mock_deps()
    three_am_central = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)  # 03:00 Central
    r = run_compliance_gate(_prospect(jurisdiction="US"), {"channel": "call", "body": "s"}, d,
                            now=three_am_central)
    assert not r.passed and r.failing_rule == "outside_local_call_window"


def test_call_us_cell_no_consent_blocks():
    d = mock_deps()
    r = run_compliance_gate(_prospect(jurisdiction="US", phone_type="mobile", has_consent=False),
                            {"channel": "call", "body": "s"}, d, now=NOON)
    assert not r.passed and r.failing_rule == "us_cell_no_consent_for_autodial"


def test_call_business_landline_in_window_passes():
    d = mock_deps()
    r = run_compliance_gate(_prospect(jurisdiction="US"), {"channel": "call", "body": "script"}, d, now=NOON)
    assert r.passed


# --------------------------- LinkedIn -------------------------------------- #
def test_linkedin_programmatic_send_hard_blocks():
    d = mock_deps()
    draft = {"channel": "linkedin", "body": "hi", "sent": True, "approved": False}
    r = run_compliance_gate(_prospect(jurisdiction="US"), draft, d, now=NOON)
    assert not r.passed and r.failing_rule == "linkedin_programmatic_send_forbidden"


def test_linkedin_unapproved_blocks():
    d = mock_deps()
    draft = {"channel": "linkedin", "body": "hi", "approved": False}
    r = run_compliance_gate(_prospect(jurisdiction="US"), draft, d, now=NOON)
    assert not r.passed and r.failing_rule == "linkedin_requires_human_approval"


def test_linkedin_human_approved_passes():
    d = mock_deps()
    draft = {"channel": "linkedin", "body": "hi", "approved": True}
    r = run_compliance_gate(_prospect(jurisdiction="US"), draft, d, now=NOON)
    assert r.passed and r.lawful_basis == "human_gated_linkedin"


# --------------------------- Honesty + audit log --------------------------- #
def test_deceptive_subject_blocks():
    d = mock_deps()
    body = f"Hi. {ORG.address}. Reply STOP to opt out."
    r = run_compliance_gate(_prospect(jurisdiction="US"), email(body, subject="you won free money"),
                            d, now=NOON)
    assert not r.passed and r.failing_rule == "deceptive_subject_or_headers"


def test_every_result_writes_nonempty_record():
    d = mock_deps()
    r = run_compliance_gate(_prospect(jurisdiction="US"),
                            email(f"{ORG.address}. Reply STOP to opt out."), d, now=NOON)
    assert r.record and r.record["lead_id"] == "L1" and "checked_at" in r.record
