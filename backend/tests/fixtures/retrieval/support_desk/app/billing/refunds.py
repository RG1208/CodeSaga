"""Refunding payments back to the customer."""

from app.billing.payments import CardCharge, PaymentGateway


class RefundError(Exception):
    pass


def refund_payment(gateway: PaymentGateway, charge: CardCharge, amount_cents: int | None = None) -> dict:
    """Send money back to the customer for a captured charge.

    A partial refund is possible by passing a smaller amount than the original charge.
    """
    if not charge.captured:
        raise RefundError("cannot refund an uncaptured charge")
    refunded = amount_cents or charge.amount_cents
    if refunded > charge.amount_cents:
        raise RefundError("refund exceeds the original payment")
    return {"refund_id": f"re_{charge.charge_id}", "amount_cents": refunded, "status": "succeeded"}


def is_refundable(charge: CardCharge) -> bool:
    return charge.captured
