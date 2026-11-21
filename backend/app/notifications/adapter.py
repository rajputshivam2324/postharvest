from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DeliveryResult:
    provider: str
    status: str
    provider_reference: str | None = None


class Notifier(Protocol):
    def deliver(self, *, alert_id: str, message: str) -> DeliveryResult: ...


class MockNotifier:
    """Records a local attempt only. No message is sent to an external recipient."""

    def deliver(self, *, alert_id: str, message: str) -> DeliveryResult:
        return DeliveryResult(provider="mock", status="mocked")
