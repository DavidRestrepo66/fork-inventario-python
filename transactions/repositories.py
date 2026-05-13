"""
Repositorios: abstracción del acceso a datos.
Los métodos son transaction-agnostic — el servicio decide los límites de atomic().
"""

from decimal import Decimal

from store.models import Item
from accounts.models import Customer, Vendor

from .models import Purchase, Sale, SaleDetail
from .domain import SaleAggregate, Money
from .exceptions import (
    ItemNotFoundError,
    InsufficientStockError,
    TransactionError,
)


class InventoryRepository:
    """Operaciones de inventario sobre Item."""

    def get_available_stock(self, item_id: int) -> int:
        try:
            return Item.objects.get(id=item_id).quantity
        except Item.DoesNotExist:
            raise ItemNotFoundError(item_id)

    def get_item_price(self, item_id: int) -> Money:
        # Item.price es FloatField — convertimos vía str para preservar precisión.
        try:
            item = Item.objects.get(id=item_id)
        except Item.DoesNotExist:
            raise ItemNotFoundError(item_id)
        return Money(Decimal(str(item.price)))

    def check_stock_availability(self, items_needed: dict[int, int]) -> None:
        for item_id, qty_needed in items_needed.items():
            available = self.get_available_stock(item_id)
            if available < qty_needed:
                raise InsufficientStockError(item_id, qty_needed, available)

    def reduce_stock(self, item_id: int, quantity: int) -> None:
        # Requiere estar dentro de transaction.atomic() por select_for_update.
        try:
            item = Item.objects.select_for_update().get(id=item_id)
        except Item.DoesNotExist:
            raise ItemNotFoundError(item_id)
        if item.quantity < quantity:
            raise InsufficientStockError(item_id, quantity, item.quantity)
        item.quantity -= quantity
        item.save(update_fields=['quantity'])

    def reduce_stock_batch(self, reductions: dict[int, int]) -> None:
        for item_id, qty in reductions.items():
            self.reduce_stock(item_id, qty)

    def increase_stock(self, item_id: int, quantity: int) -> None:
        # Requiere estar dentro de transaction.atomic() por select_for_update.
        try:
            item = Item.objects.select_for_update().get(id=item_id)
        except Item.DoesNotExist:
            raise ItemNotFoundError(item_id)
        item.quantity += quantity
        item.save(update_fields=['quantity'])


class SaleRepository:
    """Operaciones sobre Sale / SaleDetail."""

    def create_from_aggregate(self, aggregate: SaleAggregate) -> Sale:
        data = aggregate.to_dict()

        try:
            Customer.objects.get(id=aggregate.customer_id)
        except Customer.DoesNotExist:
            raise TransactionError(
                f"Customer {aggregate.customer_id} not found"
            )

        sale = Sale.objects.create(
            customer_id=aggregate.customer_id,
            sub_total=data['subtotal'],
            tax_amount=data['tax_amount'],
            tax_percentage=data['tax_percentage'],
            grand_total=data['grand_total'],
            amount_paid=data['amount_paid'],
            amount_change=data['amount_change'],
        )

        for line in data['line_items']:
            SaleDetail.objects.create(
                sale=sale,
                item_id=line['item_id'],
                price=line['price'],
                quantity=line['quantity'],
                total_detail=line['total'],
            )

        return sale

    def get_by_id(self, sale_id: int) -> Sale:
        try:
            return Sale.objects.get(id=sale_id)
        except Sale.DoesNotExist:
            raise TransactionError(f"Sale {sale_id} not found")


class PurchaseRepository:
    """Operaciones sobre Purchase."""

    def create(
        self,
        *,
        item_id: int,
        vendor_id: int,
        quantity: int,
        price: Decimal,
        description: str = "",
        delivery_date=None,
        delivery_status: str = "P",
    ) -> Purchase:
        try:
            Item.objects.get(id=item_id)
        except Item.DoesNotExist:
            raise ItemNotFoundError(item_id)

        try:
            Vendor.objects.get(id=vendor_id)
        except Vendor.DoesNotExist:
            raise TransactionError(f"Vendor {vendor_id} not found")

        return Purchase.objects.create(
            item_id=item_id,
            vendor_id=vendor_id,
            quantity=quantity,
            price=price,
            description=description,
            delivery_date=delivery_date,
            delivery_status=delivery_status,
        )
