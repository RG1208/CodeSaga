"""Outgoing email notifications over SMTP."""

import smtplib
from email.message import EmailMessage

DEFAULT_SENDER = "support@example.test"


class EmailNotifier:
    def __init__(self, host: str, port: int = 587, sender: str = DEFAULT_SENDER) -> None:
        self.host = host
        self.port = port
        self.sender = sender

    def send_email(self, recipient: str, subject: str, body: str) -> None:
        """Deliver a plain-text message to one recipient."""
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(self.host, self.port) as client:
            client.send_message(message)

    def send_ticket_receipt(self, recipient: str, ticket_id: str) -> None:
        self.send_email(recipient, f"Ticket {ticket_id} received", "We are on it.")
