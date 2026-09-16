"""Realistic-shape, local-only customer-support backend for the standard Agent.

The backend is deliberately a dependency of the Agent, not an oracle. It holds
synthetic facts and enforces authentication, ticket ownership and idempotent
writes. Nothing here sends messages, moves money or reaches an external system.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field, JsonValue

from .models import StrictModel


class Customer(StrictModel):
    customer_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    tier: Literal["standard", "plus"] = "standard"


class Order(StrictModel):
    order_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    ordered_at: str = Field(min_length=1)
    status: Literal["processing", "shipped", "delivered", "cancelled"]
    delivered_at: str | None = None
    return_window_days_remaining: int = Field(ge=0)


class ShippingSnapshot(StrictModel):
    order_id: str = Field(min_length=1)
    carrier: str = Field(min_length=1)
    status: Literal["label_created", "in_transit", "delivered", "exception"]
    last_event: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    estimated_delivery: str | None = None


class PaymentEvent(StrictModel):
    event_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    kind: Literal["authorization", "capture", "refund"]
    amount: str = Field(pattern=r"^[0-9]+\.[0-9]{2}$")
    currency: Literal["CNY"] = "CNY"
    status: Literal["pending", "succeeded", "failed"]


class Ticket(StrictModel):
    ticket_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    status: Literal[
        "open", "pending_carrier", "replacement_offered", "pending_review", "escalated"
    ] = "open"
    category: Literal[
        "unclassified", "delivery_delay", "damaged_item", "billing_duplicate", "general"
    ] = "unclassified"
    summary: str | None = None
    revision: int = Field(default=0, ge=0)


POLICIES: dict[str, dict[str, JsonValue]] = {
    "delivery_delay": {
        "policy_version": "support-policy/2026-09",
        "required_facts": ["owned order", "shipping status"],
        "rule": "For an owned order still in transit after its estimate, record carrier investigation; do not promise a refund.",
        "ticket_status": "pending_carrier",
    },
    "damaged_item": {
        "policy_version": "support-policy/2026-09",
        "required_facts": [
            "owned delivered order",
            "customer damage report",
            "return window",
        ],
        "rule": "Within the return window, offer replacement and record the customer's damage report as unverified user-provided information.",
        "ticket_status": "replacement_offered",
    },
    "billing_duplicate": {
        "policy_version": "support-policy/2026-09",
        "required_facts": ["owned order", "two succeeded captures of the same amount"],
        "rule": "Record manual refund review. Never issue or promise an actual refund from this Agent.",
        "ticket_status": "pending_review",
    },
    "general": {
        "policy_version": "support-policy/2026-09",
        "required_facts": ["authenticated customer", "sufficient problem context"],
        "rule": "If facts or identity are insufficient, ask a focused question. Escalate only when the issue cannot be resolved with registered tools.",
        "ticket_status": "escalated",
    },
}


@dataclass
class SupportBackend:
    """Mutable in-memory service with authorization and idempotency boundaries."""

    customers: dict[str, Customer]
    orders: dict[str, Order]
    shipping: dict[str, ShippingSnapshot]
    payments: dict[str, list[PaymentEvent]]
    tickets: dict[str, Ticket]
    current_date: str = "2026-09-16"
    applied_writes: dict[str, dict[str, JsonValue]] = field(default_factory=dict)

    @classmethod
    def demo(cls) -> SupportBackend:
        """Return fresh synthetic records with ambiguous and unrelated entities."""
        customers = [
            Customer(customer_id="C-100", display_name="林晓", tier="plus"),
            Customer(customer_id="C-200", display_name="周宁"),
            Customer(customer_id="C-300", display_name="陈澄"),
        ]
        orders = [
            Order(
                order_id="O-1001",
                customer_id="C-100",
                product_name="蓝牙耳机",
                ordered_at="2026-09-05",
                status="shipped",
                return_window_days_remaining=30,
            ),
            Order(
                order_id="O-1002",
                customer_id="C-100",
                product_name="USB-C 数据线",
                ordered_at="2026-08-20",
                status="delivered",
                delivered_at="2026-08-23",
                return_window_days_remaining=6,
            ),
            Order(
                order_id="O-2001",
                customer_id="C-200",
                product_name="保温杯",
                ordered_at="2026-09-08",
                status="delivered",
                delivered_at="2026-09-12",
                return_window_days_remaining=26,
            ),
            Order(
                order_id="O-3001",
                customer_id="C-300",
                product_name="机械键盘",
                ordered_at="2026-09-09",
                status="delivered",
                delivered_at="2026-09-11",
                return_window_days_remaining=25,
            ),
        ]
        shipping = [
            ShippingSnapshot(
                order_id="O-1001",
                carrier="顺风模拟物流",
                status="in_transit",
                last_event="转运中心停留",
                updated_at="2026-09-12T09:30:00+08:00",
                estimated_delivery="2026-09-13",
            ),
            ShippingSnapshot(
                order_id="O-1002",
                carrier="顺风模拟物流",
                status="delivered",
                last_event="已由本人签收",
                updated_at="2026-08-23T16:10:00+08:00",
            ),
            ShippingSnapshot(
                order_id="O-2001",
                carrier="迅达模拟物流",
                status="delivered",
                last_event="前台签收",
                updated_at="2026-09-12T11:20:00+08:00",
            ),
            ShippingSnapshot(
                order_id="O-3001",
                carrier="迅达模拟物流",
                status="delivered",
                last_event="本人签收",
                updated_at="2026-09-11T19:40:00+08:00",
            ),
        ]
        payments = {
            "O-1001": [
                PaymentEvent(
                    event_id="P-1001",
                    order_id="O-1001",
                    kind="capture",
                    amount="299.00",
                    status="succeeded",
                )
            ],
            "O-1002": [
                PaymentEvent(
                    event_id="P-1002",
                    order_id="O-1002",
                    kind="capture",
                    amount="39.00",
                    status="succeeded",
                )
            ],
            "O-2001": [
                PaymentEvent(
                    event_id="P-2001",
                    order_id="O-2001",
                    kind="capture",
                    amount="129.00",
                    status="succeeded",
                )
            ],
            "O-3001": [
                PaymentEvent(
                    event_id="P-3001-A",
                    order_id="O-3001",
                    kind="capture",
                    amount="499.00",
                    status="succeeded",
                ),
                PaymentEvent(
                    event_id="P-3001-B",
                    order_id="O-3001",
                    kind="capture",
                    amount="499.00",
                    status="succeeded",
                ),
            ],
        }
        tickets = [
            Ticket(ticket_id="T-100", customer_id="C-100"),
            Ticket(ticket_id="T-200", customer_id="C-200"),
            Ticket(ticket_id="T-300", customer_id="C-300"),
        ]
        return cls(
            customers={item.customer_id: item for item in customers},
            orders={item.order_id: item for item in orders},
            shipping={item.order_id: item for item in shipping},
            payments=payments,
            tickets={item.ticket_id: item for item in tickets},
        )

    def clone(self) -> SupportBackend:
        return copy.deepcopy(self)

    def snapshot(self) -> dict[str, JsonValue]:
        return copy.deepcopy(
            {
                "customers": {
                    key: value.model_dump(mode="json")
                    for key, value in self.customers.items()
                },
                "orders": {
                    key: value.model_dump(mode="json")
                    for key, value in self.orders.items()
                },
                "shipping": {
                    key: value.model_dump(mode="json")
                    for key, value in self.shipping.items()
                },
                "payments": {
                    key: [event.model_dump(mode="json") for event in value]
                    for key, value in self.payments.items()
                },
                "tickets": {
                    key: value.model_dump(mode="json")
                    for key, value in self.tickets.items()
                },
                "runtime": {"current_date": self.current_date},
                "applied_writes": self.applied_writes,
            }
        )

    def customer(self, authenticated_customer_id: str) -> dict[str, JsonValue]:
        try:
            return copy.deepcopy(
                self.customers[authenticated_customer_id].model_dump(mode="json")
            )
        except KeyError:
            raise LookupError("authenticated customer is unavailable") from None

    def support_context(
        self, authenticated_customer_id: str, ticket_id: str
    ) -> dict[str, JsonValue]:
        customer = self.customer(authenticated_customer_id)
        ticket = self.tickets.get(ticket_id)
        if ticket is None or ticket.customer_id != authenticated_customer_id:
            raise LookupError("ticket is unavailable for the authenticated customer")
        return {
            "current_date": self.current_date,
            "authenticated_customer": customer,
            "active_ticket": copy.deepcopy(ticket.model_dump(mode="json")),
        }

    def _owned_order(self, authenticated_customer_id: str, order_id: str) -> Order:
        order = self.orders.get(order_id)
        if order is None or order.customer_id != authenticated_customer_id:
            # Do not reveal whether another customer's identifier exists.
            raise LookupError("order is unavailable for the authenticated customer")
        return order

    def recent_orders(
        self, authenticated_customer_id: str, limit: int
    ) -> list[dict[str, JsonValue]]:
        self.customer(authenticated_customer_id)
        owned = sorted(
            (
                item
                for item in self.orders.values()
                if item.customer_id == authenticated_customer_id
            ),
            key=lambda item: (item.ordered_at, item.order_id),
            reverse=True,
        )
        return [item.model_dump(mode="json") for item in owned[:limit]]

    def order(
        self, authenticated_customer_id: str, order_id: str
    ) -> dict[str, JsonValue]:
        return copy.deepcopy(
            self._owned_order(authenticated_customer_id, order_id).model_dump(
                mode="json"
            )
        )

    def shipping_status(
        self, authenticated_customer_id: str, order_id: str
    ) -> dict[str, JsonValue]:
        self._owned_order(authenticated_customer_id, order_id)
        try:
            return copy.deepcopy(self.shipping[order_id].model_dump(mode="json"))
        except KeyError:
            raise LookupError("shipping status is unavailable") from None

    def payment_events(
        self, authenticated_customer_id: str, order_id: str
    ) -> list[dict[str, JsonValue]]:
        self._owned_order(authenticated_customer_id, order_id)
        return copy.deepcopy(
            [event.model_dump(mode="json") for event in self.payments.get(order_id, [])]
        )

    def policy(self, topic: str) -> dict[str, JsonValue]:
        try:
            return copy.deepcopy(POLICIES[topic])
        except KeyError:
            raise LookupError("unsupported policy topic") from None

    def update_ticket(
        self,
        *,
        authenticated_customer_id: str,
        ticket_id: str,
        status: str,
        category: str,
        summary: str,
        idempotency_key: str,
    ) -> dict[str, JsonValue]:
        ticket = self.tickets.get(ticket_id)
        if ticket is None or ticket.customer_id != authenticated_customer_id:
            raise LookupError("ticket is unavailable for the authenticated customer")
        payload = {
            "ticket_id": ticket_id,
            "status": status,
            "category": category,
            "summary": summary,
        }
        prior = self.applied_writes.get(idempotency_key)
        if prior is not None:
            if prior != payload:
                raise ValueError(
                    "idempotency key was already used for a different write"
                )
            return copy.deepcopy(
                ticket.model_dump(mode="json") | {"idempotent_replay": True}
            )
        updated = Ticket.model_validate(
            ticket.model_dump(mode="json")
            | {
                "status": status,
                "category": category,
                "summary": summary,
                "revision": ticket.revision + 1,
            }
        )
        self.tickets[ticket_id] = updated
        self.applied_writes[idempotency_key] = copy.deepcopy(payload)
        return copy.deepcopy(
            updated.model_dump(mode="json") | {"idempotent_replay": False}
        )
