"""Human-in-the-loop gate behavior: the locked decision that calls + LinkedIn
+ pricing pause for a human, and nothing leaves the building before approval."""
from __future__ import annotations

import pytest
from langgraph.types import Command

from conftest import cfg
from constrox_sdr.state import initial_state


def _cadence(channel):
    return lambda state, deps: {"cadence": [{"channel": channel, "step": 1, "purpose": "intro"}],
                                "stage": "outreach"}


def test_call_script_pauses_for_human_then_queues(deps, fake_llm, monkeypatch, fabricator_us):
    from constrox_sdr.nodes import outreach
    from constrox_sdr import compliance
    from constrox_sdr.graph import build_graph

    monkeypatch.setattr(outreach, "plan_cadence", _cadence("call"))
    monkeypatch.setattr(compliance, "within_call_window", lambda *a, **k: True)  # deterministic
    app = build_graph(deps)
    c = cfg("hitl-call")

    app.invoke(initial_state(fabricator_us), c)
    snap = app.get_state(c)
    assert snap.next == ("call_human_gate",)
    intr = snap.tasks[0].interrupts[0].value
    assert intr["gate"] == "cold_call_script" and intr["channel"] == "call"
    assert deps.dialer.queued == []          # NOTHING dialed before approval

    app.invoke(Command(resume={"action": "approve"}), c)
    assert len(deps.dialer.queued) == 1       # queued for the human only after approval
    assert app.get_state(c).next == ("await_reply",)


def test_call_script_reject_does_not_queue(deps, fake_llm, monkeypatch, fabricator_us):
    from constrox_sdr.nodes import outreach
    from constrox_sdr import compliance
    from constrox_sdr.graph import build_graph

    monkeypatch.setattr(outreach, "plan_cadence", _cadence("call"))
    monkeypatch.setattr(compliance, "within_call_window", lambda *a, **k: True)
    app = build_graph(deps)
    c = cfg("hitl-call-reject")

    app.invoke(initial_state(fabricator_us), c)
    app.invoke(Command(resume={"action": "reject"}), c)
    assert deps.dialer.queued == []


def test_linkedin_always_pauses_and_never_auto_sends(deps, fake_llm, monkeypatch, fabricator_us):
    from constrox_sdr.nodes import outreach
    from constrox_sdr.graph import build_graph

    monkeypatch.setattr(outreach, "plan_cadence", _cadence("linkedin"))
    app = build_graph(deps)
    c = cfg("hitl-li")

    app.invoke(initial_state(fabricator_us), c)
    snap = app.get_state(c)
    assert snap.next == ("linkedin_human_gate",)
    assert snap.tasks[0].interrupts[0].value["gate"] == "linkedin_message"
    assert deps.linkedin.queue == []          # nothing queued before human approval

    app.invoke(Command(resume={"action": "approve"}), c)
    assert len(deps.linkedin.queue) == 1
    # queued as a draft for a human to send — never auto-sent
    assert deps.linkedin.queue[0]["status"] == "pending_human_send"


def test_pricing_gate_fires_on_low_value_and_reject_loses_deal(graph, deps, fabricator_us):
    st = initial_state(fabricator_us)
    st["deal"] = {"pipeline_value": 1500.0, "stage": "open", "recurring": True}  # below floor
    st["inbound_reply"] = "Interested, let's talk pricing."
    c = cfg("hitl-price")

    graph.invoke(st, c)
    snap = graph.get_state(c)
    assert snap.next == ("pricing_gate",)
    assert snap.tasks[0].interrupts[0].value["gate"] == "pricing_approval"

    graph.invoke(Command(resume={"action": "reject"}), c)
    deal = next(iter(deps.crm.deals.values()))
    assert deal["stage"] == "lost"            # rejected price never closes as won
    assert deal.get("won_amount", 0) in (0, None)


def test_pricing_gate_approve_closes_won(graph, deps, fabricator_us):
    st = initial_state(fabricator_us)
    st["deal"] = {"pipeline_value": 1500.0, "stage": "open", "recurring": True}
    st["inbound_reply"] = "Interested, let's talk pricing."
    c = cfg("hitl-price-ok")

    graph.invoke(st, c)
    graph.invoke(Command(resume={"action": "approve"}), c)
    deal = next(iter(deps.crm.deals.values()))
    assert deal["stage"] == "won"


def test_high_value_email_does_not_interrupt_by_default(graph, deps, fabricator_us):
    """Email is the only auto-send channel: the happy path must NOT pause."""
    st = initial_state(fabricator_us)
    st["inbound_reply"] = "Interested."
    c = cfg("no-email-gate")
    graph.invoke(st, c)
    # reached terminal without any interrupt
    assert graph.get_state(c).next == ()
    assert len(deps.email.sent) == 1
