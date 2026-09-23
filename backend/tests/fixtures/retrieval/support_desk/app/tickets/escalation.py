"""Escalation rules for tickets that breach their service-level agreement.

This class is deliberately longer than one chunk so the chunker has to split it
into a class header plus one chunk per method.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

FIRST_RESPONSE_MINUTES = 30
RESOLUTION_MINUTES = 480
TIERS = ("agent", "senior_agent", "manager", "director")


@dataclass
class Breach:
    ticket_id: str
    kind: str
    minutes_late: int
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


class EscalationPolicy:
    """Decides when a ticket moves up a tier and who should look at it next."""

    def __init__(self, tiers: tuple[str, ...] = TIERS) -> None:
        self.tiers = tiers
        self._breaches: dict[str, list[Breach]] = {}
        self._tier_of: dict[str, int] = {}

    def is_overdue(self, ticket_id: str, opened_at: datetime, responded: bool) -> bool:
        """True when a ticket has missed its first-response or resolution deadline."""
        deadline_minutes = FIRST_RESPONSE_MINUTES if not responded else RESOLUTION_MINUTES
        deadline = opened_at + timedelta(minutes=deadline_minutes)
        return datetime.now(UTC) > deadline

    def record_breach(self, ticket_id: str, kind: str, minutes_late: int) -> Breach:
        """Remember that a ticket missed a deadline, for reporting and escalation."""
        breach = Breach(ticket_id=ticket_id, kind=kind, minutes_late=minutes_late)
        self._breaches.setdefault(ticket_id, []).append(breach)
        return breach

    def escalate_to_manager(self, ticket_id: str, reason: str) -> str:
        """Move an overdue ticket up to the manager tier and return the new owner tier.

        Escalation is capped at the highest configured tier, so repeatedly escalating
        an already-escalated ticket is harmless.
        """
        current = self._tier_of.get(ticket_id, 0)
        manager_index = self.tiers.index("manager") if "manager" in self.tiers else len(self.tiers) - 1
        target = min(max(current + 1, manager_index), len(self.tiers) - 1)
        self._tier_of[ticket_id] = target
        self.record_breach(ticket_id, kind=reason, minutes_late=0)
        return self.tiers[target]

    def deescalate(self, ticket_id: str) -> str:
        """Return a ticket to the tier below its current one after it is under control."""
        current = self._tier_of.get(ticket_id, 0)
        target = max(current - 1, 0)
        self._tier_of[ticket_id] = target
        return self.tiers[target]

    def next_reviewer(self, ticket_id: str, roster: dict[str, list[str]]) -> str | None:
        """Pick the first person on the roster for the ticket's current tier."""
        tier = self.tiers[self._tier_of.get(ticket_id, 0)]
        candidates = roster.get(tier, [])
        return candidates[0] if candidates else None

    def breach_summary(self, ticket_id: str) -> dict[str, int]:
        """Count breaches per kind so dashboards can show where time is being lost."""
        summary: dict[str, int] = {}
        for breach in self._breaches.get(ticket_id, []):
            summary[breach.kind] = summary.get(breach.kind, 0) + 1
        return summary

    def snooze(self, ticket_id: str, minutes: int) -> datetime:
        """Pause escalation for a ticket that is waiting on the requester."""
        until = datetime.now(UTC) + timedelta(minutes=minutes)
        self._breaches.setdefault(ticket_id, [])
        return until

    def tier_of(self, ticket_id: str) -> str:
        """The tier a ticket currently sits at, defaulting to the first one."""
        return self.tiers[self._tier_of.get(ticket_id, 0)]

    def escalation_history(self, ticket_id: str) -> list[str]:
        """Human-readable list of every breach recorded against a ticket."""
        return [
            f"{breach.at.isoformat()} {breach.kind} ({breach.minutes_late} minutes late)"
            for breach in self._breaches.get(ticket_id, [])
        ]
