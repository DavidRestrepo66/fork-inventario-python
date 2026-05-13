# Documentación del Sistema de Inventario y Ventas

> Doc generado tras la re-arquitectura de la app `transactions/`. Cubre el repo completo en formato reseña, con tratamiento a fondo del módulo refactorizado.

## Tabla de contenido

1. [Visión general](#1-visión-general)
2. [Stack y configuración](#2-stack-y-configuración)
3. [Mapa de apps y dependencias](#3-mapa-de-apps-y-dependencias)
4. [Documentación por app (reseña)](#4-documentación-por-app-reseña)
   - 4.1 [InventoryMS — configuración del proyecto](#41-inventoryms--configuración-del-proyecto)
   - 4.2 [accounts — usuarios, clientes, vendors](#42-accounts--usuarios-clientes-vendors)
   - 4.3 [store — catálogo y entregas](#43-store--catálogo-y-entregas)
   - 4.4 [transactions — ventas y compras](#44-transactions--ventas-y-compras)
   - 4.5 [bills — facturas internas](#45-bills--facturas-internas)
   - 4.6 [invoice — recibos de cliente](#46-invoice--recibos-de-cliente)
5. [Re-arquitectura de `transactions/` (foco principal)](#5-re-arquitectura-de-transactions-foco-principal)
   - 5.1 [Problemas detectados en el código original](#51-problemas-detectados-en-el-código-original)
   - 5.2 [Capas introducidas y responsabilidades](#52-capas-introducidas-y-responsabilidades)
   - 5.3 [Comparación antes / después](#53-comparación-antes--después)
   - 5.4 [Patrones aplicados](#54-patrones-aplicados)
   - 5.5 [Decisiones arquitectónicas documentadas](#55-decisiones-arquitectónicas-documentadas)
6. [Tests](#6-tests)
7. [Pendientes y bugs detectados durante la documentación](#7-pendientes-y-bugs-detectados-durante-la-documentación)

---

## 1. Visión general

Sistema de gestión de inventario, ventas y compras con autenticación de usuarios. Aplicación web Django monolítica con varias apps internas que comparten una BD SQLite (por defecto). Frontend renderizado server-side con templates Django + Bootstrap 5; flujo de creación de ventas usa AJAX para selección dinámica de items y clientes.

**Casos de uso principales:**
- Registrar/listar/editar **items** (productos) y **categorías**.
- Crear **ventas** (Sale) que descuentan stock automáticamente.
- Registrar **compras** (Purchase) a vendors que aumentan stock.
- Llevar **facturas** (Bill) y **recibos** (Invoice).
- Gestionar **clientes** (Customer), **vendors** y **perfiles de personal** (Profile).
- Exportar ventas y compras a Excel.
- Dashboard con estadísticas y gráficos.

---

## 2. Stack y configuración

| Componente | Versión / valor |
|---|---|
| Python | 3.14 (probado) |
| Django | 5.1 |
| BD | SQLite por defecto (`db.sqlite3`), configurable vía `DATABASES` |
| Frontend | Bootstrap 5 vía `crispy-bootstrap5`, templates Django |
| Tablas | `django-tables2` |
| Filtros | `django-filter` |
| Slugs automáticos | `django-extensions`, `django-autoslug` |
| Imágenes | `django-imagekit` (perfil de usuario) |
| Teléfonos | `django-phonenumber-field` |
| Exportación | `openpyxl` (xlsx), `tablib` |

**Apps instaladas** (`InventoryMS/settings.py:22-43`): `store`, `accounts`, `transactions`, `invoice`, `bills` + dependencias de terceros.

**Configuración relevante:**
- `LOGIN_URL = 'user-login'`, `LOGIN_REDIRECT_URL = 'dashboard'`
- `DEBUG = True` (⚠️ valor de desarrollo; cambiar en producción)
- `SECRET_KEY` hardcoded en `settings.py:12` (⚠️ mover a variable de entorno antes de producción)
- `MEDIA_ROOT = static/images/`, `STATIC_URL = 'static/'`
- `USE_TZ = True` — todos los datetimes deben ser timezone-aware

---

## 3. Mapa de apps y dependencias

```
                    ┌─────────────┐
                    │ InventoryMS │  ← config (settings, urls raíz, wsgi/asgi)
                    └──────┬──────┘
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
       ▼                   ▼                   ▼
  ┌──────────┐       ┌──────────┐        ┌──────────┐
  │ accounts │       │  store   │        │   bills  │
  │ Profile  │       │ Category │        │   Bill   │
  │ Customer │◄──┐   │   Item   │        └──────────┘
  │  Vendor  │   │   │ Delivery │
  └────┬─────┘   │   └────┬─────┘
       │         │        │
       │         │        │  Item (FK)
       │         │        ▼
       │         │   ┌──────────┐
       │         │   │ invoice  │
       │         │   │ Invoice  │
       │         │   └──────────┘
       │         │
       │         │   transactions ──► usa Customer (accounts) y Item (store)
       │         └──────────────────┐
       ▼                            │
  ┌─────────────────────────────────┴─┐
  │         transactions              │
  │  ┌─────────────────────────────┐  │
  │  │  Sale, SaleDetail, Purchase │  │  ← modelos
  │  │  domain (Aggregate, Money)  │  │  ← capa de dominio (nueva)
  │  │  repositories               │  │  ← acceso a datos (nueva)
  │  │  services                   │  │  ← orquestación (nueva)
  │  │  audit                      │  │  ← auditoría (nueva)
  │  │  exceptions                 │  │  ← errores de dominio (nueva)
  │  │  views                      │  │  ← HTTP (refactorizada)
  │  └─────────────────────────────┘  │
  └───────────────────────────────────┘
```

**Cardinalidad de dependencias entre apps** (qué importa qué):

| App | Importa de |
|---|---|
| `InventoryMS` | (nada — solo router) |
| `accounts` | (autónomo) |
| `store` | `accounts.models.Profile, Vendor`, `transactions.models.Sale` (en dashboard) |
| `transactions` | `accounts.models.Customer, Vendor`, `store.models.Item` |
| `invoice` | `store.models.Item` |
| `bills` | `accounts.models.Profile` |

---

## 4. Documentación por app (reseña)

### 4.1 InventoryMS — configuración del proyecto

Carpeta de configuración Django estándar.

| Archivo | Contenido |
|---|---|
| `settings.py` | Configuración global. SQLite, Crispy Bootstrap 5, `USE_TZ=True`. |
| `urls.py` | Router raíz. Monta `store.urls` en `/`, `transactions.urls` en `/transactions/`, etc. |
| `wsgi.py` / `asgi.py` | Entry points para servidor de aplicaciones. |

**URLs raíz:**
```python
path('admin/', admin.site.urls),
path('', include('store.urls')),
path('staff/', include('accounts.urls')),
path('transactions/', include('transactions.urls')),
path('accounts/', include('accounts.urls')),   # ⚠️ duplicado, ver §7
path('invoice/', include('invoice.urls')),
path('bills/', include('bills.urls')),
```

---

### 4.2 accounts — usuarios, clientes, vendors

**Propósito:** autenticación, gestión de personal (perfiles vinculados al `User` de Django), clientes y vendors.

**Modelos** (`accounts/models.py`):

| Modelo | Campos clave | Notas |
|---|---|---|
| `Profile` | `user` (1-1 con `User`), `slug`, `profile_picture`, `telephone`, `email`, `first_name`, `last_name`, `status` (INA/A/OL), `role` (OP/EX/AD) | Extensión del User estándar. |
| `Vendor` | `name`, `slug`, `phone_number`, `address` | Usado por `store.Item` y `transactions.Purchase`. |
| `Customer` | `first_name`, `last_name`, `address`, `email`, `phone`, `loyalty_points` | Tiene `to_select2()` para AJAX dropdowns. |

**Views** (`accounts/views.py`):

| Tipo | Views |
|---|---|
| Auth | `register` (FBV), Django auth views (`LoginView`, `LogoutView` vía templates) |
| Profile | `profile`, `profile_update`, `ProfileListView`, `ProfileCreateView`, `ProfileUpdateView`, `ProfileDeleteView` |
| Customer | `CustomerListView`, `CustomerCreateView`, `CustomerUpdateView`, `CustomerDeleteView`, `get_customers` (AJAX) |
| Vendor | `VendorListView`, `VendorCreateView`, `VendorUpdateView`, `VendorDeleteView` |

**Forms** (`accounts/forms.py`): `CreateUserForm`, `UserUpdateForm`, `ProfileUpdateForm`, `CustomerForm`, `VendorForm`. Todos con widgets Bootstrap.

**URLs principales** (`accounts/urls.py`):
- Auth: `/register/`, `/login/`, `/profile/`, `/profile/update/`, `/logout/`
- Profile: `/profiles/`, `/new-profile/`, `/profile/<pk>/update/`, `/profile/<pk>/delete/`
- Customer: `/customers/`, `/customers/create/`, `/customers/<pk>/update/`, `/customers/<pk>/delete/`, `/get_customers/`
- Vendor: `/vendors/`, `/vendors/new/`, etc.

⚠️ **Bug detectado**: `get_customers` filtra por `Customer.name`, pero el modelo tiene `first_name` / `last_name` (no `name`). Ese endpoint AJAX no devuelve resultados. Ver §7.

---

### 4.3 store — catálogo y entregas

**Propósito:** catálogo de productos, categorías y entregas a clientes.

**Modelos** (`store/models.py`):

| Modelo | Campos clave |
|---|---|
| `Category` | `name`, `slug` |
| `Item` | `slug`, `name`, `description`, `category` (FK), `quantity` (Integer), `price` (Float), `expiring_date`, `vendor` (FK) |
| `Delivery` | `item` (FK), `customer_name`, `phone_number`, `location`, `date`, `is_delivered` |

⚠️ `Item.price` es `FloatField` (no `DecimalField`). El motivo de la conversión `Decimal(str(item.price))` en `transactions/repositories.py:get_item_price` es preservar precisión al construir `Money`.

⚠️ `Item.quantity` es `IntegerField` (no `PositiveIntegerField`). Permite cantidades negativas en BD.

**Views** (`store/views.py`):

| Categoría | Views |
|---|---|
| Dashboard | `dashboard` (FBV, agrega stats: items, ventas, gráficos) |
| Product | `ProductListView`, `ItemSearchListView`, `ProductDetailView`, `ProductCreateView`, `ProductUpdateView`, `ProductDeleteView` |
| Delivery | `DeliveryListView`, `DeliverySearchListView`, `DeliveryDetailView`, `DeliveryCreateView`, `DeliveryUpdateView`, `DeliveryDeleteView` |
| Category | `CategoryListView`, `CategoryDetailView`, `CategoryCreateView`, `CategoryUpdateView`, `CategoryDeleteView` |
| AJAX | `get_items_ajax_view` (búsqueda por término) |

**Forms** (`store/forms.py`): `ItemForm`, `CategoryForm`, `DeliveryForm`.

**URLs principales** (`store/urls.py`):
- `/` (dashboard)
- `/products/`, `/product/<slug>/`, `/new-product/`, `/product/<slug>/update/`, `/product/<slug>/delete/`
- `/search/`
- `/deliveries/`, `/delivery/<slug>/`, etc.
- `/categories/`, `/categories/<pk>/`, etc.
- `/get-items/` (AJAX)

---

### 4.4 transactions — ventas y compras

**Propósito:** registrar ventas (`Sale`) que descuentan stock atómicamente, y compras (`Purchase`) que lo aumentan. Es la app refactorizada — la **§5** documenta la arquitectura nueva en profundidad.

**Modelos** (`transactions/models.py`):

| Modelo | Campos clave |
|---|---|
| `Sale` | `date_added`, `customer` (FK), `sub_total`, `grand_total`, `tax_amount`, `tax_percentage`, `amount_paid`, `amount_change` (todos Decimal salvo `tax_percentage` Float) |
| `SaleDetail` | `sale` (FK con related_name `saledetail_set`), `item` (FK), `price` (Decimal), `quantity` (PositiveInteger), `total_detail` (Decimal) |
| `Purchase` | `slug`, `item` (FK), `description`, `vendor` (FK), `order_date`, `delivery_date`, `quantity`, `delivery_status` (P/S), `price`, `total_value` |

**Archivos** (la lista marca los **nuevos** que introdujo la re-arquitectura):

```
transactions/
├── models.py             # Sale, SaleDetail, Purchase
├── admin.py
├── apps.py
├── filters.py
├── forms.py              # PurchaseForm
├── signals.py            # post_save de Purchase (⚠️ bug, ver §7)
├── tables.py
├── urls.py
├── views.py              # refactorizada (§5)
├── exceptions.py         # ← nuevo
├── domain.py             # ← nuevo
├── repositories.py       # ← nuevo
├── services.py           # ← nuevo
├── audit.py              # ← nuevo
└── tests/
    ├── __init__.py
    ├── test_domain.py    # ← nuevo (28 tests)
    └── test_services.py  # ← nuevo (9 tests)
```

**Views** (`transactions/views.py`):

| View | Responsabilidad |
|---|---|
| `SaleListView` | Listar ventas (paginada). |
| `SaleDetailView` | Detalle de una venta. |
| `SaleCreateView` (FBV) | **Refactorizada** — delega a `CreateSaleService`. |
| `SaleDeleteView` | Hard delete. ⚠️ No restaura stock — ver §7. |
| `PurchaseListView/DetailView/CreateView/UpdateView/DeleteView` | CRUD de compras. |
| `export_sales_to_excel` | Genera xlsx. |
| `export_purchases_to_excel` | Genera xlsx. |

**URLs** (`transactions/urls.py`):
- Ventas: `sales/`, `sale/<pk>/`, `new-sale/`, `sale/<slug>/delete/`
- Compras: `purchases/`, `purchase/<slug>/`, `new-purchase/`, `purchase/<pk>/update/`, `purchase/<pk>/delete/`
- Export: `sales/export/`, `purchases/export/`

---

### 4.5 bills — facturas internas

**Propósito:** registrar facturas que la empresa **recibe** (facturas a pagar a instituciones externas).

**Modelo** (`bills/models.py`):

| Modelo | Campos clave |
|---|---|
| `Bill` | `slug`, `date`, `institution_name`, `phone_number`, `email`, `address`, `description`, `payment_details`, `amount` (Float), `status` (Bool — pagado/no pagado) |

**Views** (`bills/views.py`): `BillListView` (con export), `BillCreateView`, `BillUpdateView`, `BillDeleteView`. Todas con `LoginRequiredMixin`; update y delete con `UserPassesTestMixin`.

**URLs**: `bills/`, `new-bill/`, `bill/<slug>/update/`, `bill/<pk>/delete/`.

App pequeña y autocontenida (sin lógica de stock).

---

### 4.6 invoice — recibos de cliente

**Propósito:** emitir recibos por items vendidos directamente (paralelo conceptual a `Sale`, pero más simple — registra una sola línea por recibo en vez de un detalle multi-item).

**Modelo** (`invoice/models.py`):

| Modelo | Campos clave |
|---|---|
| `Invoice` | `slug`, `date`, `customer_name`, `contact_number`, `item` (FK a `store.Item`), `price_per_item` (Float), `quantity` (Float), `shipping`, `total` (computado en `save()`), `grand_total` (computado en `save()`) |

`Invoice.save()` recalcula `total` y `grand_total` antes de persistir.

**Views**: CRUD estándar (`InvoiceListView`, `InvoiceDetailView`, `InvoiceCreateView`, `InvoiceUpdateView`, `InvoiceDeleteView`).

⚠️ **No descuenta stock** al crear un Invoice — esto es por diseño (el `Invoice` parece ser solo "imprimible") pero podría sorprender a un lector.

---

## 5. Re-arquitectura de `transactions/` (foco principal)

### 5.1 Problemas detectados en el código original

El `SaleCreateView` original (115 líneas) acumulaba responsabilidades. Análisis específico:

**Lista de problemas** (sobre el código pre-refactor, recuperable con `git show HEAD~N:transactions/views.py`):

| # | Problema | Línea (original) |
|---|---|---|
| 1 | **SRP violado**: la vista parsea HTTP, valida, hace queries ORM, escribe BD, calcula totales y maneja 6 tipos de excepción | 157–271 |
| 2 | **`Sale.objects.create()` y `SaleDetail.objects.create()` fuera de chequeo de stock por item** — el orden hace el `atomic()` correcto, pero el bucle de items es frágil | 191–225 |
| 3 | **`item.quantity -= int(...)` sin `select_for_update`** — race condition bajo concurrencia: dos ventas simultáneas del mismo producto pueden ambas pasar la verificación y dejar `quantity` negativo | 224 |
| 4 | **Atomicidad cubre venta+detalle+stock**, pero no hay auditoría: si algo falla, no queda traza estructurada del intento | (toda la función) |
| 5 | **Confianza ciega en totales del cliente**: el frontend envía `sub_total`, `grand_total`, `tax_amount`, `amount_change` y la vista los guarda tal cual. Cliente malicioso puede manipular precios | 181–188 |
| 6 | **Excepciones específicas de ORM filtradas al borde HTTP**: `Customer.DoesNotExist`, `Item.DoesNotExist`. La capa de transporte conoce detalles de la BD | 241–250 |
| 7 | **`except Exception as e`** con mensaje crudo de error: leak de detalles internos al cliente | 261–269 |
| 8 | **Imposible de testear sin BD**: toda la lógica de negocio vive entre llamadas a `Customer.objects`, `Item.objects`, `Sale.objects` | (toda la función) |
| 9 | **Sin reutilización**: si mañana queremos una API REST para crear ventas, hay que duplicar ~100 líneas | (toda la función) |

---

### 5.2 Capas introducidas y responsabilidades

La re-arquitectura divide la app en **5 capas** con dependencias unidireccionales (cada capa solo conoce las que tiene debajo):

```
┌─────────────────────────────────────────────────────────┐
│   View (HTTP)                  ← transactions/views.py  │
│   - Parsea JSON                                         │
│   - Mapea payload → kwargs del servicio                 │
│   - Traduce excepciones de dominio a JsonResponse       │
└────────────────────────────┬────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────┐
│   Service (orquestación)    ← transactions/services.py  │
│   - Define los límites de transaction.atomic()          │
│   - Compone repos + dominio + audit                     │
│   - Traduce ValueError (dominio) → InvalidSaleError     │
└────────┬─────────────────────┬──────────────────────────┘
         ▼                     ▼
┌──────────────────┐  ┌──────────────────────────────────┐
│ Domain (puro)    │  │ Repositories (acceso a datos)    │
│ ← domain.py      │  │ ← repositories.py                │
│ - Aggregate      │  │ - Traducen ORM exceptions →      │
│ - Value objects  │  │   exceptions de dominio          │
│ - Invariantes    │  │ - Usan select_for_update         │
│                  │  │ - SON transaction-agnostic       │
└────────┬─────────┘  └────────┬─────────────────────────┘
         │                     │
         ▼                     ▼
┌─────────────────┐  ┌──────────────────────────────────┐
│ Exceptions      │  │ Audit (efectos colaterales)      │
│ ← exceptions.py │  │ ← audit.py                       │
│ - Errores de    │  │ - log_sale_created               │
│   dominio       │  │ - log_sale_failed                │
│ - Sin Django    │  │ - Sin Django                     │
└─────────────────┘  └──────────────────────────────────┘
```

**Tabla de responsabilidades por archivo:**

| Archivo | Responsabilidad | Depende de Django |
|---|---|---|
| `exceptions.py` | Jerarquía de errores de negocio (`TransactionError` raíz). | No |
| `domain.py` | Entidades inmutables (`Money`, `PriceSnapshot`, `SaleLineItem`, `SaleAggregate`) con invariantes. | No |
| `repositories.py` | Operaciones sobre `Item`, `Sale`, `SaleDetail`, `Customer`. Traducen `*.DoesNotExist` → excepciones de dominio. | Sí (ORM) |
| `services.py` | `CreateSaleService.execute()` — único punto donde se abre `transaction.atomic()`. | Sí (transaction) |
| `audit.py` | `AuditLogger` — escribe logs estructurados. | No |
| `views.py` | Solo HTTP. Instancia repos+service por request. | Sí |

---

### 5.3 Comparación antes / después

#### El cambio principal: `SaleCreateView`

**ANTES** (115 líneas, extracto):

```python
def SaleCreateView(request):
    context = {"active_icon": "sales",
               "customers": [c.to_select2() for c in Customer.objects.all()]}

    if request.method == 'POST':
        if is_ajax(request=request):
            try:
                data = json.loads(request.body)
                # 10 líneas validando required_fields...
                sale_attributes = {
                    "customer": Customer.objects.get(id=int(data['customer'])),
                    "sub_total": float(data["sub_total"]),     # ⚠️ del cliente
                    "grand_total": float(data["grand_total"]),  # ⚠️ del cliente
                    # ...
                }
                with transaction.atomic():
                    new_sale = Sale.objects.create(**sale_attributes)
                    items = data["items"]
                    if not isinstance(items, list):
                        raise ValueError("Items should be a list")
                    for item in items:
                        # 20 líneas: validar item, fetch Item, check stock,
                        # crear SaleDetail, decrementar item.quantity
                        item_instance = Item.objects.get(id=int(item["id"]))
                        if item_instance.quantity < int(item["quantity"]):
                            raise ValueError(f"Not enough stock for item: ...")
                        SaleDetail.objects.create(...)
                        item_instance.quantity -= int(item["quantity"])
                        item_instance.save()
                return JsonResponse({'status': 'success', ...})
            except json.JSONDecodeError: ...     # 6 except blocks
            except Customer.DoesNotExist: ...
            except Item.DoesNotExist: ...
            except ValueError as ve: ...
            except TypeError as te: ...
            except Exception as e:
                logger.error(f"Exception during sale creation: {e}")
                return JsonResponse({'message': f'... {str(e)}'}, status=500)

    return render(request, "transactions/sale_create.html", context=context)
```

**DESPUÉS** (~75 líneas):

```python
@login_required
def SaleCreateView(request):
    context = {"active_icon": "sales",
               "customers": [c.to_select2() for c in Customer.objects.all()]}

    if request.method != 'POST' or not is_ajax(request=request):
        return render(request, "transactions/sale_create.html", context=context)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error',
                             'message': 'Invalid JSON format in request body'},
                            status=400)

    try:
        customer_id = int(data['customer'])
        tax_percentage = Decimal(str(data.get('tax_percentage', 0)))
        amount_paid = Decimal(str(data['amount_paid']))
        items = [{'item_id': int(it['id']), 'qty': int(it['quantity'])}
                 for it in data['items']]
    except (KeyError, ValueError, TypeError, InvalidOperation) as e:
        return JsonResponse({'status': 'error',
                             'message': f'Invalid request data: {e}'},
                            status=400)

    service = CreateSaleService(
        InventoryRepository(), SaleRepository(), AuditLogger(),
    )

    try:
        sale = service.execute(
            customer_id=customer_id, items=items,
            tax_percentage=tax_percentage, amount_paid=amount_paid,
            user_id=request.user.id,
        )
    except InsufficientStockError as e:
        return JsonResponse({
            'status': 'error', 'message': str(e),
            'item_id': e.item_id, 'requested': e.requested,
            'available': e.available,
        }, status=400)
    except TransactionError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    except Exception:
        logger.exception('Unexpected error in SaleCreateView')
        return JsonResponse({'status': 'error',
                             'message': 'Unexpected error'}, status=500)

    return JsonResponse({'status': 'success', 'sale_id': sale.id,
                         'redirect': '/transactions/sales/'})
```

#### Tabla: qué se movió a dónde

| Responsabilidad original (en `views.py`) | Ahora vive en |
|---|---|
| Validar `required_fields` | `services.CreateSaleService._validate_input_shape` (forma) + `domain.SaleAggregate.__post_init__` (semántica) |
| Calcular `sub_total`, `tax_amount`, `grand_total` | `domain.SaleAggregate.{subtotal, tax_amount, grand_total}` (properties, derivadas) |
| `Customer.objects.get` | `repositories.SaleRepository.create_from_aggregate` |
| `Item.objects.get` por cada item | `repositories.InventoryRepository.get_item_price` (también `get_available_stock`) |
| Verificar stock (`if item_instance.quantity < ...`) | `repositories.InventoryRepository.check_stock_availability` (fail-fast) + `reduce_stock` con `select_for_update` (lock real) |
| `transaction.atomic()` | `services.CreateSaleService.execute` — único punto |
| `Sale.objects.create` + `SaleDetail.objects.create` en bucle | `repositories.SaleRepository.create_from_aggregate` |
| `item.quantity -= ...; item.save()` | `repositories.InventoryRepository.reduce_stock_batch` |
| Translación de excepciones ORM | Repos: `Item.DoesNotExist → ItemNotFoundError`, `Customer.DoesNotExist → TransactionError(...)` |
| Logging de creación / fallo | `audit.AuditLogger.{log_sale_created, log_sale_failed}` |
| Confianza ciega en totales del cliente | **Eliminada**: el servidor recomputa todo desde `items` + `tax_percentage` |

#### Cambios concretos en el modelo de seguridad

| Antes | Después |
|---|---|
| Cliente decide `sub_total`, `grand_total`, `tax_amount`, `amount_change`. Servidor los persiste tal cual. | Cliente solo decide `items` (con `id`, `quantity`), `tax_percentage`, `amount_paid`. Servidor recomputa todos los totales desde el snapshot de `Item.price` del momento. |
| `item.quantity -= N` sin lock — race condition. | `select_for_update().get(id=...)` dentro de `atomic()` — lock pesimista. |
| Mensaje de error filtra `str(e)` interno. | Excepciones de dominio mapean a mensajes controlados; `except Exception` retorna `"Unexpected error"` genérico. |
| Sin `@login_required` (función). | `@login_required` aplicado. |

---

### 5.4 Patrones aplicados

**1. Domain Aggregate (DDD)**

`SaleAggregate` es la "raíz de agregado": cualquier modificación de una venta y sus líneas pasa por él. Es `frozen=True` (inmutable) y valida invariantes en `__post_init__`:

- Al menos una línea.
- `0 ≤ tax_percentage ≤ 100`.
- `customer_id` requerido.
- `amount_paid is not None`.
- `amount_paid ≥ grand_total` (no se permite subpago).

Para representar "la venta tras persistirse" sin romper la inmutabilidad, se usa el patrón `dataclasses.replace(agg, id=new_id)`: produce una nueva instancia con el `id` asignado. Esto modela explícitamente el ciclo de vida: agregado in-flight (`id=None`) → agregado persistido (`id` poblado).

**2. Value Object**

`Money` es un value object: inmutable, igualdad por valor, opera consigo mismo (`+`, `*`), valida invariantes (no negativo) y se rehúsa a operar con divisas distintas:

```python
Money(Decimal("1"), "USD") + Money(Decimal("1"), "EUR")
# TypeError: Cannot add Money with different currencies: USD and EUR
```

`PriceSnapshot` captura el precio + timestamp + item para que la venta histórica nunca cambie aunque el precio del catálogo cambie después.

**3. Repository**

`InventoryRepository` y `SaleRepository` aíslan el acceso a datos. Decisiones de diseño:

- **Transaction-agnostic**: ningún método del repo abre `atomic()` propio. El servicio decide los límites. Esto garantiza atomicidad real cross-repo (si la creación de `Sale` falla después de descontar stock, todo se revierte).
- **Traducen excepciones ORM** a excepciones de dominio: `Item.DoesNotExist → ItemNotFoundError(item_id)`.
- **Conversión de tipos**: `Item.price` es `FloatField`, así que `get_item_price` hace `Decimal(str(item.price))` para preservar precisión al construir `Money`.

**4. Application Service**

`CreateSaleService.execute()` orquesta:

1. Validación de forma (claves esperadas en el payload).
2. Construcción del agregado (que valida invariantes).
3. `check_stock_availability` (fail-fast antes de crear filas).
4. `create_from_aggregate` (inserta `Sale` + `SaleDetail`s).
5. `reduce_stock_batch` (con `select_for_update`).
6. `audit.log_sale_created`.

Todo bajo un único `transaction.atomic()`. Cualquier falla revierte el bloque completo.

**5. Domain Exceptions**

Jerarquía:

```
TransactionError                   (raíz, captura todo lo de dominio)
├── InsufficientStockError         (con atributos item_id, requested, available)
├── ItemNotFoundError              (con atributo item_id)
├── InvalidSaleError               (datos de venta inválidos)
└── UnauthorizedOperationError     (no usado todavía, reservado)
```

Los atributos estructurados de `InsufficientStockError` se serializan al frontend, permitiendo UX rica:

```json
{
  "status": "error",
  "message": "Item 42: requested 100, but only 7 available",
  "item_id": 42, "requested": 100, "available": 7
}
```

**6. Audit logging**

`AuditLogger` registra:
- `SALE_CREATED | sale_id=... | customer_id=... | total=... | user_id=... | timestamp=...`
- `SALE_FAILED | customer_id=... | reason=... | user_id=... | timestamp=...`

Errores inesperados se auditan con prefijo `unexpected:` para distinguirlos de fallas de negocio esperadas.

---

### 5.5 Decisiones arquitectónicas documentadas

Estas son decisiones tomadas durante la re-arquitectura que se apartan del documento original o que requieren justificación.

#### 5.5.1 Límite de cantidad por línea: 1000

El doc original tenía contradicción interna (`SaleLineItem` permitía 10,000 pero `SaleAggregate` rechazaba > 1,000). Decisión: **el límite vive solo en `SaleLineItem`** (invariante de la entidad que lo gobierna). Valor: 1,000. Si una venta requiere más, se divide en varias líneas.

#### 5.5.2 `id: int | None` en vez de `str`

El doc original tipaba `SaleAggregate.id: str = None` pensando en UUIDs. Decisión: **alinear con la realidad** — Django asigna `int` autoincremental a `Sale.id`. Si en el futuro se migra a UUID, es un cambio acotado.

#### 5.5.3 `frozen=True` + `dataclasses.replace`

`SaleAggregate` es inmutable. Para representar "venta tras persistirse" se usa `replace(agg, id=new_id)`. Alternativa rechazada: hacer el agregado mutable. Razón: el agregado inmutable modela mejor el ciclo de vida y previene mutaciones accidentales.

#### 5.5.4 `Money.__add__` valida divisa

El doc original sumaba ignorando `currency`. Decisión: **lanzar `TypeError`** si las divisas difieren. Costo: 2 líneas extra. Beneficio: bugs sutiles imposibles.

#### 5.5.5 `amount_change` como `@property`, no campo

`amount_paid` es input del usuario; `amount_change` se deriva (`amount_paid - grand_total`). Modelarlo como propiedad garantiza que **siempre cuadre** y elimina la posibilidad de que el frontend lo mande mal.

#### 5.5.6 Repos transaction-agnostic

Los métodos del repo **no abren `atomic()` propio**. El servicio decide los límites. Esto fuerza al servicio a pensar explícitamente en la atomicidad, y `select_for_update` exige estar dentro de `atomic` — Django lanzará `TransactionManagementError` si alguien usa el repo fuera de transacción. Esto es **deseable**: previene mal uso silencioso.

#### 5.5.7 `_validate_input` reducido al chequeo de forma

El doc original tenía `_validate_input` que duplicaba validaciones del agregado. Decisión: **el servicio solo valida la forma del dict** (claves `item_id`, `qty` presentes). Las validaciones semánticas (qty > 0, tax en rango) viven en el agregado. DRY.

#### 5.5.8 `ValueError` del agregado se traduce a `InvalidSaleError` en el servicio

`SaleAggregate.__post_init__` lanza `ValueError`. El servicio lo captura y re-lanza como `InvalidSaleError` (parte de la jerarquía `TransactionError`). Alternativa rechazada: hacer que `domain.py` importe `exceptions.py`. Razón: mantener `domain.py` sin dependencias internas.

#### 5.5.9 No enmascarar excepciones inesperadas

El doc original tenía `except Exception → raise InvalidSaleError(...)`. **Eliminado**: si una excepción rara (timeout de BD, OOM) ocurre, debe propagarse tal cual para que la capa HTTP la trate como 500. Solo se audita con prefijo `unexpected:` para investigación.

#### 5.5.10 Servicios cancel y purchase pospuestos

- **`CancelSaleService`** requiere decidir cómo modelar la cancelación (campo `Sale.status`, tabla separada, soft-delete). Esa decisión amplía el scope, así que se pospuso.
- **`CreatePurchaseService`** sería el simétrico para compras, pero `Purchase.save()` + `signals.py` ya tienen un bug (§7) que debe arreglarse antes de envolver con servicio.

#### 5.5.11 No agregar `CustomerNotFoundError`

Cuando `SaleRepository.create_from_aggregate` no encuentra al customer, lanza el genérico `TransactionError(f"Customer {id} not found")` en vez de añadir una nueva clase. Razón: una sola call-site lo necesita, y `TransactionError` ya cubre el caso para el manejo en la vista.

---

## 6. Tests

### Estrategia

- **Unitarios sin BD**: lógica de dominio y servicios con mocks de repositorios. Rápidos (~10ms para los 37 tests actuales). Corren en cualquier entorno con Python.
- **Integración** (a futuro): repos contra BD real con `TransactionTestCase` cuando se quiera validar comportamiento de `select_for_update` bajo concurrencia.

### Estado actual

| Archivo | Tests | Cubre |
|---|---|---|
| `transactions/tests/test_domain.py` | 28 | `Money`, `PriceSnapshot`, `SaleLineItem`, `SaleAggregate` |
| `transactions/tests/test_services.py` | 9 | `CreateSaleService` con mocks (6 escenarios + variantes) |
| **Total** | **37** | |

### Cómo correrlos

```bash
# Domain tests — pura stdlib, no requiere Django
python -m unittest transactions.tests.test_domain

# Suite completa (37 tests) — requiere venv con Django
python manage.py test transactions.tests

# Toda la app transactions
python manage.py test transactions
```

### Por qué `unittest` y no `pytest`

- `pytest` no estaba en `requirements.txt`. Agregarlo solo para tests es scope creep.
- `unittest.TestCase` corre tanto con `python -m unittest` como con `python manage.py test`.
- Los tests son simples (mocks + asserts) — el azúcar de pytest no aporta aquí.

---

## 7. Pendientes y bugs detectados durante la documentación

Estos son hallazgos descubiertos al leer el código completo. **No fueron introducidos por la re-arquitectura** — preexistían. Documentados para acción futura.

### 7.1 ⚠️ Bug crítico: Purchase incrementa stock dos veces

**Archivos**: `transactions/models.py:143-151` y `transactions/signals.py`.

```python
# transactions/models.py
class Purchase(models.Model):
    def save(self, *args, **kwargs):
        self.total_value = self.price * self.quantity
        super().save(*args, **kwargs)
        self.item.quantity += self.quantity   # ← primera vez
        self.item.save()

# transactions/signals.py
@receiver(post_save, sender=Purchase)
def update_item_quantity(sender, instance, created, **kwargs):
    if created:
        instance.item.quantity += instance.quantity   # ← segunda vez
        instance.item.save()
```

Al crear un `Purchase`:
1. `save()` corre `super().save()`, que dispara el signal `post_save`.
2. El signal incrementa `item.quantity` por `purchase.quantity`.
3. Tras `super().save()` retorna, el código en `save()` también incrementa.

**Resultado**: cada compra aumenta el stock por **2× la cantidad real**.

**Arreglo recomendado**: eliminar uno de los dos. El más limpio es **eliminar la mutación de `Purchase.save()`** y dejar solo el signal, o (mejor) reemplazar ambos por un `CreatePurchaseService` que orqueste el aumento de stock explícitamente, como `CreateSaleService` hace con la disminución. Eso restablece simetría con la venta.

### 7.2 ⚠️ Bug: `get_customers` filtra por campo inexistente

**Archivo**: `accounts/views.py:237-239`.

```python
customers = Customer.objects.filter(
    name__icontains=term         # ← Customer no tiene 'name'
).values('id', 'name')
```

`Customer` tiene `first_name` y `last_name`, no `name`. El endpoint AJAX `/get_customers/` no devuelve resultados (probablemente lanza `FieldError` al ejecutar).

**Arreglo**: usar `Q(first_name__icontains=term) | Q(last_name__icontains=term)` y `values('id', 'first_name', 'last_name')` o un método helper.

### 7.3 ⚠️ Duplicación en `InventoryMS/urls.py`

```python
path('staff/', include('accounts.urls')),
path('accounts/', include('accounts.urls')),   # ← mismas URLs, dos prefijos
```

Las mismas rutas de `accounts.urls` están montadas en `/staff/...` y en `/accounts/...`. Resultado: cada URL nombrada (`user-login`, `customer_list`, etc.) tiene dos rutas resolvibles. `reverse()` usa la última registrada. Es probable que sea histórico (alguien renombró `staff/` → `accounts/` pero no quitó el viejo).

**Arreglo**: decidir cuál prefijo es el oficial y eliminar el otro. Verificar que ningún template hardcodea el prefijo no oficial.

### 7.4 ⚠️ `SaleDeleteView` no revierte stock

**Archivo**: `transactions/views.py` (clase `SaleDeleteView`).

Hace hard-delete vía `DeleteView` por defecto. Si un superuser borra una venta, **el stock que se descontó al crearla no vuelve**. El doc del Paso 6 marcó esto como pendiente porque requiere un `CancelSaleService` con decisión previa de modelado:

- Opción A: campo `Sale.status` (`ACTIVE`/`CANCELLED`) — soft-delete.
- Opción B: tabla `SaleCancellation` con FK a `Sale` — auditoría más rica.
- Opción C: prohibir delete y solo permitir cancel.

### 7.5 ⚠️ `SECRET_KEY` y `DEBUG=True` hardcodeados

**Archivo**: `InventoryMS/settings.py:12,15`.

`SECRET_KEY` está hardcoded en el repo y `DEBUG=True`. Para producción mover a variables de entorno (`os.environ.get('DJANGO_SECRET_KEY')`) y `DEBUG=False`. Configurar `ALLOWED_HOSTS`.

### 7.6 ⚠️ `Item.price` es `FloatField`

**Archivo**: `store/models.py:48`.

Para precios monetarios, `DecimalField(max_digits=..., decimal_places=2)` es el estándar. `FloatField` puede acumular errores binarios (e.g., `0.1 + 0.2 == 0.30000000000000004`). La re-arquitectura mitiga esto convirtiendo `Decimal(str(item.price))` en el repo, pero el campo original sigue ahí. Migrar a `DecimalField` es una mejora pendiente.

### 7.7 ⚠️ `Item.quantity` permite negativos

**Archivo**: `store/models.py:47`.

Es `IntegerField`, no `PositiveIntegerField`. Si algún code path resta sin chequear (o si el bug 7.1 lleva la cuenta a desbordarse y luego se decrementa), `quantity` puede quedar negativo. La re-arquitectura previene esto en el camino de ventas (chequeo + lock + decremento atómico), pero migrar el campo refuerza la garantía a nivel de schema.

### 7.8 Funcionalidad pendiente (post-refactor)

- **`CreatePurchaseService`** simétrico a `CreateSaleService` — arregla 7.1 y restaura simetría.
- **`CancelSaleService`** — arregla 7.4.
- **Tests de integración con BD** — validar comportamiento de `select_for_update` bajo concurrencia simulada.
- **API REST** — toda la lógica ya está aislada en servicios; agregar DRF reutilizando `CreateSaleService` es directo.
- **Migración `Item.price` Float→Decimal** y `Item.quantity` Integer→PositiveInteger.

---

*Documento generado tras la implementación de los 7 pasos del plan en `docs/IMPLEMENTACION_PRACTICA.md`. Para historia completa, ver el journal de la conversación y `git log`.*
