"""FastAPI webhook surface (prod extra).

Three inbound events resume or feed the agent:
  POST /webhooks/reply     -> resume a parked thread with an inbound reply
  POST /webhooks/approval  -> resume a HITL gate (call / linkedin / pricing)
  POST /webhooks/invoice   -> record a paid invoice -> commission

Build the app with build_app(deps, checkpointer, ledger). The graph must be
compiled with a persistent checkpointer (Postgres) so threads survive restarts.
"""
from __future__ import annotations

from typing import Optional

from .adapters.base import Deps
from .commission import CommissionLedger


def build_app(deps: Deps, checkpointer=None, ledger: Optional[CommissionLedger] = None):
    from fastapi import FastAPI
    from pydantic import BaseModel
    from langgraph.types import Command

    from .graph import build_graph

    app = FastAPI(title="Constrox SDR Agent")
    graph = build_graph(deps, checkpointer)
    ledger = ledger or CommissionLedger()

    def _cfg(thread_id: str):
        return {"configurable": {"thread_id": thread_id}}

    class ReplyEvent(BaseModel):
        thread_id: str
        reply_text: str

    class ApprovalEvent(BaseModel):
        thread_id: str
        action: str                      # approve | edit | reject | counter
        body: Optional[str] = None       # edited script/message, if any

    class InvoiceEvent(BaseModel):
        invoice_id: str
        deal_id: str
        amount: float
        status: str                      # issued | paid | void
        period_month: Optional[str] = None

    @app.post("/webhooks/reply")
    def inbound_reply(ev: ReplyEvent):
        # await_reply parks via interrupt(); resume with the reply text.
        graph.invoke(Command(resume=ev.reply_text), _cfg(ev.thread_id))
        return {"ok": True, "thread_id": ev.thread_id}

    @app.post("/webhooks/approval")
    def approval(ev: ApprovalEvent):
        resume = {"action": ev.action}
        if ev.body is not None:
            resume["body"] = ev.body
        graph.invoke(Command(resume=resume), _cfg(ev.thread_id))
        return {"ok": True, "thread_id": ev.thread_id, "action": ev.action}

    @app.post("/webhooks/invoice")
    def invoice(ev: InvoiceEvent):
        commission = ledger.on_invoice_paid(ev.model_dump())
        return {"ok": True, "commission": commission}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
