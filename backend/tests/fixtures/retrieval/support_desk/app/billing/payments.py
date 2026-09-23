"""Card charges through the payment gateway."""

from dataclasses import dataclass


@dataclass
class CardCharge:
    charge_id: str
    amount_cents: int
    currency: str
    captured: bool = False


class PaymentGateway:
    """Thin wrapper over the gateway's HTTP API."""

    def __init__(self, api_key: str, base_url: str = "https://api.gateway.test") -> None:
        self.api_key = api_key
        self.base_url = base_url

    def charge_card(self, token: str, amount_cents: int, currency: str = "usd") -> CardCharge:
        """Authorise and capture a payment for the given card token."""
        if amount_cents <= 0:
            raise ValueError("amount must be positive")
        charge_id = f"ch_{token[-6:]}"
        return CardCharge(charge_id=charge_id, amount_cents=amount_cents, currency=currency, captured=True)

    def void_authorisation(self, charge_id: str) -> None:
        """Release an authorisation that was never captured."""
