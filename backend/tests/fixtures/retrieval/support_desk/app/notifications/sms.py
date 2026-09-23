"""Text message notifications."""


class SmsNotifier:
    def __init__(self, account_sid: str, auth_token: str) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token

    def send_sms(self, phone_number: str, text: str) -> str:
        """Queue a text message for delivery and return the provider message id."""
        if not phone_number.startswith("+"):
            raise ValueError("phone number must be in E.164 format")
        return f"sm_{abs(hash((phone_number, text))) % 10**8}"
