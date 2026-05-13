"""
Servicios de aplicación: orquestan repositorios + dominio.
Aquí viven los límites de transacción (atomic).
"""

from datetime import datetime
from decimal import Decimal

from django.db import transaction

from .audit import AuditLogger
from .domain import PriceSnapshot, SaleAggregate, SaleLineItem
from .exceptions import (
    InsufficientStockError,
    InvalidPurchaseError,
    InvalidSaleError,
    ItemNotFoundError,
    TransactionError,
)
from .models import Purchase, Sale
from .repositories import (
    InventoryRepository,
    PurchaseRepository,
    SaleRepository,
)


class CreateSaleService:
    """Crea ventas de forma atómica y auditada."""

    def __init__(
        self,
        inventory_repo: InventoryRepository,
        sale_repo: SaleRepository,
        audit_logger: AuditLogger,
    ):
        self.inventory = inventory_repo
        self.sales = sale_repo
        self.audit = audit_logger

    def execute(
        self,
        customer_id: int,
        items: list[dict],
        tax_percentage: Decimal,
        amount_paid: Decimal,
        user_id: int | None = None,
    ) -> Sale:
        try:
            self._validate_input_shape(items)

            with transaction.atomic():
                line_items = self._build_line_items(items)

                aggregate = SaleAggregate(
                    customer_id=customer_id,
                    line_items=line_items,
                    tax_percentage=tax_percentage,
                    amount_paid=amount_paid,
                )

                stock_needed = {item['item_id']: item['qty'] for item in items}
                self.inventory.check_stock_availability(stock_needed)

                sale = self.sales.create_from_aggregate(aggregate)
                self.inventory.reduce_stock_batch(stock_needed)

                self.audit.log_sale_created(
                    sale_id=sale.id,
                    customer_id=customer_id,
                    total=aggregate.grand_total.amount,
                    user_id=user_id,
                )

                return sale

        except ValueError as e:
            self.audit.log_sale_failed(
                customer_id=customer_id, reason=str(e), user_id=user_id,
            )
            raise InvalidSaleError(str(e)) from e

        except (InsufficientStockError, ItemNotFoundError, TransactionError) as e:
            self.audit.log_sale_failed(
                customer_id=customer_id, reason=str(e), user_id=user_id,
            )
            raise

        except Exception as e:
            self.audit.log_sale_failed(
                customer_id=customer_id,
                reason=f"unexpected: {type(e).__name__}: {e}",
                user_id=user_id,
            )
            raise

    def _validate_input_shape(self, items: list[dict]) -> None:
        if not items:
            raise InvalidSaleError("Sale must have at least one item")
        for item in items:
            if 'item_id' not in item or 'qty' not in item:
                raise InvalidSaleError(
                    "Each item must have 'item_id' and 'qty' keys"
                )

    def _build_line_items(self, items: list[dict]) -> list[SaleLineItem]:
        result = []
        for item_data in items:
            price = self.inventory.get_item_price(item_data['item_id'])
            snapshot = PriceSnapshot(
                amount=price.amount,
                captured_at=datetime.now(),
                item_id=item_data['item_id'],
            )
            result.append(SaleLineItem(
                item_id=item_data['item_id'],
                quantity=item_data['qty'],
                price_snapshot=snapshot,
            ))
        return result


class CreatePurchaseService:
    """Crea compras de forma atómica y auditada (simétrico a CreateSaleService)."""

    def __init__(
        self,
        inventory_repo: InventoryRepository,
        purchase_repo: PurchaseRepository,
        audit_logger: AuditLogger,
    ):
        self.inventory = inventory_repo
        self.purchases = purchase_repo
        self.audit = audit_logger

    def execute(
        self,
        item_id: int,
        vendor_id: int,
        quantity: int,
        price: Decimal,
        description: str = "",
        delivery_date=None,
        delivery_status: str = "P",
        user_id: int | None = None,
    ) -> Purchase:
        try:
            self._validate(quantity, price)

            with transaction.atomic():
                purchase = self.purchases.create(
                    item_id=item_id,
                    vendor_id=vendor_id,
                    quantity=quantity,
                    price=price,
                    description=description,
                    delivery_date=delivery_date,
                    delivery_status=delivery_status,
                )
                self.inventory.increase_stock(item_id, quantity)

                self.audit.log_purchase_created(
                    purchase_id=purchase.id,
                    item_id=item_id,
                    vendor_id=vendor_id,
                    quantity=quantity,
                    total_value=purchase.total_value,
                    user_id=user_id,
                )

                return purchase

        except ValueError as e:
            self.audit.log_purchase_failed(
                item_id=item_id, vendor_id=vendor_id,
                reason=str(e), user_id=user_id,
            )
            raise InvalidPurchaseError(str(e)) from e

        except (ItemNotFoundError, TransactionError) as e:
            self.audit.log_purchase_failed(
                item_id=item_id, vendor_id=vendor_id,
                reason=str(e), user_id=user_id,
            )
            raise

        except Exception as e:
            self.audit.log_purchase_failed(
                item_id=item_id, vendor_id=vendor_id,
                reason=f"unexpected: {type(e).__name__}: {e}",
                user_id=user_id,
            )
            raise

    def _validate(self, quantity: int, price: Decimal) -> None:
        if quantity is None or quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {quantity}")
        if price is None or price < 0:
            raise ValueError(f"Price cannot be negative, got {price}")
