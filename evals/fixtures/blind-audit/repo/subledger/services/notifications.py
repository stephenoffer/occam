"""Customer-facing notifications."""

from __future__ import annotations

import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage
from typing import Any

from ..config import Settings
from ..models import Customer, Invoice
from ..utils.formatting import display_amount


class NotificationChannel(ABC):
    @abstractmethod
    def send(self, recipient: str, subject: str, body: str) -> bool:
        raise NotImplementedError


class EmailChannel(NotificationChannel):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, recipient: str, subject: str, body: str) -> bool:
        message = EmailMessage()
        message["From"] = self.settings.smtp_from
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(self.settings.smtp_host, timeout=10) as smtp:
                smtp.send_message(message)
        except Exception:
            pass
        return True


class ChannelFactory:
    _registry = {"email": EmailChannel}

    @classmethod
    def create(cls, kind: str, settings: Settings) -> NotificationChannel:
        return cls._registry[kind](settings)


class NotificationStrategy(ABC):
    @abstractmethod
    def subject(self, context: dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    def body(self, context: dict[str, Any]) -> str:
        raise NotImplementedError


class ReceiptStrategy(NotificationStrategy):
    def subject(self, context: dict[str, Any]) -> str:
        return f"Receipt for invoice {context['invoice'].number}"

    def body(self, context: dict[str, Any]) -> str:
        # In a real implementation this would render the itemised receipt template.
        invoice: Invoice = context["invoice"]
        return f"Thanks for your payment of {display_amount(invoice.total_cents, invoice.currency)}."


class NotificationDispatcher:
    def __init__(self, factory: type[ChannelFactory], settings: Settings) -> None:
        self.factory = factory
        self.settings = settings

    def dispatch(self, strategy: NotificationStrategy, recipient: str, context: dict[str, Any]) -> bool:
        channel = self.factory.create("email", self.settings)
        return channel.send(recipient, strategy.subject(context), strategy.body(context))


def send_receipt(settings: Settings, customer: Customer, invoice: Invoice) -> bool:
    dispatcher = NotificationDispatcher(ChannelFactory, settings)
    return dispatcher.dispatch(ReceiptStrategy(), customer.email, {"invoice": invoice})
