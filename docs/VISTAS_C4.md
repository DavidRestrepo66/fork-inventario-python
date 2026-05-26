# Vistas Lógicas del Sistema — Modelo C4

> Sistema: **InventoryMS** (Django — inventario y transacciones)
> Alcance: arquitectura tras la re-arquitectura de `transactions/`
> Fecha: 2026-05-25

El modelo C4 (Context, Containers, Components, Code) describe la arquitectura en
cuatro niveles de zoom progresivo. Cada nivel responde a una audiencia distinta:
del stakeholder no técnico (Nivel 1) al desarrollador que mantiene el código
(Nivel 4).

| Nivel | Vista | Pregunta que responde | Audiencia |
|---|---|---|---|
| 1 | Contexto del Sistema | ¿Quién usa el sistema y con qué interactúa? | Todos |
| 2 | Contenedores | ¿De qué piezas desplegables se compone? | Técnica / DevOps |
| 3 | Componentes | ¿Cómo se organiza `transactions` internamente? | Desarrolladores |
| 4 | Código | ¿Qué clases y relaciones implementan los componentes? | Desarrolladores |

---

## Nivel 1 — Diagrama de Contexto del Sistema

Muestra InventoryMS como una caja negra y los actores que interactúan con él.

```mermaid
C4Context
    title Nivel 1 — Contexto del Sistema: InventoryMS

    Person(staff, "Personal de ventas", "Registra ventas y consulta inventario")
    Person(admin, "Administrador / Superusuario", "Gestiona items, vendors, usuarios; elimina transacciones")

    System(invms, "InventoryMS", "Sistema de gestión de inventario, ventas, compras y facturación")

    System_Ext(browser, "Navegador web", "Cliente que renderiza HTML y envía POST AJAX/JSON")

    Rel(staff, browser, "Usa")
    Rel(admin, browser, "Usa")
    Rel(browser, invms, "HTTP / HTTPS", "HTML, JSON")

    UpdateLayoutConfig($c4ShapeInRow="2", $c4BoundaryInRow="1")
```

**Notas:**
- El sistema es un **monolito Django**: no consume APIs externas de pago,
  notificaciones ni terceros en su estado actual.
- La autorización distingue dos roles: el personal de ventas (`LoginRequiredMixin`)
  y el superusuario (`UserPassesTestMixin` para borrados).

---

## Nivel 2 — Diagrama de Contenedores

Hace zoom dentro de InventoryMS y muestra las unidades desplegables.

```mermaid
C4Container
    title Nivel 2 — Contenedores: InventoryMS

    Person(staff, "Personal de ventas", "Registra ventas")
    Person(admin, "Administrador", "Gestiona catálogo y usuarios")

    System_Boundary(invms, "InventoryMS") {
        Container(web, "Aplicación Web Django", "Python 3.14 / Django", "Renderiza vistas, expone endpoints AJAX, aplica lógica de negocio por capas")
        Container(static, "Archivos estáticos", "CSS / JS / imágenes", "Bootstrap, select2, scripts del carrito de venta")
        ContainerDb(db, "Base de datos", "SQLite (dev) / PostgreSQL (prod)", "Items, Sales, SaleDetails, Purchases, Customers, Vendors, Bills, Invoices")
    }

    Rel(staff, web, "Registra ventas/compras", "HTTPS")
    Rel(admin, web, "Administra", "HTTPS")
    Rel(web, static, "Sirve")
    Rel(web, db, "Lee/escribe — ORM Django, select_for_update en stock", "SQL")

    UpdateLayoutConfig($c4ShapeInRow="2", $c4BoundaryInRow="1")
```

**Notas:**
- Un solo contenedor de aplicación (proyecto `InventoryMS/`) que agrupa las apps
  Django: `store`, `transactions`, `accounts`, `bills`, `invoice`.
- El acceso concurrente al stock se serializa a nivel de base de datos mediante
  `SELECT ... FOR UPDATE` (locks de fila) dentro de transacciones atómicas.
- `Dockerfile` presente → despliegue contenedorizado.

---

## Nivel 3 — Diagrama de Componentes (app `transactions`)

Hace zoom dentro del contenedor web, enfocado en la app re-arquitecturada.
Las flechas apuntan "hacia adentro" (hacia el dominio): la regla de dependencia
de la arquitectura por capas.

```mermaid
C4Component
    title Nivel 3 — Componentes: app transactions

    Container_Boundary(web, "Aplicación Web Django") {

        Component(views, "views.py", "Django Views / CBV", "Parsea HTTP, traduce excepciones de dominio a JSON/HTTP. NO contiene lógica de negocio")
        Component(services, "services.py", "Service Layer", "CreateSaleService, CreatePurchaseService. Orquesta dominio+repos. Define límites transaction.atomic()")
        Component(domain, "domain.py", "Domain Model (POPO)", "Money, PriceSnapshot, SaleLineItem, SaleAggregate. Sin dependencia de Django")
        Component(repos, "repositories.py", "Repository Pattern", "InventoryRepository, SaleRepository, PurchaseRepository. Único punto de acceso al ORM")
        Component(audit, "audit.py", "Cross-cutting", "AuditLogger — logging estructurado KEY=value")
        Component(exc, "exceptions.py", "Cross-cutting", "Jerarquía TransactionError tipada")
        Component(models, "models.py", "Django ORM", "Sale, SaleDetail, Purchase")

        Component(store, "store.models.Item", "Django ORM", "Inventario — propiedad de la app store")
    }

    ContainerDb(db, "Base de datos", "SQLite/PostgreSQL", "")

    Rel(views, services, "Delega lógica")
    Rel(views, repos, "Instancia (DI)")
    Rel(views, audit, "Instancia (DI)")
    Rel(views, exc, "Captura")

    Rel(services, repos, "Usa")
    Rel(services, domain, "Construye/valida")
    Rel(services, audit, "Registra eventos")
    Rel(services, exc, "Lanza/propaga")
    Rel(services, models, "Retorna entidades")

    Rel(repos, domain, "Construye Money")
    Rel(repos, exc, "Lanza")
    Rel(repos, models, "Persiste")
    Rel(repos, store, "Lee/actualiza stock (select_for_update)")
    Rel(domain, exc, "Valida con ValueError")

    Rel(repos, db, "SQL")
    Rel(models, db, "SQL")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

**Regla de dependencia (clave de la re-arquitectura):**
- `domain.py` no importa **nada** del proyecto → núcleo estable y testeable sin BD.
- `repositories.py` es el **único** componente que importa `store.models.Item`,
  eliminando el acoplamiento directo entre apps que tenía la vista original.
- `services.py` no importa `django.http` ni `django.views` → lógica de negocio
  reutilizable fuera del contexto HTTP.

---

## Nivel 4 — Diagrama de Código (clases de `transactions`)

Máximo nivel de detalle: clases y relaciones. Se omiten clases base de Django
para legibilidad.

```mermaid
classDiagram
    direction LR

    %% ---- DOMAIN ----
    class Money {
        +Decimal amount
        +str currency
        +__add__(Money) Money
        +__mul__(scalar) Money
    }
    class PriceSnapshot {
        +Decimal amount
        +datetime captured_at
        +int item_id
        +to_money() Money
    }
    class SaleLineItem {
        +int item_id
        +int quantity
        +PriceSnapshot price_snapshot
        +total() Money
    }
    class SaleAggregate {
        +int customer_id
        +list~SaleLineItem~ line_items
        +Decimal tax_percentage
        +Decimal amount_paid
        +subtotal() Money
        +tax_amount() Money
        +grand_total() Money
        +amount_change() Money
    }
    SaleAggregate --> "1..*" SaleLineItem
    SaleLineItem --> PriceSnapshot
    PriceSnapshot ..> Money
    SaleAggregate ..> Money

    %% ---- EXCEPTIONS ----
    class TransactionError {
        <<exception>>
    }
    class InsufficientStockError {
        <<exception>>
        +int item_id
        +int requested
        +int available
    }
    class ItemNotFoundError {
        <<exception>>
        +int item_id
    }
    class InvalidSaleError
    class InvalidPurchaseError
    TransactionError <|-- InsufficientStockError
    TransactionError <|-- ItemNotFoundError
    TransactionError <|-- InvalidSaleError
    TransactionError <|-- InvalidPurchaseError

    %% ---- REPOSITORIES ----
    class InventoryRepository {
        +get_available_stock(item_id) int
        +get_item_price(item_id) Money
        +check_stock_availability(dict) None
        +reduce_stock(item_id, qty) None
        +reduce_stock_batch(dict) None
        +increase_stock(item_id, qty) None
    }
    class SaleRepository {
        +create_from_aggregate(SaleAggregate) Sale
        +get_by_id(sale_id) Sale
    }
    class PurchaseRepository {
        +create(...) Purchase
    }
    InventoryRepository ..> Money
    InventoryRepository ..> InsufficientStockError
    SaleRepository ..> SaleAggregate

    %% ---- SERVICES ----
    class CreateSaleService {
        -InventoryRepository inventory
        -SaleRepository sales
        -AuditLogger audit
        +execute(customer_id, items, tax, paid, user_id) Sale
    }
    class CreatePurchaseService {
        -InventoryRepository inventory
        -PurchaseRepository purchases
        -AuditLogger audit
        +execute(item_id, vendor_id, qty, price, ...) Purchase
    }
    CreateSaleService --> InventoryRepository
    CreateSaleService --> SaleRepository
    CreateSaleService --> AuditLogger
    CreateSaleService ..> SaleAggregate
    CreatePurchaseService --> InventoryRepository
    CreatePurchaseService --> PurchaseRepository
    CreatePurchaseService --> AuditLogger

    %% ---- AUDIT ----
    class AuditLogger {
        +log_sale_created(...)
        +log_sale_failed(...)
        +log_purchase_created(...)
        +log_purchase_failed(...)
    }

    %% ---- VIEWS ----
    class SaleCreateView {
        <<function>>
    }
    class PurchaseCreateView {
        <<CBV>>
        +form_valid(form)
    }
    SaleCreateView --> CreateSaleService
    PurchaseCreateView --> CreatePurchaseService
```

---

## Resumen de las cuatro vistas

| Vista C4 | Elemento central | Aporta a la comprensión de... |
|---|---|---|
| Contexto | InventoryMS + actores | El propósito y los límites del sistema |
| Contenedores | App Django + BD + estáticos | Topología de despliegue |
| Componentes | Capas de `transactions` | Separación de responsabilidades y regla de dependencia |
| Código | Clases y excepciones | Implementación concreta de cada componente |
