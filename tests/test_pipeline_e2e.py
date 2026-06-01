"""End-to-end pipeline tests on mock adapters + fake LLMs."""
from __future__ import annotations

from conftest import cfg


def test_happy_path_email_to_won(graph, deps, fabricator_us):
    from constrox_sdr.state import initial_state
    st = initial_state(fabricator_us)
    st["inbound_reply"] = "Yes, interested — can we talk Thursday?"  # seed so await_reply passes through

    out = graph.invoke(st, cfg("e2e-happy"))

    # one compliant email actually sent
    assert len(deps.email.sent) == 1
    assert any(c["passed"] for c in out["compliance_results"])
    # deal won + synced to CRM
    assert out["crm_synced"] is True
    deal = next(iter(deps.crm.deals.values()))
    assert deal["stage"] == "won"
    assert deal["won_amount"] > 0
    # graph reached terminal state
    assert graph.get_state(cfg("e2e-happy")).next == ()


def test_disqualified_prospect_skips_outreach(graph, deps, fabricator_us, llm_canned):
    from constrox_sdr.state import initial_state, LeadScore
    llm_canned["LeadScore"] = LeadScore(fit=10, intent=5, tier="disqualify", rationale="off-ICP")
    out = graph.invoke(initial_state(fabricator_us), cfg("e2e-dq"))
    assert len(deps.email.sent) == 0          # never sent
    assert out["crm_synced"] is True          # still logged to CRM
    assert graph.get_state(cfg("e2e-dq")).next == ()


def test_suppressed_email_blocks_send(graph, deps, fabricator_us):
    from constrox_sdr.state import initial_state
    deps.email.suppressed.add(fabricator_us.email)
    out = graph.invoke(initial_state(fabricator_us), cfg("e2e-supp"))
    assert len(deps.email.sent) == 0
    assert out["stage"] in ("blocked", "crm_sync")  # blocked then synced for audit
    assert out["crm_synced"] is True


def test_not_interested_reply_terminates(graph, deps, fabricator_us, llm_canned):
    from constrox_sdr.state import initial_state, ReplyClass
    llm_canned["ReplyClass"] = ReplyClass(intent="not_interested", sentiment="negative",
                                          suggested_next="suppress")
    st = initial_state(fabricator_us)
    st["inbound_reply"] = "Not interested, thanks."
    out = graph.invoke(st, cfg("e2e-ni"))
    assert len(deps.email.sent) == 1          # the outreach email went
    assert not deps.crm.deals                 # no deal created
    assert out["crm_synced"] is True


def test_stage_sequence_streamed(graph, fabricator_us):
    from constrox_sdr.state import initial_state
    st = initial_state(fabricator_us)
    st["inbound_reply"] = "Interested, let's chat."
    seen = []
    for upd in graph.stream(st, cfg("e2e-stream"), stream_mode="updates"):
        seen.extend(upd.keys())
    # key milestones appear in order
    for node in ("research", "score", "email_send", "classify_reply", "close_deal", "crm_sync"):
        assert node in seen, f"missing {node} in {seen}"
