"""In-memory, deterministic mock adapters for dev + tests.

Every mock records what it received so tests can assert on side effects
(e.g. MockEmail.sent, MockDialer.queued, MockLinkedInQueue.queue).
"""
from __future__ import annotations

from .base import Deps


class MockCRM:
    def __init__(self) -> None:
        self.leads: dict[str, dict] = {}
        self.deals: dict[str, dict] = {}
        self.activities: list[tuple[str, dict]] = []

    def upsert_lead(self, lead: dict) -> str:
        lid = lead["lead_id"]
        self.leads[lid] = {**self.leads.get(lid, {}), **lead}
        return lid

    def upsert_deal(self, deal: dict) -> str:
        did = deal.get("deal_id") or f"deal-{len(self.deals) + 1}"
        self.deals[did] = {**self.deals.get(did, {}), **deal, "deal_id": did}
        return did

    def log_activity(self, lead_id: str, activity: dict) -> None:
        self.activities.append((lead_id, activity))

    def enrich(self, domain: str) -> dict:
        return {"size": "50-200", "industry": "structural steel fabrication", "segment": "fabricator"}


class MockDialer:
    def __init__(self) -> None:
        self.queued: list[tuple[str, str]] = []
        self.outcomes: list[tuple[str, dict]] = []

    def queue_call(self, lead_id: str, script: str) -> str:
        self.queued.append((lead_id, script))
        return f"mock-call-{lead_id}"

    def status(self, call_id: str) -> str:
        return "queued"

    def log_outcome(self, call_id: str, outcome: dict) -> None:
        self.outcomes.append((call_id, outcome))


class MockEmail:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.suppressed: set[str] = set()

    def send(self, to: str, subject: str, body: str, headers: dict) -> str:
        self.sent.append({"to": to, "subject": subject, "body": body, "headers": headers})
        return f"msg-{len(self.sent)}"

    def suppression_check(self, email: str) -> bool:
        return email in self.suppressed


class MockLinkedInQueue:
    def __init__(self) -> None:
        # each item: {queue_id, lead_id, kind, body, status}
        self.queue: list[dict] = []

    def queue_draft(self, lead_id: str, kind: str, body: str) -> str:
        qid = f"li-{len(self.queue) + 1}"
        self.queue.append(
            {"queue_id": qid, "lead_id": lead_id, "kind": kind, "body": body,
             "status": "pending_human_send"}
        )
        return qid

    def mark_sent_by_human(self, queue_id: str) -> None:
        for item in self.queue:
            if item["queue_id"] == queue_id:
                item["status"] = "sent_by_human"


class MockEnrichment:
    def company(self, domain: str) -> dict:
        return {"size": "50-200", "segment": "fabricator", "jurisdiction": "US",
                "industry": "structural steel fabrication"}

    def contact(self, name: str, company: str) -> dict:
        return {"email": f"contact@{company.lower().replace(' ', '')}.com",
                "phone": "+12145551234", "title": "Chief Estimator",
                "linkedin_url": "https://www.linkedin.com/in/example"}

    def phone_type(self, phone: str) -> str:
        return "business_landline"


class MockCalendar:
    def __init__(self) -> None:
        self.bookings: list[dict] = []

    def book(self, lead_id: str, slot: str, kind: str) -> str:
        bid = f"booking-{len(self.bookings) + 1}"
        self.bookings.append({"booking_id": bid, "lead_id": lead_id, "slot": slot, "kind": kind})
        return bid

    def availability(self) -> list[str]:
        return ["2026-06-02T15:00:00Z", "2026-06-03T16:00:00Z", "2026-06-04T14:00:00Z"]


class MockScrubber:
    """By default nothing is listed and scrubs are fresh. Tests can register
    listed numbers or force staleness."""
    def __init__(self) -> None:
        self.listed: set[str] = set()
        self.force_stale: bool = False

    def scrub(self, phone: str, jurisdiction: str) -> dict:
        return {
            "listed": phone in self.listed,
            "checked_at": "2026-05-31T00:00:00Z",
            "fresh": not self.force_stale,
            "jurisdiction": jurisdiction,
        }


def mock_deps() -> Deps:
    """Convenience factory: a Deps bundle wired entirely with mocks."""
    return Deps(
        crm=MockCRM(),
        dialer=MockDialer(),
        email=MockEmail(),
        linkedin=MockLinkedInQueue(),
        enrich=MockEnrichment(),
        cal=MockCalendar(),
        scrub=MockScrubber(),
    )
