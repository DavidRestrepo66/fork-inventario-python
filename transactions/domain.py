"""
Entidades de dominio puro para transacciones.
Independientes de Django — solo lógica de negocio.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Money:
    """Valor monetario inmutable. Garantiza no-negativo y consistencia de divisa."""
    amount: Decimal
    currency: str = "USD"

    def __post_init__(self):
        if self.amount < 0:
            raise ValueError(f"Money amount cannot be negative: {self.amount}")

    def __add__(self, other):
        if not isinstance(other, Money):
            raise TypeError(f"Cannot add Money to {type(other).__name__}")
        if self.currency != other.currency:
            raise TypeError(
                f"Cannot add Money with different currencies: "
                f"{self.currency} and {other.currency}"
            )
        return Money(self.amount + other.amount, self.currency)

    def __mul__(self, scalar):
        if not isinstance(scalar, (int, float, Decimal)):
            raise TypeError(f"Cannot multiply Money by {type(scalar).__name__}")
        return Money(self.amount * Decimal(str(scalar)), self.currency)


@dataclass(frozen=True)
class PriceSnapshot:
    """Precio de un item capturado en un instante. Garantiza histórico inmutable."""
    amount: Decimal
    captured_at: datetime
    item_id: int

    def to_money(self) -> Money:
        return Money(self.amount)


@dataclass(frozen=True)
class SaleLineItem:
    """Línea individual de una venta."""
    item_id: int
    quantity: int
    price_snapshot: PriceSnapshot

    def __post_init__(self):
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {self.quantity}")
        if self.quantity > 1000:
            raise ValueError(
                f"Quantity cannot exceed 1,000, got {self.quantity}"
            )

    @property
    def total(self) -> Money:
        return self.price_snapshot.to_money() * self.quantity

    def to_dict(self):
        return {
            'item_id': self.item_id,
            'quantity': self.quantity,
            'price': self.price_snapshot.amount,
            'total': self.total.amount,
        }


@dataclass(frozen=True)
class SaleAggregate:
    """
    Agregado de venta completa. Inmutable.
    Tras persistir, usar dataclasses.replace(agg, id=new_id) para obtener
    la versión con id poblado.
    """
    id: int | None = None
    customer_id: int | None = None
    line_items: list[SaleLineItem] | None = None
    tax_percentage: Decimal = Decimal("0")
    amount_paid: Decimal | None = None
    notes: str = ""

    def __post_init__(self):
        if not self.line_items:
            raise ValueError("Sale must have at least one line item")

        if not 0 <= self.tax_percentage <= 100:
            raise ValueError(
                f"Tax percentage must be 0-100, got {self.tax_percentage}"
            )

        if not self.customer_id:
            raise ValueError("Customer ID is required")

        if self.amount_paid is None:
            raise ValueError("amount_paid is required")

        if self.amount_paid < self.grand_total.amount:
            raise ValueError(
                f"amount_paid ({self.amount_paid}) must be >= "
                f"grand_total ({self.grand_total.amount})"
            )

    @property
    def subtotal(self) -> Money:
        result = Money(Decimal("0"))
        for line in self.line_items:
            result = result + line.total
        return result

    @property
    def tax_amount(self) -> Money:
        tax = self.subtotal.amount * (self.tax_percentage / 100)
        return Money(tax)

    @property
    def grand_total(self) -> Money:
        return self.subtotal + self.tax_amount

    @property
    def amount_change(self) -> Money:
        return Money(self.amount_paid - self.grand_total.amount)

    def to_dict(self):
        return {
            'customer_id': self.customer_id,
            'subtotal': self.subtotal.amount,
            'tax_amount': self.tax_amount.amount,
            'tax_percentage': self.tax_percentage,
            'grand_total': self.grand_total.amount,
            'amount_paid': self.amount_paid,
            'amount_change': self.amount_change.amount,
            'line_items': [item.to_dict() for item in self.line_items],
            'notes': self.notes,
        }
