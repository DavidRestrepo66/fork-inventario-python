"""
Tests del dominio puro. No requieren Django.
Corren con: python -m unittest transactions.tests.test_domain
"""

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from decimal import Decimal

from transactions.domain import (
    Money,
    PriceSnapshot,
    SaleAggregate,
    SaleLineItem,
)


def _snapshot(amount="100", item_id=1):
    return PriceSnapshot(
        amount=Decimal(amount), captured_at=datetime.now(), item_id=item_id,
    )


def _line(qty=5, amount="100", item_id=1):
    return SaleLineItem(
        item_id=item_id, quantity=qty,
        price_snapshot=_snapshot(amount=amount, item_id=item_id),
    )


def _agg(amount_paid="600", tax="10", lines=None):
    return SaleAggregate(
        customer_id=42,
        line_items=lines or [_line()],
        tax_percentage=Decimal(tax),
        amount_paid=Decimal(amount_paid),
    )


class MoneyTests(unittest.TestCase):

    def test_creates_with_default_currency(self):
        m = Money(Decimal("100"))
        self.assertEqual(m.amount, Decimal("100"))
        self.assertEqual(m.currency, "USD")

    def test_rejects_negative_amount(self):
        with self.assertRaises(ValueError):
            Money(Decimal("-1"))

    def test_is_frozen(self):
        m = Money(Decimal("10"))
        with self.assertRaises(FrozenInstanceError):
            m.amount = Decimal("999")

    def test_addition_sums_amounts(self):
        self.assertEqual(
            Money(Decimal("10")) + Money(Decimal("20")),
            Money(Decimal("30")),
        )

    def test_addition_rejects_currency_mismatch(self):
        with self.assertRaises(TypeError):
            Money(Decimal("1"), "USD") + Money(Decimal("1"), "EUR")

    def test_addition_rejects_non_money(self):
        with self.assertRaises(TypeError):
            Money(Decimal("1")) + 5

    def test_multiplication_with_int(self):
        self.assertEqual(Money(Decimal("10")) * 3, Money(Decimal("30")))

    def test_multiplication_with_decimal(self):
        self.assertEqual(
            Money(Decimal("10")) * Decimal("2.5"),
            Money(Decimal("25.0")),
        )

    def test_multiplication_rejects_string(self):
        with self.assertRaises(TypeError):
            Money(Decimal("10")) * "x"


class PriceSnapshotTests(unittest.TestCase):

    def test_to_money_returns_amount_as_money(self):
        snap = _snapshot(amount="50")
        self.assertEqual(snap.to_money(), Money(Decimal("50")))


class SaleLineItemTests(unittest.TestCase):

    def test_rejects_zero_quantity(self):
        with self.assertRaises(ValueError):
            _line(qty=0)

    def test_rejects_negative_quantity(self):
        with self.assertRaises(ValueError):
            _line(qty=-1)

    def test_rejects_quantity_above_1000(self):
        with self.assertRaises(ValueError):
            _line(qty=1001)

    def test_accepts_boundary_quantity_1000(self):
        line = _line(qty=1000)
        self.assertEqual(line.quantity, 1000)

    def test_total_is_price_times_quantity(self):
        line = _line(qty=5, amount="50")
        self.assertEqual(line.total, Money(Decimal("250")))


class SaleAggregateTests(unittest.TestCase):

    def test_requires_line_items(self):
        with self.assertRaises(ValueError):
            SaleAggregate(
                customer_id=1, line_items=[],
                tax_percentage=Decimal("0"), amount_paid=Decimal("0"),
            )

    def test_requires_customer_id(self):
        with self.assertRaises(ValueError):
            SaleAggregate(
                line_items=[_line()],
                tax_percentage=Decimal("0"), amount_paid=Decimal("9999"),
            )

    def test_requires_amount_paid(self):
        with self.assertRaises(ValueError) as ctx:
            SaleAggregate(
                customer_id=1, line_items=[_line()],
                tax_percentage=Decimal("0"),
            )
        self.assertIn("amount_paid", str(ctx.exception))

    def test_rejects_tax_below_zero(self):
        with self.assertRaises(ValueError):
            _agg(tax="-1", amount_paid="9999")

    def test_rejects_tax_above_100(self):
        with self.assertRaises(ValueError):
            _agg(tax="101", amount_paid="9999")

    def test_rejects_underpayment(self):
        # line = qty 5 * 100 = 500, tax 10% => grand_total 550
        with self.assertRaises(ValueError) as ctx:
            _agg(amount_paid="500", tax="10")
        self.assertIn("grand_total", str(ctx.exception))

    def test_subtotal_sums_all_lines(self):
        agg = SaleAggregate(
            customer_id=1,
            line_items=[
                _line(qty=5, amount="100"),  # 500
                _line(qty=2, amount="30", item_id=2),  # 60
            ],
            tax_percentage=Decimal("0"),
            amount_paid=Decimal("560"),
        )
        self.assertEqual(agg.subtotal, Money(Decimal("560")))

    def test_tax_amount_uses_percentage(self):
        agg = _agg(tax="10", amount_paid="550")  # 500 * 0.10 = 50
        self.assertEqual(agg.tax_amount, Money(Decimal("50.0")))

    def test_grand_total_includes_tax(self):
        agg = _agg(tax="10", amount_paid="550")
        self.assertEqual(agg.grand_total, Money(Decimal("550.0")))

    def test_amount_change_when_overpaid(self):
        agg = _agg(tax="10", amount_paid="600")  # grand_total 550
        self.assertEqual(agg.amount_change, Money(Decimal("50.0")))

    def test_amount_change_zero_when_exact(self):
        agg = _agg(tax="10", amount_paid="550")
        self.assertEqual(agg.amount_change, Money(Decimal("0.0")))

    def test_replace_assigns_id_immutably(self):
        agg = _agg()
        saved = replace(agg, id=123)
        self.assertEqual(saved.id, 123)
        self.assertEqual(saved.customer_id, agg.customer_id)
        self.assertIsNone(agg.id)  # original sigue intacto

    def test_to_dict_includes_payment_fields(self):
        agg = _agg(tax="10", amount_paid="600")
        d = agg.to_dict()
        self.assertEqual(d["amount_paid"], Decimal("600"))
        self.assertEqual(d["amount_change"], Decimal("50.0"))
        self.assertEqual(d["grand_total"], Decimal("550.0"))


if __name__ == "__main__":
    unittest.main()
