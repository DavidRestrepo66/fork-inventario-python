# Guion de Presentación — Proyecto InventoryMS (Módulo MVP)

> Documento de exposición. Cubre los cuatro bloques solicitados.
> Fecha: 2026-05-25

---

## 1. Contexto del proyecto

### Problema que resuelve el sistema
InventoryMS gestiona el **inventario, las ventas y las compras** de un comercio:
controla el stock de cada item, registra las ventas a clientes con su detalle y
totales (subtotal, impuesto, total, cambio), y las compras a proveedores que
reponen el stock.

El problema central no era funcional sino **arquitectónico**: el módulo de
transacciones concentraba toda la responsabilidad en las vistas. `SaleCreateView`
tenía ~115 líneas que mezclaban parsing HTTP, validación, lógica de negocio,
acceso a la base de datos, actualización de stock y auditoría. Esto provocaba:
acoplamiento directo entre apps, **race conditions en el stock**, imposibilidad de
testear sin servidor HTTP, y nula trazabilidad de operaciones fallidas.

### Alcance del módulo MVP
El MVP es la **app `transactions/` re-arquitecturada**, con dos casos de uso
completos de punta a punta:

- **Crear venta** (`SaleCreateView`): valida, reserva stock con bloqueo, persiste
  venta + detalle y audita.
- **Crear compra** (`PurchaseCreateView`): persiste la compra e incrementa stock
  de forma atómica.

Quedan **fuera del MVP** (deuda consciente): cancelación de ventas
(`CancelSaleService`), migración de `Item.price` a `DecimalField`, y una API REST
formal con DRF.

---

## 2. Arquitectura propuesta

### Vista lógica final
El módulo se organiza en **capas con regla de dependencia hacia el dominio**:

```
┌──────────────────────────────────────────────┐
│  views.py        (Capa HTTP)                   │  parsing + traducción de errores
├──────────────────────────────────────────────┤
│  services.py     (Capa de Servicio)            │  orquestación + transaction.atomic()
├──────────────────────────────────────────────┤
│  domain.py       (Dominio puro, sin Django)    │  reglas de negocio + value objects
├──────────────────────────────────────────────┤
│  repositories.py (Capa de Repositorio)         │  ÚNICO acceso al ORM / store.Item
├──────────────────────────────────────────────┤
│  models.py / ORM Django / Base de datos        │
└──────────────────────────────────────────────┘
   Transversales: exceptions.py · audit.py
```

### Componentes principales y responsabilidades

| Componente | Responsabilidad | Regla clave |
|---|---|---|
| `views.py` | Parsear HTTP/JSON, traducir excepciones de dominio a respuestas | No contiene lógica de negocio |
| `services.py` | Orquestar dominio + repositorios; definir límites transaccionales | No importa `django.http` ni `django.views` |
| `domain.py` | Entidades puras: `Money`, `PriceSnapshot`, `SaleLineItem`, `SaleAggregate` | No importa nada del proyecto |
| `repositories.py` | Acceso a datos (`Item`, `Sale`, `Purchase`) | Único módulo que importa `store.models.Item` |
| `exceptions.py` | Jerarquía de errores de dominio tipados | Capturables como grupo o por tipo |
| `audit.py` | Logging estructurado de eventos críticos | Se invoca antes de re-lanzar fallos |

### Diagramas C4 clave
Los diagramas completos están en **`VISTAS_C4.md`**. Para la exposición se
recomiendan dos:

1. **Nivel 2 — Contenedores**: muestra el monolito Django, la base de datos y los
   estáticos; útil para situar al público.
2. **Nivel 3 — Componentes (`transactions`)**: muestra las capas y la regla de
   dependencia hacia el dominio; es el corazón del MVP.

### Estilo arquitectónico predominante
**Arquitectura por capas (Layered)** combinada con **Domain-Driven Design ligero**:
Repository Pattern, Service Layer y un Aggregate de dominio (`SaleAggregate`).

**Por qué se eligió:** el problema no requería microservicios (un solo dominio
acotado, un solo equipo, un despliegue). La arquitectura por capas resuelve los
dolores reales —acoplamiento, testeabilidad y race conditions— con la mínima
complejidad, manteniendo el despliegue monolítico de Django intacto y sin tocar la
base de datos.

---

## 3. Refactorización y código

### Problemas de la versión inicial
- **Vista gorda**: `SaleCreateView` con ~115 líneas; toda la lógica acoplada al HTTP.
- **Acoplamiento entre apps**: la vista importaba `store.models.Item` directamente.
- **Race condition**: `item.quantity -= qty; item.save()` sin bloqueo de fila →
  dos ventas concurrentes podían sobre-vender el stock.
- **Precisión**: uso de `float()` para montos monetarios (6 ocurrencias).
- **Sin excepciones de dominio**: todo era `ValueError`/`Exception` genérico.
- **Sin tests** y **sin auditoría** de fallos.

### Cambios más importantes

**Separación de capas / servicios**
- Se extrajo la lógica a `CreateSaleService` y `CreatePurchaseService`.
- Acceso a datos aislado en `InventoryRepository`, `SaleRepository`,
  `PurchaseRepository`.
- Reglas de negocio en `domain.py` (`SaleAggregate` valida en `__post_init__`:
  si el agregado se construye, la venta es válida por definición).

**Corrección de la race condition**
- `InventoryRepository.reduce_stock()` usa `select_for_update()` dentro de
  `transaction.atomic()` (gestionado por el servicio) → locks de fila que serializan
  el acceso concurrente al mismo item.

**Endpoints**
- El sistema usa el patrón **MVT de Django** (Model-View-Template), no REST puro.
- `SaleCreateView` expone un endpoint **AJAX/JSON** (`POST /transactions/sales/`)
  que recibe el carrito y devuelve `JsonResponse` con `sale_id` o errores
  estructurados (incluye `item_id`, `requested`, `available` en stock insuficiente).
- `PurchaseCreateView` es una CBV basada en formulario Django que delega en el
  servicio. *(Una API REST formal con DRF queda como evolución futura — la
  arquitectura ya lo permite reutilizando los servicios.)*

**Patrones aplicados**
- **MVT** (base Django) + **Service Layer** + **Repository** + **Domain Model /
  Aggregate** + **jerarquía de excepciones de dominio**.

### Demo del MVP funcionando
Para mostrar el módulo en vivo:
```bash
python manage.py runserver
```
- **Venta**: `/transactions/sales/` → seleccionar cliente, añadir items al carrito,
  confirmar → se crea la venta y se descuenta stock.
- **Stock insuficiente**: intentar vender más unidades de las disponibles →
  respuesta 400 con `item_id`, `requested`, `available`.
- **Compra**: `/transactions/purchases/new/` → registrar compra → el stock del item
  aumenta atómicamente.
- *(Insertar aquí capturas de pantalla de cada flujo para la presentación.)*

---

## 4. Atributos de calidad y conclusiones

### Atributos priorizados (ISO/IEC 25010) y cómo los aborda la arquitectura

1. **Mantenibilidad** — la separación en capas localiza cada tipo de cambio en un
   único componente y eliminó la concentración de cambios en `views.py`. Incluye la
   *testeabilidad*: `domain.py` no depende de Django y los servicios usan inyección
   de dependencias, lo que permitió **54 tests (38 sin base de datos)** donde antes
   había cero.

2. **Confiabilidad** — `select_for_update()` evita el sobre-venta del stock bajo
   concurrencia y `transaction.atomic()` en el servicio garantiza rollback completo
   (recuperabilidad) ante cualquier fallo intermedio.

3. **Idoneidad funcional** — el dominio usa `Decimal` y captura el precio en un
   `PriceSnapshot`, asegurando la corrección de los totales (subtotal, impuesto,
   total, cambio) y eliminando la imprecisión del `float` anterior.

*(Análisis formal en `EVALUACION_SAAM.md` y `EVALUACION_ATAM.md`.)*

### Lección aprendida principal
La garantía de concurrencia (`select_for_update`) **solo es efectiva sobre
PostgreSQL/MySQL**, no sobre el SQLite usado en desarrollo. La próxima vez
**definiríamos el backend de producción y un test de integración de concurrencia
desde el inicio**, en lugar de validar la protección de stock únicamente con mocks
— para no arriesgarnos a que una garantía clave del diseño no se cumpla en el
entorno real.
