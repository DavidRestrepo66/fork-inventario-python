"""
Tests del CreateSaleService con repositorios y auditor mockeados.
No tocan BD: el servicio se prueba en aislamiento.
Corren con: python manage.py test transactions.tests.test_services
"""

import unittest
from decimal import Decimal
from unittest.mock import Mock

from transactions.domain import Money
from transactions.exceptions import (
    InsufficientStockError,
    InvalidPurchaseError,
    InvalidSaleError,
    ItemNotFoundError,
    TransactionError,
)
from transactions.services import CreatePurchaseService, CreateSaleService


class CreateSaleServiceTests(unittest.TestCase):

    def setUp(self):
        self.inventory = Mock()
        self.sales = Mock()
        self.audit = Mock()
        self.service = CreateSaleService(
            self.inventory, self.sales, self.audit,
        )
        self.inventory.get_item_price.return_value = Money(Decimal("100"))
        self.inventory.check_stock_availability.return_value = None
        fake_sale = Mock()
        fake_sale.id = 42
        self.sales.create_from_aggregate.return_value = fake_sale

    def _execute(self, **overrides):
        kwargs = {
            "customer_id": 1,
            "items": [{"item_id": 10, "qty": 5}],
            "tax_percentage": Decimal("10"),
            "amount_paid": Decimal("600"),
            "user_id": 7,
        }
        kwargs.update(overrides)
        return self.service.execute(**kwargs)

    def test_happy_path_returns_created_sale(self):
        sale = self._execute()
        self.assertEqual(sale.id, 42)

    def test_happy_path_calls_repos_in_order(self):
        self._execute()
        self.inventory.check_stock_availability.assert_called_once_with({10: 5})
        self.sales.create_from_aggregate.assert_called_once()
        self.inventory.reduce_stock_batch.assert_called_once_with({10: 5})

    def test_happy_path_audits_with_grand_total(self):
        self._execute()
        # subtotal = 5 * 100 = 500, tax 10% = 50 -> grand_total 550
        kwargs = self.audit.log_sale_created.call_args.kwargs
        self.assertEqual(kwargs["sale_id"], 42)
        self.assertEqual(kwargs["customer_id"], 1)
        self.assertEqual(kwargs["total"], Decimal("550.00"))
        self.assertEqual(kwargs["user_id"], 7)

    def test_insufficient_stock_does_not_create_sale(self):
        self.inventory.check_stock_availability.side_effect = (
            InsufficientStockError(10, 100, 3)
        )
        with self.assertRaises(InsufficientStockError):
            self._execute(items=[{"item_id": 10, "qty": 100}],
                          amount_paid=Decimal("99999"))
        self.sales.create_from_aggregate.assert_not_called()
        self.inventory.reduce_stock_batch.assert_not_called()
        self.audit.log_sale_failed.assert_called_once()
        self.audit.log_sale_created.assert_not_called()

    def test_empty_items_raises_invalid_sale(self):
        with self.assertRaises(InvalidSaleError):
            self._execute(items=[], amount_paid=Decimal("0"))
        self.audit.log_sale_failed.assert_called_once()
        self.sales.create_from_aggregate.assert_not_called()

    def test_item_without_qty_raises_invalid_sale(self):
        with self.assertRaises(InvalidSaleError):
            self._execute(items=[{"item_id": 1}],  # falta 'qty'
                          amount_paid=Decimal("0"))
        self.audit.log_sale_failed.assert_called_once()

    def test_underpayment_translates_to_invalid_sale(self):
        with self.assertRaises(InvalidSaleError) as ctx:
            # subtotal 500, sin tax -> grand_total 500; pago 100 -> underpaid
            self._execute(tax_percentage=Decimal("0"),
                          amount_paid=Decimal("100"))
        self.assertTrue(
            "amount_paid" in str(ctx.exception)
            or "grand_total" in str(ctx.exception)
        )
        self.sales.create_from_aggregate.assert_not_called()
        self.audit.log_sale_failed.assert_called_once()

    def test_unexpected_exception_is_not_masked(self):
        class WeirdError(RuntimeError):
            pass

        self.sales.create_from_aggregate.side_effect = WeirdError("boom")

        with self.assertRaises(WeirdError):
            self._execute()

        # No fue traducido a una excepción de dominio
        self.audit.log_sale_failed.assert_called_once()
        reason = self.audit.log_sale_failed.call_args.kwargs["reason"]
        self.assertIn("unexpected", reason)
        self.assertIn("WeirdError", reason)

    def test_transaction_error_from_repo_is_audited_and_reraised(self):
        self.sales.create_from_aggregate.side_effect = TransactionError(
            "Customer 1 not found"
        )
        with self.assertRaises(TransactionError):
            self._execute()
        self.audit.log_sale_failed.assert_called_once()
        self.sales.create_from_aggregate.assert_called_once()


class CreatePurchaseServiceTests(unittest.TestCase):

    def setUp(self):
        self.inventory = Mock()
        self.purchases = Mock()
        self.audit = Mock()
        self.service = CreatePurchaseService(
            self.inventory, self.purchases, self.audit,
        )
        fake_purchase = Mock()
        fake_purchase.id = 99
        fake_purchase.total_value = Decimal("500")
        self.purchases.create.return_value = fake_purchase

    def _execute(self, **overrides):
        kwargs = {
            "item_id": 10,
            "vendor_id": 5,
            "quantity": 25,
            "price": Decimal("20"),
            "user_id": 7,
        }
        kwargs.update(overrides)
        return self.service.execute(**kwargs)

    def test_happy_path_returns_created_purchase(self):
        purchase = self._execute()
        self.assertEqual(purchase.id, 99)

    def test_happy_path_creates_then_increases_stock(self):
        self._execute()
        self.purchases.create.assert_called_once()
        self.inventory.increase_stock.assert_called_once_with(10, 25)
        # Audit fires AFTER stock increment with correct kwargs
        kwargs = self.audit.log_purchase_created.call_args.kwargs
        self.assertEqual(kwargs["purchase_id"], 99)
        self.assertEqual(kwargs["item_id"], 10)
        self.assertEqual(kwargs["vendor_id"], 5)
        self.assertEqual(kwargs["quantity"], 25)
        self.assertEqual(kwargs["total_value"], Decimal("500"))
        self.assertEqual(kwargs["user_id"], 7)

    def test_rejects_zero_quantity(self):
        with self.assertRaises(InvalidPurchaseError):
            self._execute(quantity=0)
        self.purchases.create.assert_not_called()
        self.inventory.increase_stock.assert_not_called()
        self.audit.log_purchase_failed.assert_called_once()

    def test_rejects_negative_quantity(self):
        with self.assertRaises(InvalidPurchaseError):
            self._execute(quantity=-5)
        self.purchases.create.assert_not_called()
        self.audit.log_purchase_failed.assert_called_once()

    def test_rejects_negative_price(self):
        with self.assertRaises(InvalidPurchaseError):
            self._execute(price=Decimal("-1"))
        self.purchases.create.assert_not_called()
        self.audit.log_purchase_failed.assert_called_once()

    def test_item_not_found_does_not_increase_stock(self):
        self.purchases.create.side_effect = ItemNotFoundError(10)
        with self.assertRaises(ItemNotFoundError):
            self._execute()
        self.inventory.increase_stock.assert_not_called()
        self.audit.log_purchase_failed.assert_called_once()
        self.audit.log_purchase_created.assert_not_called()

    def test_vendor_not_found_is_audited_and_reraised(self):
        self.purchases.create.side_effect = TransactionError("Vendor 5 not found")
        with self.assertRaises(TransactionError):
            self._execute()
        self.inventory.increase_stock.assert_not_called()
        self.audit.log_purchase_failed.assert_called_once()

    def test_unexpected_exception_is_not_masked(self):
        class WeirdError(RuntimeError):
            pass

        self.inventory.increase_stock.side_effect = WeirdError("boom")
        with self.assertRaises(WeirdError):
            self._execute()
        self.audit.log_purchase_failed.assert_called_once()
        reason = self.audit.log_purchase_failed.call_args.kwargs["reason"]
        self.assertIn("unexpected", reason)
        self.assertIn("WeirdError", reason)


if __name__ == "__main__":
    unittest.main()
