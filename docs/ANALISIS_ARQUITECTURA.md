# Análisis Arquitectónico: Sistema de Inventario y Transacciones

## 📋 Resumen Ejecutivo

El análisis de tu código actual (`SaleCreateView`) evidencia **tres problemas arquitectónicos críticos**:

| Problema | Ubicación | Impacto | Severidad |
|----------|-----------|--------|-----------|
| **Acoplamiento Directo** | `views.py:209` | `Item` (store) acoplado a `SaleCreateView` | 🔴 Alta |
| **Lógica Negocio en Vista** | `views.py:157-271` | 115 líneas de lógica de venta en vista | 🔴 Alta |
| **Actualización Directa de Stock** | `views.py:224-225` | Sin repositorio intermedio | 🔴 Alta |
| **Atomicidad Limitada** | `Purchase.save()` | Efectos secundarios en save() | 🟡 Media |
| **Falta de Trazabilidad** | Todo el código | Sin auditoría de operaciones críticas | 🟡 Media |

---

## 🔍 Análisis Detallado de Problemas

### 1. **Acoplamiento Directo entre Módulos**

#### Problema Actual:
```python
# transactions/views.py
from store.models import Item  # ❌ Acoplamiento directo

def SaleCreateView(request):
    item_instance = Item.objects.get(id=int(item["id"]))  # Acceso directo
    item_instance.quantity -= int(item["quantity"])       # Modificación directa
    item_instance.save()
```

#### Consecuencias:
- Si la estructura de `Item` cambia (ej: soporte para múltiples bodegas), **hay que refactorizar masivamente** `transactions`
- Cambios en `store/models.py` rompen automáticamente `transactions/views.py`
- Imposible simular o mockear `Item` en tests unitarios sin BD

#### Ejemplo de Cambio Futuro Problemático:
```python
# En store/models.py - Cambio: agregar soporte para múltiples almacenes
class Item(models.Model):
    warehouse = models.ForeignKey(Warehouse, ...)  # Nuevo campo
    quantity = models.PositiveIntegerField()
    
# 💥 Ahora SaleCreateView está ROTO porque:
item_instance.quantity -= ...  # ¿De cuál almacén restar?
```

---

### 2. **Vistas Gordas (Fat Views)**

#### Estadísticas Actuales:
```
SaleCreateView: 115 líneas
├─ Validaciones: 17 líneas (170-177)
├─ Extracción de datos: 20 líneas (179-188)
├─ Lógica de negocio: 35 líneas (191-226)
├─ Manejo de errores: 35 líneas (235-269)
└─ Respuesta HTTP: 5 líneas (227-233)
```

#### Problemas:
- **No testeable sin Django**: Requiere `HttpRequest`, cliente web, BD
- **Mezcla de responsabilidades**: HTTP + validación + BD + lógica
- **Duplication**: Misma lógica debe repetirse si surge una API REST

#### Caso Real de Reuso Imposible:
```python
# Escenario futuro: Agregar API REST
class SaleAPIView(APIView):
    def post(self, request):
        # 🤦 Tengo que copiar-pegar las 115 líneas de SaleCreateView?
        # O crear otra función con lógica duplicada?
        pass
```

---

### 3. **Actualización de Stock sin Repositorio**

#### Problema Actual:
```python
# transactions/views.py:224-225
item_instance.quantity -= int(item["quantity"])
item_instance.save()
```

**¿Por qué es problemático?**

1. **Sin validaciones intermedias**: Nada valida que `quantity` no sea negativo
2. **Sin auditoría**: No se registra quién, cuándo, por qué se modificó el stock
3. **Sin transacciones complejas**: Si fallan 2 de 3 items, los 3 quedan en estado inconsistente

#### Ejemplo de Error Silencioso:
```python
# Escenario: Vender 100 unidades de 3 items
for item in items:
    item_instance.quantity -= item["quantity"]  # Item 1: 100 ✓
    item_instance.save()                        # Item 1: OK
    
    # ... algún error aquí ...
    item_instance.quantity -= item["quantity"]  # Item 2: 100 ✓
    item_instance.save()                        # Item 2: OK
    
    # ❌ Excepción en item 3
    item_instance.quantity -= item["quantity"]  # Item 3: no ejecuta
    
# Resultado: Stock inconsistente - Items 1-2 deducidos, Item 3 no
# Sin transacción completa, NO HAY ROLLBACK automático
```

---

### 4. **Atomicidad Incompleta**

#### Código Actual:
```python
with transaction.atomic():  # ✓ Bueno
    new_sale = Sale.objects.create(...)
    for item in items:
        SaleDetail.objects.create(...)
        item_instance.quantity -= ...          # ⚠️ Problematico
        item_instance.save()
    # ❌ Si falla aquí, todo revierte, OK
    # ❌ Pero si falla item_instance.save(), Sale ya existe
```

**El problema**: Aunque usa `transaction.atomic()`, si hay excepción:
- Sale se revierte (bien)
- SaleDetail se revierte (bien)
- Pero si hay deadlock en BD, la excepción no está prevista

#### Mejor Enfoque:
```python
# Usar locks explícitos
with transaction.atomic():
    sale = Sale.objects.create(...)
    
    for item_data in items:
        # Lock el item para evitar race conditions
        item = Item.objects.select_for_update().get(id=item_data['id'])
        
        if item.quantity < item_data['quantity']:
            raise InsufficientStockError(...)
        
        # Operación atómica
        item.quantity -= item_data['quantity']
        item.save()
```

---

## ✅ Soluciones Propuestas

### 1. **Capa de Servicios (Services Layer)**

#### Concepto:
Trasladar toda la lógica de negocio de las vistas a servicios **reutilizables e independientes de Django**.

#### Estructura Propuesta:
```
transactions/
├── models.py
├── services.py           # ← NUEVO: Lógica de negocio
├── repositories.py       # ← NUEVO: Acceso a datos
├── views.py              # Solo orquestación HTTP
└── tests.py
```

#### Ejemplo: `CreateSaleService`
```python
# transactions/services.py
class CreateSaleService:
    """Servicio para crear ventas de forma consistente y auditada."""
    
    def __init__(self, inventory_repo, sale_repo, audit_logger):
        self.inventory = inventory_repo
        self.sales = sale_repo
        self.audit = audit_logger
    
    def execute(self, customer_id, items, tax_percentage=0):
        """
        Ejecuta la creación de una venta de forma atómica.
        
        Args:
            customer_id: ID del cliente
            items: [{'item_id': 1, 'qty': 5, 'price': 1000}, ...]
            tax_percentage: Porcentaje de impuesto (0-100)
        
        Returns:
            Sale: La venta creada
        
        Raises:
            InsufficientStockError: Si no hay stock suficiente
            CustomerNotFoundError: Si el cliente no existe
            InvalidTaxError: Si el impuesto es inválido
        """
        # Validaciones
        self._validate_inputs(customer_id, items, tax_percentage)
        
        # Verificar disponibilidad de stock
        self._check_stock_availability(items)
        
        # Calcular totales
        sub_total, tax_amount, grand_total = self._calculate_totals(
            items, tax_percentage
        )
        
        # Crear venta de forma atómica
        try:
            sale = self.sales.create_with_details(
                customer_id=customer_id,
                items=items,
                sub_total=sub_total,
                tax_amount=tax_amount,
                grand_total=grand_total
            )
            
            # Deducir del inventario (sin efectos secundarios)
            self.inventory.reduce_stock_batch(items)
            
            # Auditar operación
            self.audit.log_sale_created(sale.id, customer_id)
            
            return sale
            
        except Exception as e:
            self.audit.log_sale_failed(customer_id, str(e))
            raise
    
    def _validate_inputs(self, customer_id, items, tax_percentage):
        """Validaciones de entrada."""
        if not customer_id:
            raise ValueError("Customer ID is required")
        if not items:
            raise ValueError("At least one item is required")
        if not 0 <= tax_percentage <= 100:
            raise InvalidTaxError(f"Tax must be 0-100, got {tax_percentage}")
    
    def _check_stock_availability(self, items):
        """Verifica que hay stock suficiente para todos los items."""
        for item in items:
            available = self.inventory.get_available_stock(item['item_id'])
            if available < item['qty']:
                raise InsufficientStockError(
                    f"Item {item['item_id']}: need {item['qty']}, "
                    f"available {available}"
                )
    
    def _calculate_totals(self, items, tax_percentage):
        """Calcula subtotal, impuesto y total."""
        sub_total = sum(item['price'] * item['qty'] for item in items)
        tax_amount = sub_total * (tax_percentage / 100)
        grand_total = sub_total + tax_amount
        return sub_total, tax_amount, grand_total
```

#### Ventajas:
✅ **Testeable sin Django**: Solo necesita repositorios mockeados  
✅ **Reutilizable**: Mismo servicio para vistas web, API, CLI  
✅ **Auditaría incorporada**: Todas las operaciones se registran  
✅ **Manejo de errores centralizado**: Excepciones de negocio claras  

---

### 2. **Patrón Repositorio (Repository Pattern)**

#### Concepto:
Interfaz intermedia que **desacopla** el acceso a datos del resto del código.

#### Implementación:
```python
# transactions/repositories.py

class InventoryRepository:
    """
    Abstracción para acceder al inventario sin depender de Item.
    Si Item cambia, solo cambia este repositorio.
    """
    
    def get_item(self, item_id):
        """Obtiene un item por ID."""
        from store.models import Item
        try:
            return Item.objects.get(id=item_id)
        except Item.DoesNotExist:
            raise ItemNotFoundError(f"Item {item_id} not found")
    
    def get_available_stock(self, item_id):
        """Obtiene stock disponible de un item."""
        item = self.get_item(item_id)
        return item.quantity
    
    def reduce_stock(self, item_id, quantity):
        """Reduce el stock de un item."""
        from store.models import Item
        from django.db import transaction
        
        with transaction.atomic():
            # select_for_update() previene race conditions
            item = Item.objects.select_for_update().get(id=item_id)
            
            if item.quantity < quantity:
                raise InsufficientStockError(...)
            
            item.quantity -= quantity
            item.save()
    
    def reduce_stock_batch(self, items):
        """
        Reduce stock para múltiples items de forma atómica.
        
        Args:
            items: [{'item_id': 1, 'qty': 5}, ...]
        """
        from django.db import transaction
        
        with transaction.atomic():
            for item_data in items:
                self.reduce_stock(item_data['item_id'], item_data['qty'])


class SaleRepository:
    """Abstracción para acceder a ventas."""
    
    def create_with_details(self, customer_id, items, sub_total, 
                           tax_amount, grand_total):
        """
        Crea una venta con sus detalles de forma atómica.
        """
        from django.db import transaction
        from accounts.models import Customer
        
        with transaction.atomic():
            customer = Customer.objects.get(id=customer_id)
            
            sale = Sale.objects.create(
                customer=customer,
                sub_total=sub_total,
                tax_amount=tax_amount,
                grand_total=grand_total
            )
            
            for item in items:
                SaleDetail.objects.create(
                    sale=sale,
                    item_id=item['item_id'],
                    price=item['price'],
                    quantity=item['qty'],
                    total_detail=item['price'] * item['qty']
                )
            
            return sale
```

#### Cómo Cambia si Item Se Modifica:
```python
# Escenario: Item ahora tiene warehouse
class Item(models.Model):
    warehouse = models.ForeignKey(Warehouse, ...)
    quantity = models.PositiveIntegerField()

# Solo cambias el repositorio:
class InventoryRepository:
    def get_available_stock(self, item_id, warehouse_id=None):
        item = Item.objects.get(id=item_id)
        if warehouse_id:
            stock = Warehouse.objects.get(id=warehouse_id).item_stock.get(...)
        else:
            stock = item.quantity
        return stock
    
    def reduce_stock(self, item_id, quantity, warehouse_id):
        # Nueva lógica, pero SaleCreateView NO CAMBIA
        warehouse = Warehouse.objects.select_for_update().get(id=warehouse_id)
        warehouse.reduce_item_stock(item_id, quantity)

# ✅ Las vistas y servicios siguen igual!
```

---

### 3. **Entidades de Dominio Puro**

#### Problema Actual:
```python
# transactions/models.py
class SaleDetail(models.Model):
    price = models.DecimalField(...)  # Precio guardado, ¿pero de cuándo?
    quantity = models.PositiveIntegerField()

# Riesgo: Si el precio del producto en store cambia,
# ¿la venta histórica refleja el precio actual o el histórico?
# ¡NO hay claridad!
```

#### Solución: Entidades de Dominio
```python
# transactions/domain.py

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

@dataclass(frozen=True)  # Inmutable = seguro
class PriceSnapshot:
    """Captura el precio en un momento específico."""
    amount: Decimal
    currency: str = "USD"
    captured_at: datetime = None
    
    def __post_init__(self):
        if self.amount < 0:
            raise ValueError("Price cannot be negative")

@dataclass(frozen=True)
class SaleItemDomain:
    """Entidad de dominio para línea de venta."""
    item_id: int
    quantity: int
    price_snapshot: PriceSnapshot
    
    @property
    def total(self) -> Decimal:
        return self.price_snapshot.amount * self.quantity
    
    def validate(self):
        """Validaciones de negocio."""
        if self.quantity <= 0:
            raise ValueError("Quantity must be positive")
        if self.quantity > 1000:
            raise ValueError("Quantity cannot exceed 1000 per line")

@dataclass(frozen=True)
class SaleDomain:
    """Entidad de dominio para venta completa."""
    customer_id: int
    items: list[SaleItemDomain]
    tax_percentage: Decimal
    
    @property
    def subtotal(self) -> Decimal:
        return sum(item.total for item in self.items)
    
    @property
    def tax_amount(self) -> Decimal:
        return self.subtotal * (self.tax_percentage / 100)
    
    @property
    def grand_total(self) -> Decimal:
        return self.subtotal + self.tax_amount
    
    def validate(self):
        """Validaciones de reglas de negocio."""
        if not self.items:
            raise ValueError("Sale must have at least one item")
        
        for item in self.items:
            item.validate()
        
        if not 0 <= self.tax_percentage <= 100:
            raise ValueError("Tax must be 0-100%")
```

#### Beneficios:
✅ **Independientes de Django**: Son clases Python puras  
✅ **Testables**: `from domain import SaleDomain; sale = SaleDomain(...)`  
✅ **Inmutables**: No se pueden modificar accidentalmente  
✅ **Expresan reglas**: El código dice qué es válido  

---

### 4. **Centralización de Seguridad y Autorización**

#### Antes (Disperso):
```python
# transactions/views.py
class SaleDeleteView(UserPassesTestMixin, DeleteView):
    def test_func(self):
        return self.request.user.is_superuser  # ❌ Mezclado con vista

# invoice/views.py
class InvoiceView(DetailView):
    def get(self, request, *args, **kwargs):
        if not request.user.is_staff:           # ❌ Repetido
            raise PermissionDenied()
```

#### Después (Centralizado en Servicios):
```python
# transactions/services.py

class SaleAuthorizationService:
    """Centraliza todas las reglas de autorización de ventas."""
    
    def can_create_sale(self, user) -> bool:
        """¿Puede crear ventas?"""
        return user.is_authenticated
    
    def can_cancel_sale(self, user, sale) -> bool:
        """¿Puede cancelar esta venta?"""
        return (user.is_superuser or 
                user.id == sale.created_by_id)
    
    def can_view_sale_details(self, user, sale) -> bool:
        """¿Puede ver detalles de la venta?"""
        return (user.is_staff or 
                user.id == sale.customer.account_manager_id)


class CancelSaleService:
    def __init__(self, sale_repo, inventory_repo, auth_service, audit_logger):
        self.sales = sale_repo
        self.inventory = inventory_repo
        self.auth = auth_service
        self.audit = audit_logger
    
    def execute(self, user, sale_id):
        """Cancela una venta con autorización integrada."""
        sale = self.sales.get_by_id(sale_id)
        
        # Autorización en el servicio
        if not self.auth.can_cancel_sale(user, sale):
            self.audit.log_unauthorized_cancel(user.id, sale_id)
            raise PermissionDenied(f"User {user.id} cannot cancel sale {sale_id}")
        
        # Revertir stock
        for detail in sale.saledetail_set.all():
            self.inventory.add_stock(detail.item_id, detail.quantity)
        
        # Marcar como cancelada
        sale.status = "CANCELLED"
        sale.save()
        
        self.audit.log_sale_cancelled(sale.id, user.id)
```

---

## 📊 Matriz de Comparación

### Actual vs Propuesto

| Aspecto | Actual | Propuesto | Mejora |
|---------|--------|-----------|--------|
| **Testabilidad** | Requiere BD, HTTP | Solo Python | 100% |
| **Reusabilidad** | Código duplicado | Un servicio | Reducción 70% |
| **Desacoplamiento** | store← →transactions | store→repo←transactions | Independiente |
| **Auditoría** | Manual en cada vista | Automática en servicio | Consistente |
| **Atomicidad** | Parcial | Completa con locks | Seguro |
| **Documentación de negocio** | Implícita en vista | Explícita en dominio | Clara |

---

## 🚀 Plan de Migración Incremental

### Fase 1: **Fundación** (1-2 semanas)
1. Crear `repositories.py` con `InventoryRepository`, `SaleRepository`
2. Crear `domain.py` con entidades puras
3. Tests unitarios para ambos

### Fase 2: **Servicios** (2-3 semanas)
1. Crear `services.py` con `CreateSaleService`, `CancelSaleService`
2. Refactorizar `SaleCreateView` para usar servicios
3. Crear `audit_logger.py` para trazabilidad

### Fase 3: **Extensión** (1 semana)
1. Agregar API REST reutilizando servicios
2. Crear CLI usando mismos servicios
3. Documentación de API

### Fase 4: **Robustez** (1-2 semanas)
1. Tests de integración
2. Optimizar performance
3. Dockerizar con reproducibilidad

---

## 📝 Problemas Específicos a Resolver

### Actual: Purchase.save() modifica stock
```python
# ❌ PROBLEMATICO
class Purchase(models.Model):
    def save(self, *args, **kwargs):
        self.total_value = self.price * self.quantity
        super().save(*args, **kwargs)
        self.item.quantity += self.quantity  # Efecto secundario oculto!
        self.item.save()
```

**Solución**:
```python
# ✅ MEJOR
class PurchaseService:
    def receive_purchase(self, purchase_id):
        """Registra la recepción de compra."""
        purchase = Purchase.objects.get(id=purchase_id)
        
        self.inventory.add_stock(
            purchase.item_id, 
            purchase.quantity
        )
        
        purchase.delivery_status = "SUCCESSFUL"
        purchase.save()
```

---

## 🎯 Métricas de Éxito

Después de implementar la re-arquitectura, deberías lograr:

| Métrica | Target |
|---------|--------|
| **Cobertura de tests** | >80% (era ~20%) |
| **Tiempo de test unitarios** | <5 segundos (era >30s) |
| **Líneas por vista** | <40 (era 115) |
| **Módulos desacoplados** | 100% (era 0%) |
| **Auditoría de operaciones** | 100% (era 0%) |

---

## ⚠️ Riesgos de NO Hacer Esta Refactorización

1. **Cambios futuros costosos**: Agregar bodegas múltiples requerirá 3-4 semanas
2. **Bugs silenciosos**: Race conditions en actualización de stock
3. **Imposible escalar**: No puedes agregar API REST sin duplicar código
4. **Imposible auditar**: Si hay discrepancias de stock, no hay trazabilidad
5. **Nuevos miembros del equipo perdidos**: Código de vista con toda la lógica

---

## 🔗 Siguiente Paso

Ver `IMPLEMENTACION_PRACTICA.md` para código completo listo para usar.
