"""Support ticket workflow."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.notifications.email import EmailNotifier

OPEN = "open"
ASSIGNED = "assigned"
CLOSED = "closed"


@dataclass
class Ticket:
    ticket_id: str
    subject: str
    requester_email: str
    status: str = OPEN
    assignee: str | None = None
    history: list[str] = field(default_factory=list)


class TicketService:
    """Creates tickets, assigns them to agents and closes them."""

    def __init__(self, notifier: EmailNotifier) -> None:
        self.notifier = notifier
        self._tickets: dict[str, Ticket] = {}

    def create_ticket(self, subject: str, requester_email: str) -> Ticket:
        """Open a new support ticket and email a receipt to the requester."""
        ticket = Ticket(ticket_id=f"T-{len(self._tickets) + 1:04d}", subject=subject, requester_email=requester_email)
        self._tickets[ticket.ticket_id] = ticket
        self.notifier.send_ticket_receipt(requester_email, ticket.ticket_id)
        return ticket

    def assign_ticket(self, ticket_id: str, agent: str) -> Ticket:
        """Hand a ticket to a support agent."""
        ticket = self._tickets[ticket_id]
        ticket.assignee = agent
        ticket.status = ASSIGNED
        ticket.history.append(f"{datetime.now(UTC).isoformat()} assigned to {agent}")
        return ticket

    def close_ticket(self, ticket_id: str, resolution: str) -> Ticket:
        """Mark a ticket resolved and notify the requester."""
        ticket = self._tickets[ticket_id]
        ticket.status = CLOSED
        ticket.history.append(resolution)
        self.notifier.send_email(ticket.requester_email, f"Ticket {ticket_id} closed", resolution)
        return ticket
