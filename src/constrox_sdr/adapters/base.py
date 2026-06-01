"""Adapter contracts. Nodes call these Protocols, never vendor SDKs.

Mock implementations (mock.py) satisfy these now; real Constrox adapters
(constrox.py) slot in behind the identical surface with zero node changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class CRMAdapter(Protocol):
    def upsert_lead(self, lead: dict) -> str: ...
    def upsert_deal(self, deal: dict) -> str: ...
    def log_activity(self, lead_id: str, activity: dict) -> None: ...
    def enrich(self, domain: str) -> dict: ...


@runtime_checkable
class DialerAdapter(Protocol):
    def queue_call(self, lead_id: str, script: str) -> str: ...   # human dials
    def status(self, call_id: str) -> str: ...
    def log_outcome(self, call_id: str, outcome: dict) -> None: ...


@runtime_checkable
class EmailSender(Protocol):
    def send(self, to: str, subject: str, body: str, headers: dict) -> str: ...
    def suppression_check(self, email: str) -> bool: ...          # internal opt-out


@runtime_checkable
class LinkedInQueue(Protocol):
    """NEVER auto-sends. Queues drafts for a human to send in LinkedIn's own UI."""
    def queue_draft(self, lead_id: str, kind: str, body: str) -> str: ...
    def mark_sent_by_human(self, queue_id: str) -> None: ...


@runtime_checkable
class EnrichmentAdapter(Protocol):
    def company(self, domain: str) -> dict: ...
    def contact(self, name: str, company: str) -> dict: ...
    def phone_type(self, phone: str) -> str: ...                  # business_landline|mobile


@runtime_checkable
class CalendarAdapter(Protocol):
    def book(self, lead_id: str, slot: str, kind: str) -> str: ...
    def availability(self) -> list[str]: ...


@runtime_checkable
class RegisterScrubber(Protocol):
    """DNC (US) / TPS-CTPS (UK) / DNCR (AU) scrub."""
    def scrub(self, phone: str, jurisdiction: str) -> dict: ...   # {listed, checked_at, fresh}


@dataclass
class Deps:
    """Dependency container injected at graph-build time."""
    crm: CRMAdapter
    dialer: DialerAdapter
    email: EmailSender
    linkedin: LinkedInQueue
    enrich: EnrichmentAdapter
    cal: CalendarAdapter
    scrub: RegisterScrubber
