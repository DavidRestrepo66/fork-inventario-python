# 🔧 Implementación Práctica: Re-arquitectura del Sistema de Inventario

## Estructura Propuesta de Archivos

```
transactions/
├── models.py                      # Modelos existentes
├── views.py                       # Refactorizado (ahora delgado)
├── services.py                    # ← NUEVO: Lógica de negocio
├── repositories.py                # ← NUEVO: Acceso a datos
├── domain.py                      # ← NUEVO: Entidades puras
├── exceptions.py                  # ← NUEVO: Excepciones de dominio
├── audit.py                       # ← NUEVO: Auditoría
├── urls.py
├── admin.py
├── tests/
│   ├── __init__.py
│   ├── test_services.py          # ← Tests de servicios
│   ├── test_repositories.py       # ← Tests de repositorios
│   └── test_domain.py             # ← Tests de dominio
└── signals.py
```

---

## 1️⃣ Paso 1: Crear Excepciones Personalizadas

**Archivo**: `transactions/exceptions.py`

```python
"""
Excepciones de dominio para transacciones.
Estas son independientes de Django y expresan errores de negocio.
"""

class TransactionError(Exception):
    """Excepción base para errores de transacciones."""
    pass


class InsufficientStockError(TransactionError):
    """No hay stock suficiente del item."""
    
    def __init__(self, item_id, requested, available):
        self.item_id = item_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"Item {item_id}: requested {requested}, "
            f"but only {available} available"
        )


class ItemNotFoundError(TransactionError):
    """El item solicitado no existe."""
    
    def __init__(self, item_id):
        self.item_id = item_id
        super().__init__(f"Item {item_id} not found")


class InvalidSaleError(TransactionError):
    """Datos de venta inválidos."""
    pass


class UnauthorizedOperationError(TransactionError):
    """Usuario no autorizado para esta operación."""
    pass
```

---

## 2️⃣ Paso 2: Crear Entidades de Dominio

**Archivo**: `transactions/domain.py`

```python
"""
Entidades de dominio puro para transacciones.
Independientes de Django, solo lógica de negocio.
"""

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from typing import List
import uuid


@dataclass(frozen=True)
class Money:
    """Representa dinero de forma segura."""
    amount: Decimal
    currency: str = "USD"
    
    def __post_init__(self):
        if self.amount < 0:
            raise ValueError(f"Money amount cannot be negative: {self.amount}")
    
    def __add__(self, other):
        if not isinstance(other, Money):
            raise TypeError(f"Cannot add Money to {type(other)}")
        return Money(self.amount + other.amount, self.currency)
    
    def __mul__(self, scalar):
        if not isinstance(scalar, (int, float, Decimal)):
            raise TypeError(f"Cannot multiply Money by {type(scalar)}")
        return Money(self.amount * Decimal(str(scalar)), self.currency)


@dataclass(frozen=True)
class PriceSnapshot:
    """
    Captura el precio de un producto en un momento específico.
    Garantiza que la venta histórica nunca cambia aunque el precio actual sí.
    """
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
        if self.quantity > 10000:
            raise ValueError(f"Quantity cannot exceed 10,000, got {self.quantity}")
    
    @property
    def total(self) -> Money:
        """Calcula el total de esta línea."""
        return self.price_snapshot.to_money() * self.quantity
    
    def to_dict(self):
        """Convierte a diccionario para serialización."""
        return {
            'item_id': self.item_id,
            'quantity': self.quantity,
            'price': self.price_snapshot.amount,
            'total': self.total.amount,
        }


@dataclass(frozen=True)
class SaleAggregate:
    """
    Agregado de dominio para una venta completa.
    Garantiza integridad de datos mediante validaciones.
    """
    id: str = None  # UUID de la venta (se asigna al guardar)
    customer_id: int = None
    line_items: List[SaleLineItem] = None
    tax_percentage: Decimal = Decimal("0")
    notes: str = ""
    
    def __post_init__(self):
        # Validaciones de invariantes
        if not self.line_items:
            raise ValueError("Sale must have at least one line item")
        
        if not 0 <= self.tax_percentage <= 100:
            raise ValueError(
                f"Tax percentage must be 0-100, got {self.tax_percentage}"
            )
        
        if not self.customer_id:
            raise ValueError("Customer ID is required")
        
        # Validar cada línea
        for line in self.line_items:
            if line.quantity > 1000:
                raise ValueError(
                    f"Item {line.item_id}: quantity {line.quantity} "
                    f"exceeds limit of 1,000"
                )
    
    @property
    def subtotal(self) -> Money:
        """Suma de todos los items."""
        result = Money(Decimal("0"))
        for line in self.line_items:
            result = result + line.total
        return result
    
    @property
    def tax_amount(self) -> Money:
        """Impuesto calculado."""
        tax = self.subtotal.amount * (self.tax_percentage / 100)
        return Money(tax)
    
    @property
    def grand_total(self) -> Money:
        """Total final a pagar."""
        return self.subtotal + self.tax_amount
    
    def to_dict(self):
        """Serializa la venta para almacenar en BD."""
        return {
            'customer_id': self.customer_id,
            'subtotal': self.subtotal.amount,
            'tax_amount': self.tax_amount.amount,
            'tax_percentage': self.tax_percentage,
            'grand_total': self.grand_total.amount,
            'line_items': [item.to_dict() for item in self.line_items],
            'notes': self.notes,
        }
```

---

## 3️⃣ Paso 3: Crear Repositorios

**Archivo**: `transactions/repositories.py`

```python
"""
Repositorios para desacoplar el acceso a datos.
Si los modelos de Django cambian, solo estos archivos se modifican.
"""

from django.db import transaction as db_transaction
from django.core.exceptions import ObjectDoesNotExist

from store.models import Item
from accounts.models import Customer

from .models import Sale, SaleDetail, Purchase
from .exceptions import (
    ItemNotFoundError,
    InsufficientStockError,
    TransactionError,
)
from .domain import SaleAggregate, PriceSnapshot, Money
from datetime import datetime


class InventoryRepository:
    """
    Abstracción para operaciones de inventario.
    
    Ventaja: Si cambia la forma de almacenar inventario
    (ej: múltiples bodegas), solo este repositorio cambia.
    """
    
    def get_available_stock(self, item_id: int) -> int:
        """Obtiene el stock disponible de un item."""
        try:
            item = Item.objects.get(id=item_id)
            return item.quantity
        except Item.DoesNotExist:
            raise ItemNotFoundError(item_id)
    
    def get_item_price(self, item_id: int) -> Money:
        """Obtiene el precio actual de un item."""
        try:
            item = Item.objects.get(id=item_id)
            return Money(item.cost_price)
        except Item.DoesNotExist:
            raise ItemNotFoundError(item_id)
    
    def check_stock_availability(self, items_needed: dict):
        """
        Verifica que hay stock para una lista de items.
        
        Args:
            items_needed: {'item_id': quantity, ...}
        
        Raises:
            InsufficientStockError: Si no hay stock suficiente
        """
        for item_id, quantity_needed in items_needed.items():
            available = self.get_available_stock(item_id)
            if available < quantity_needed:
                raise InsufficientStockError(
                    item_id, quantity_needed, available
                )
    
    def reduce_stock(self, item_id: int, quantity: int):
        """
        Reduce el stock de un item de forma segura.
        Usa select_for_update() para evitar race conditions.
        """
        try:
            with db_transaction.atomic():
                # Lock el item para evitar race conditions
                item = Item.objects.select_for_update().get(id=item_id)
                
                if item.quantity < quantity:
                    raise InsufficientStockError(
                        item_id, quantity, item.quantity
                    )
                
                item.quantity -= quantity
                item.save(update_fields=['quantity'])
        
        except Item.DoesNotExist:
            raise ItemNotFoundError(item_id)
    
    def reduce_stock_batch(self, reductions: dict):
        """
        Reduce stock de múltiples items de forma atómica.
        
        Args:
            reductions: {'item_id': quantity, ...}
        
        Si falla cualquier reducción, TODAS se revierten.
        """
        with db_transaction.atomic():
            for item_id, quantity in reductions.items():
                self.reduce_stock(item_id, quantity)
    
    def increase_stock(self, item_id: int, quantity: int):
        """Aumenta el stock (para devoluciones, cancelaciones)."""
        try:
            with db_transaction.atomic():
                item = Item.objects.select_for_update().get(id=item_id)
                item.quantity += quantity
                item.save(update_fields=['quantity'])
        except Item.DoesNotExist:
            raise ItemNotFoundError(item_id)


class SaleRepository:
    """Abstracción para operaciones de ventas."""
    
    def create_from_aggregate(self, aggregate: SaleAggregate) -> Sale:
        """
        Crea una venta a partir del agregado de dominio.
        
        Garantiza atomicidad: O todo se crea, o nada.
        """
        data = aggregate.to_dict()
        
        with db_transaction.atomic():
            customer = Customer.objects.get(id=aggregate.customer_id)
            
            sale = Sale.objects.create(
                customer=customer,
                sub_total=data['subtotal'],
                tax_amount=data['tax_amount'],
                tax_percentage=data['tax_percentage'],
                grand_total=data['grand_total'],
                amount_paid=data['grand_total'],  # Asume pago completo
                amount_change=0,
            )
            
            # Crear detalles
            for item_data in data['line_items']:
                SaleDetail.objects.create(
                    sale=sale,
                    item_id=item_data['item_id'],
                    price=item_data['price'],
                    quantity=item_data['quantity'],
                    total_detail=item_data['total'],
                )
            
            return sale
    
    def get_by_id(self, sale_id: int) -> Sale:
        """Obtiene una venta por ID."""
        try:
            return Sale.objects.get(id=sale_id)
        except Sale.DoesNotExist:
            raise TransactionError(f"Sale {sale_id} not found")
    
    def cancel_sale(self, sale_id: int):
        """Marca una venta como cancelada."""
        sale = self.get_by_id(sale_id)
        sale.status = "CANCELLED"  # Asume que existe este campo
        sale.save()
        return sale
    
    def get_sales_by_customer(self, customer_id: int):
        """Obtiene todas las ventas de un cliente."""
        return Sale.objects.filter(customer_id=customer_id)
```

---

## 4️⃣ Paso 4: Crear Servicios de Negocio

**Archivo**: `transactions/services.py`

```python
"""
Servicios de aplicación: Coordinan repositorios y lógica de dominio.
Estos servicios SÍ son testables sin Django.
"""

from decimal import Decimal
from datetime import datetime
from typing import List, Dict

from .domain import SaleAggregate, SaleLineItem, PriceSnapshot, Money
from .repositories import InventoryRepository, SaleRepository
from .exceptions import (
    InsufficientStockError,
    ItemNotFoundError,
    InvalidSaleError,
)
from .audit import AuditLogger


class CreateSaleService:
    """Servicio para crear ventas de forma consistente y auditada."""
    
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
        items: List[Dict],  # [{'item_id': 1, 'qty': 5}, ...]
        tax_percentage: Decimal = Decimal("0"),
        user_id: int = None,
    ):
        """
        Crea una venta de forma atómica y auditada.
        
        Args:
            customer_id: ID del cliente
            items: Lista de items a vender
            tax_percentage: Porcentaje de impuesto (0-100)
            user_id: ID del usuario que crea la venta
        
        Returns:
            Sale: La venta creada
        
        Raises:
            InsufficientStockError: Si no hay stock
            ItemNotFoundError: Si un item no existe
            InvalidSaleError: Si los datos son inválidos
        """
        try:
            # 1. Validar entrada
            self._validate_input(customer_id, items, tax_percentage)
            
            # 2. Construir agregado de dominio
            line_items = self._build_line_items(items)
            aggregate = SaleAggregate(
                customer_id=customer_id,
                line_items=line_items,
                tax_percentage=tax_percentage,
            )
            
            # 3. Verificar disponibilidad de stock
            self._verify_stock(items)
            
            # 4. Crear venta en BD
            sale = self.sales.create_from_aggregate(aggregate)
            
            # 5. Deducir stock
            stock_reductions = {item['item_id']: item['qty'] for item in items}
            self.inventory.reduce_stock_batch(stock_reductions)
            
            # 6. Auditar
            self.audit.log_sale_created(
                sale_id=sale.id,
                customer_id=customer_id,
                total=aggregate.grand_total.amount,
                user_id=user_id,
            )
            
            return sale
        
        except (InsufficientStockError, ItemNotFoundError):
            # Excepciones de negocio esperadas
            self.audit.log_sale_failed(
                customer_id=customer_id,
                reason="Validación de negocio fallida",
                user_id=user_id,
            )
            raise
        
        except Exception as e:
            # Excepciones inesperadas
            self.audit.log_sale_failed(
                customer_id=customer_id,
                reason=f"Error inesperado: {str(e)}",
                user_id=user_id,
            )
            raise InvalidSaleError(f"Error creating sale: {str(e)}")
    
    def _validate_input(self, customer_id, items, tax_percentage):
        """Valida la entrada."""
        if not customer_id or customer_id <= 0:
            raise InvalidSaleError("Invalid customer ID")
        
        if not items:
            raise InvalidSaleError("Sale must have at least one item")
        
        if not 0 <= tax_percentage <= 100:
            raise InvalidSaleError(
                f"Tax must be 0-100%, got {tax_percentage}"
            )
        
        for item in items:
            if 'item_id' not in item or 'qty' not in item:
                raise InvalidSaleError("Each item must have item_id and qty")
            
            if item['qty'] <= 0:
                raise InvalidSaleError("Item quantity must be positive")
    
    def _build_line_items(self, items: List[Dict]) -> List[SaleLineItem]:
        """Construye entidades de línea de venta."""
        line_items = []
        
        for item_data in items:
            # Obtener precio actual (snapshot)
            price = self.inventory.get_item_price(item_data['item_id'])
            
            price_snapshot = PriceSnapshot(
                amount=price.amount,
                captured_at=datetime.now(),
                item_id=item_data['item_id'],
            )
            
            line_item = SaleLineItem(
                item_id=item_data['item_id'],
                quantity=item_data['qty'],
                price_snapshot=price_snapshot,
            )
            
            line_items.append(line_item)
        
        return line_items
    
    def _verify_stock(self, items: List[Dict]):
        """Verifica disponibilidad antes de crear."""
        stock_needed = {item['item_id']: item['qty'] for item in items}
        self.inventory.check_stock_availability(stock_needed)


class CancelSaleService:
    """Servicio para cancelar ventas."""
    
    def __init__(
        self,
        inventory_repo: InventoryRepository,
        sale_repo: SaleRepository,
        audit_logger: AuditLogger,
    ):
        self.inventory = inventory_repo
        self.sales = sale_repo
        self.audit = audit_logger
    
    def execute(self, sale_id: int, user_id: int = None):
        """
        Cancela una venta y revierte el stock.
        
        Args:
            sale_id: ID de la venta a cancelar
            user_id: ID del usuario que cancela
        """
        try:
            # 1. Obtener la venta
            sale = self.sales.get_by_id(sale_id)
            
            # 2. Obtener detalles de la venta
            details = sale.saledetail_set.all()
            
            # 3. Revertir stock
            for detail in details:
                self.inventory.increase_stock(
                    detail.item_id,
                    detail.quantity,
                )
            
            # 4. Marcar como cancelada
            self.sales.cancel_sale(sale_id)
            
            # 5. Auditar
            self.audit.log_sale_cancelled(
                sale_id=sale_id,
                user_id=user_id,
            )
        
        except Exception as e:
            self.audit.log_cancel_failed(
                sale_id=sale_id,
                reason=str(e),
                user_id=user_id,
            )
            raise
```

---

## 5️⃣ Paso 5: Crear Sistema de Auditoría

**Archivo**: `transactions/audit.py`

```python
"""
Sistema de auditoría para registrar todas las operaciones críticas.
"""

import logging
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger(__name__)


class AuditLogger:
    """Registra auditoría de operaciones de transacciones."""
    
    def log_sale_created(self, sale_id: int, customer_id: int, 
                        total: Decimal, user_id: int = None):
        """Registra creación de venta."""
        message = (
            f"SALE_CREATED | sale_id={sale_id} | "
            f"customer_id={customer_id} | total={total} | user_id={user_id} | "
            f"timestamp={datetime.now().isoformat()}"
        )
        logger.info(message)
    
    def log_sale_cancelled(self, sale_id: int, user_id: int = None):
        """Registra cancelación de venta."""
        message = (
            f"SALE_CANCELLED | sale_id={sale_id} | user_id={user_id} | "
            f"timestamp={datetime.now().isoformat()}"
        )
        logger.info(message)
    
    def log_sale_failed(self, customer_id: int, reason: str, 
                       user_id: int = None):
        """Registra intento fallido de venta."""
        message = (
            f"SALE_FAILED | customer_id={customer_id} | reason={reason} | "
            f"user_id={user_id} | timestamp={datetime.now().isoformat()}"
        )
        logger.warning(message)
    
    def log_cancel_failed(self, sale_id: int, reason: str, 
                         user_id: int = None):
        """Registra cancelación fallida."""
        message = (
            f"CANCEL_FAILED | sale_id={sale_id} | reason={reason} | "
            f"user_id={user_id} | timestamp={datetime.now().isoformat()}"
        )
        logger.warning(message)
```

---

## 6️⃣ Paso 6: Refactorizar las Vistas

**Archivo**: `transactions/views.py` (REFACTORIZADO)

```python
# Standard library imports
import json
import logging
from decimal import Decimal

# Django core imports
from django.http import JsonResponse
from django.urls import reverse
from django.shortcuts import render
from django.views.generic import DetailView, ListView
from django.views.generic.edit import CreateView, UpdateView, DeleteView

# Authentication and permissions
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

# Local app imports
from accounts.models import Customer
from .models import Sale, Purchase, SaleDetail
from .forms import PurchaseForm

# Nuevas importaciones: Servicios, Repositorios, etc.
from .services import CreateSaleService, CancelSaleService
from .repositories import InventoryRepository, SaleRepository
from .audit import AuditLogger
from .exceptions import TransactionError, InsufficientStockError


logger = logging.getLogger(__name__)


def is_ajax(request):
    return request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'


def SaleCreateView(request):
    """Vista refactorizada - AHORA MUCHO MÁS DELGADA."""
    context = {
        "active_icon": "sales",
        "customers": [c.to_select2() for c in Customer.objects.all()]
    }

    if request.method == 'POST':
        if is_ajax(request=request):
            try:
                # 1. Parsear JSON
                data = json.loads(request.body)
                
                # 2. Instanciar servicios (inyección de dependencias)
                inventory_repo = InventoryRepository()
                sale_repo = SaleRepository()
                audit_logger = AuditLogger()
                
                create_service = CreateSaleService(
                    inventory_repo,
                    sale_repo,
                    audit_logger,
                )
                
                # 3. Delegar al servicio (¡Solo 1 línea!)
                items = [
                    {'item_id': item['id'], 'qty': item['quantity']}
                    for item in data['items']
                ]
                
                sale = create_service.execute(
                    customer_id=int(data['customer']),
                    items=items,
                    tax_percentage=Decimal(data.get('tax_percentage', 0)),
                    user_id=request.user.id,
                )
                
                # 4. Responder al cliente
                return JsonResponse({
                    'status': 'success',
                    'message': 'Sale created successfully!',
                    'sale_id': sale.id,
                    'redirect': '/transactions/sales/'
                })
            
            except json.JSONDecodeError:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Invalid JSON format!'
                }, status=400)
            
            except InsufficientStockError as e:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Stock error: {str(e)}'
                }, status=400)
            
            except TransactionError as e:
                return JsonResponse({
                    'status': 'error',
                    'message': str(e)
                }, status=400)
            
            except Exception as e:
                logger.error(f"Unexpected error in SaleCreateView: {e}")
                return JsonResponse({
                    'status': 'error',
                    'message': 'Unexpected error!'
                }, status=500)
    
    return render(request, "transactions/sale_create.html", context=context)


class SaleListView(LoginRequiredMixin, ListView):
    """Sin cambios."""
    model = Sale
    template_name = "transactions/sales_list.html"
    context_object_name = "sales"
    paginate_by = 10
    ordering = ['date_added']


class SaleDetailView(LoginRequiredMixin, DetailView):
    """Sin cambios."""
    model = Sale
    template_name = "transactions/saledetail.html"


class SaleDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    """Vista refactorizada - Ahora usa servicio."""
    model = Sale
    template_name = "transactions/saledelete.html"
    
    def delete(self, request, *args, **kwargs):
        """Sobrescribir delete para usar servicio."""
        try:
            sale = self.get_object()
            
            # Usar servicio para cancelar
            inventory_repo = InventoryRepository()
            sale_repo = SaleRepository()
            audit_logger = AuditLogger()
            
            cancel_service = CancelSaleService(
                inventory_repo,
                sale_repo,
                audit_logger,
            )
            
            cancel_service.execute(
                sale_id=sale.id,
                user_id=request.user.id,
            )
            
            return super().delete(request, *args, **kwargs)
        
        except TransactionError as e:
            logger.error(f"Error canceling sale: {e}")
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=400)
    
    def get_success_url(self):
        return reverse("saleslist")
    
    def test_func(self):
        return self.request.user.is_superuser


# Resto de vistas sin cambios...
class PurchaseListView(LoginRequiredMixin, ListView):
    model = Purchase
    template_name = "transactions/purchases_list.html"
    context_object_name = "purchases"
    paginate_by = 10
```

---

## 7️⃣ Paso 7: Tests Unitarios (SIN BD)

**Archivo**: `transactions/tests/test_services.py`

```python
"""
Tests unitarios para servicios.
¡IMPORTANTE: No requieren Django ni BD!
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, MagicMock

from transactions.services import CreateSaleService
from transactions.domain import SaleAggregate, SaleLineItem, PriceSnapshot, Money
from transactions.exceptions import InsufficientStockError, InvalidSaleError
from datetime import datetime


@pytest.fixture
def mocked_repos():
    """Crea repositorios mockeados."""
    inventory_repo = Mock()
    sale_repo = Mock()
    audit_logger = Mock()
    
    return inventory_repo, sale_repo, audit_logger


@pytest.fixture
def service(mocked_repos):
    """Crea servicio con deps mockeados."""
    inventory_repo, sale_repo, audit_logger = mocked_repos
    return CreateSaleService(inventory_repo, sale_repo, audit_logger)


def test_create_sale_success(service, mocked_repos):
    """Test: Crear venta exitosamente."""
    inventory_repo, sale_repo, audit_logger = mocked_repos
    
    # Setup del mock
    inventory_repo.get_item_price.return_value = Money(Decimal("100"))
    inventory_repo.check_stock_availability.return_value = None
    
    mock_sale = Mock()
    mock_sale.id = 1
    sale_repo.create_from_aggregate.return_value = mock_sale
    
    # Ejecutar
    items = [{'item_id': 1, 'qty': 5}]
    sale = service.execute(
        customer_id=1,
        items=items,
        tax_percentage=Decimal("10"),
        user_id=1,
    )
    
    # Aserciones
    assert sale.id == 1
    inventory_repo.reduce_stock_batch.assert_called_once()
    audit_logger.log_sale_created.assert_called_once()


def test_create_sale_insufficient_stock(service, mocked_repos):
    """Test: Falla por stock insuficiente."""
    inventory_repo, sale_repo, audit_logger = mocked_repos
    
    # Setup del mock para simular falta de stock
    inventory_repo.check_stock_availability.side_effect = (
        InsufficientStockError(1, 100, 50)
    )
    
    # Ejecutar y verificar que lanza excepción
    with pytest.raises(InsufficientStockError):
        service.execute(
            customer_id=1,
            items=[{'item_id': 1, 'qty': 100}],
        )
    
    # Auditoría registró el fallo
    audit_logger.log_sale_failed.assert_called_once()


def test_create_sale_invalid_input(service, mocked_repos):
    """Test: Falla por datos inválidos."""
    inventory_repo, sale_repo, audit_logger = mocked_repos
    
    # Test con customer_id inválido
    with pytest.raises(InvalidSaleError):
        service.execute(
            customer_id=0,  # Inválido
            items=[{'item_id': 1, 'qty': 5}],
        )
    
    # Test sin items
    with pytest.raises(InvalidSaleError):
        service.execute(
            customer_id=1,
            items=[],  # Inválido
        )


@pytest.fixture
def test_sale_aggregate():
    """Test: Agregado de dominio."""
    price_snapshot = PriceSnapshot(
        amount=Decimal("100"),
        captured_at=datetime.now(),
        item_id=1,
    )
    
    line_item = SaleLineItem(
        item_id=1,
        quantity=5,
        price_snapshot=price_snapshot,
    )
    
    aggregate = SaleAggregate(
        customer_id=1,
        line_items=[line_item],
        tax_percentage=Decimal("10"),
    )
    
    assert aggregate.subtotal == Money(Decimal("500"))
    assert aggregate.tax_amount == Money(Decimal("50"))
    assert aggregate.grand_total == Money(Decimal("550"))
```

---

## 📋 Checklist de Implementación

### Semana 1: Fundación
- [ ] Crear `exceptions.py`
- [ ] Crear `domain.py`
- [ ] Crear `repositories.py`
- [ ] Tests para repositorios
- [ ] Revisar y ajustar

### Semana 2: Servicios e Integración
- [ ] Crear `services.py`
- [ ] Crear `audit.py`
- [ ] Refactorizar `views.py`
- [ ] Tests para servicios
- [ ] Tests de integración

### Semana 3: Documentación y Deployment
- [ ] Documentar API de servicios
- [ ] Agregar logging completo
- [ ] Dockerfile optimizado
- [ ] CI/CD pipeline
- [ ] Deploy a staging

---

## 🧪 Ejecutar Tests

```bash
# Tests unitarios (sin BD)
pytest transactions/tests/test_services.py -v

# Tests con BD
pytest transactions/tests/ -v

# Cobertura
pytest transactions/tests/ --cov=transactions --cov-report=html
```

---

## ✅ Verificación de Éxito

Después de implementar, deberías poder:

1. ✅ **Crear una venta sin Django**:
```python
# En un script Python puro
from domain import SaleAggregate, SaleLineItem, PriceSnapshot
sale = SaleAggregate(...)  # ¡Funciona sin BD!
```

2. ✅ **Testear servicios sin BD**:
```bash
pytest transactions/tests/test_services.py  # Rápido (~1 segundo)
```

3. ✅ **Agregar API REST sin duplicar código**:
```python
# La misma lógica sirve para web y API
from rest_framework.views import APIView
class SaleAPIView(APIView):
    def post(self, request):
        service = CreateSaleService(...)
        sale = service.execute(...)  # Código compartido
```

---

## 🎯 Próximos Pasos

1. Implementa los 7 pasos anteriores
2. Escribe tests para cada módulo
3. Refactoriza `Purchase` para usar servicios
4. Agrega API REST reutilizando servicios
5. Documenta decisiones arquitectónicas
