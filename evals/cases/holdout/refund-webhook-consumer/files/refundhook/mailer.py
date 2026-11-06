"""SMTP client. Vendored from the shop's shared notifications package."""

import smtplib
from email.message import EmailMessage


class MailError(Exception):
    """The relay did not accept the message. Nothing was sent."""


class Mailer:
    def __init__(self, host="smtp.mail.invalid", sender="refunds@shop.invalid", timeout=5.0):
        self._host = host
        self._sender = sender
        self._timeout = timeout

    def send(self, to, subject, body):
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(self._host, timeout=self._timeout) as smtp:
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise MailError(str(exc)) from exc
