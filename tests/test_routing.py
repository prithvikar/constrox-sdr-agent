"""Pure routing-function tests (no graph, no LLM)."""
from __future__ import annotations

import pytest

from constrox_sdr.nodes import routing
from constrox_sdr.state import LeadScore, ReplyClass, BANT


def _score(tier):
    return LeadScore(fit=70, intent=70, tier=tier, rationale="")


@pytest.mark.parametrize("tier,expected", [
    ("A", "suppress"), ("B", "suppress"), ("C", "suppress"), ("disqualify", "disqualify"),
])
def test_route_after_score(tier, expected):
    assert routing.route_after_score({"score": _score(tier)}) == expected


def test_route_after_score_none():
    assert routing.route_after_score({"score": None}) == "disqualify"


@pytest.mark.parametrize("stage,expected", [
    ("blocked", "blocked"), ("outreach", "plan_cadence"),
])
def test_route_after_suppress(stage, expected):
    assert routing.route_after_suppress({"stage": stage}) == expected


@pytest.mark.parametrize("channel", ["email", "call", "linkedin"])
def test_route_channel(channel):
    assert routing.route_channel({"cadence": [{"channel": channel}]}) == channel


def test_route_after_email_compliance():
    assert routing.route_after_email_compliance({"compliance_results": [{"passed": True}]}) == "email_send"
    assert routing.route_after_email_compliance({"compliance_results": [{"passed": False}]}) == "blocked"


def test_route_after_call_compliance():
    assert routing.route_after_call_compliance({"compliance_results": [{"passed": True}]}) == "queue_dialer"
    assert routing.route_after_call_compliance({"compliance_results": [{"passed": False}]}) == "blocked"


@pytest.mark.parametrize("intent,expected", [
    ("interested", "book_discovery"),
    ("meeting_request", "book_discovery"),
    ("objection", "handle_objection"),
    ("referral", "handle_objection"),
    ("not_interested", "nurture_or_terminate"),
    ("unsubscribe", "nurture_or_terminate"),
    ("ooo_autoreply", "nurture_or_terminate"),
])
def test_route_after_reply(intent, expected):
    rc = ReplyClass(intent=intent, sentiment="neutral", suggested_next="")
    assert routing.route_after_reply({"reply_class": rc}) == expected


def test_route_after_reply_none():
    assert routing.route_after_reply({"reply_class": None}) == "nurture_or_terminate"


def test_route_after_discovery():
    assert routing.route_after_discovery({"bant": BANT(qualified=True)}) == "schedule_demo"
    assert routing.route_after_discovery({"bant": BANT(qualified=False)}) == "nurture_or_terminate"


def test_route_after_negotiate_high_value_closes():
    s = {"deal": {"pipeline_value": 6000.0}, "human_decision": None}
    assert routing.route_after_negotiate(s) == "close_deal"


def test_route_after_negotiate_low_value_gates():
    s = {"deal": {"pipeline_value": 1500.0}, "human_decision": None}
    assert routing.route_after_negotiate(s) == "pricing_gate"
