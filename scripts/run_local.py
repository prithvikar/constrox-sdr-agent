"""Drive the Constrox SDR agent end-to-end on mock adapters.

Runs with NO API key: when the LLM is unavailable, nodes fall back to
deterministic templates, so the whole pipeline still executes. With
GOOGLE_API_KEY/GEMINI_API_KEY set, drafting/scoring/classification use Gemini.

Usage:
    python scripts/run_local.py            # email happy-path -> won deal
    python scripts/run_local.py --call     # show the cold-call HITL pause
"""
from __future__ import annotations

import sys
from langgraph.types import Command

from constrox_sdr.graph import build_graph
from constrox_sdr.adapters.mock import mock_deps
from constrox_sdr.state import Prospect, initial_state
from constrox_sdr.commission import CommissionLedger, tier_rate
from constrox_sdr.reporting import weekly_summary


def banner(t):
    print("\n" + "=" * 70 + f"\n {t}\n" + "=" * 70)


def sample_prospect():
    return Prospect(
        lead_id="L-DEMO-001", company="Ironclad Steel Fabricators",
        domain="ironcladsteel.com", contact_name="Dana Reyes", title="Chief Estimator",
        email="dana@ironcladsteel.com", phone="+12145550199",
        phone_type="business_landline", jurisdiction="US", timezone="America/Chicago",
        entity_type="company", icp_segment="fabricator",
    )


def run_email_happy_path():
    deps = mock_deps()
    app = build_graph(deps)
    cfg = {"configurable": {"thread_id": "demo-email"}}

    st = initial_state(sample_prospect())
    st["inbound_reply"] = ("Yes, very interested — I'm the owner and we're short-staffed on detailing, "
                           "behind on shop drawings. We need help next month. Send pricing and let's "
                           "book a call.")

    banner("CONSTROX SDR AGENT — email -> discovery -> demo -> close")
    out = app.invoke(st, cfg)

    email = next((d for d in out["drafts"] if d["channel"] == "email" and d.get("sent")), None)
    if email:
        print("\n--- OUTREACH EMAIL (sent) ---")
        print("Subject:", email.get("subject"))
        print(email.get("body"))

    print("\n--- COMPLIANCE AUDIT (per outbound action) ---")
    for rec in out["compliance_results"]:
        print(f"  channel={rec['channel']} jurisdiction={rec['jurisdiction']} "
              f"passed={rec['passed']} basis={rec.get('lawful_basis')}")

    print("\n--- REPLY CLASSIFICATION ---")
    rc = out.get("reply_class")
    print(f"  intent={rc.intent} sentiment={rc.sentiment} -> next={rc.suggested_next}")

    deal = next(iter(deps.crm.deals.values()))
    print("\n--- DEAL ---")
    print(f"  stage={deal['stage']} monthly_value=${deal.get('pipeline_value',0):,.0f} "
          f"recurring={deal.get('recurring')} won=${deal.get('won_amount',0):,.0f}")

    # commission on first paid invoice
    ledger = CommissionLedger()
    ledger.upsert_deal({"deal_id": "D1", "stage": "won",
                        "pipeline_value": deal.get("pipeline_value", 0.0),
                        "recurring": deal.get("recurring", True)})
    comm = ledger.on_invoice_paid({"invoice_id": "INV-1", "deal_id": "D1",
                                   "amount": deal.get("pipeline_value", 0.0),
                                   "status": "paid", "period_month": "2026-06-01"})
    print("\n--- COMMISSION (on paid invoice) ---")
    if comm:
        print(f"  rate={comm['rate']:.0%} on ${comm['basis_amount']:,.0f} "
              f"=> ${comm['commission_amount']:,.2f} ({comm['recurring_schedule']})")

    print("\n--- PIPELINE SNAPSHOT ---")
    summ = weekly_summary(ledger)
    for k, v in summ.items():
        print(f"  {k}: {v}")

    print(f"\nFinal: crm_synced={out['crm_synced']}  graph_done={app.get_state(cfg).next == ()}")


def run_call_hitl():
    from constrox_sdr.nodes import outreach
    from constrox_sdr import compliance
    # force a call-first cadence and a deterministic call window for the demo
    outreach.plan_cadence = lambda state, deps: {
        "cadence": [{"channel": "call", "step": 1, "purpose": "intro"}], "stage": "outreach"}
    compliance.within_call_window = lambda *a, **k: True

    deps = mock_deps()
    app = build_graph(deps)
    cfg = {"configurable": {"thread_id": "demo-call"}}

    banner("CONSTROX SDR AGENT — cold call is HUMAN-GATED (never auto-dials)")
    app.invoke(initial_state(sample_prospect()), cfg)
    snap = app.get_state(cfg)
    intr = snap.tasks[0].interrupts[0].value
    print(f"\nPAUSED at: {snap.next[0]}  (gate={intr['gate']})")
    print(f"Dialer queue BEFORE approval: {deps.dialer.queued}  <-- nothing dialed")
    print("\n--- DRAFTED CALL SCRIPT awaiting human approval ---")
    print(intr["body"][:600])

    app.invoke(Command(resume={"action": "approve"}), cfg)
    print(f"\nAfter human APPROVES: dialer queue has {len(deps.dialer.queued)} item "
          f"(queued for a human rep to dial).")


if __name__ == "__main__":
    if "--call" in sys.argv:
        run_call_hitl()
    else:
        run_email_happy_path()
