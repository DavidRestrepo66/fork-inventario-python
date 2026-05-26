# Evaluación ATAM — Re-arquitectura de `transactions/`

> Método: **ATAM** (Architecture Tradeoff Analysis Method, Kazman/Klein/Clements, SEI)
> Objeto: arquitectura por capas resultante de la re-arquitectura de `transactions/`
> Fecha: 2026-05-25

ATAM extiende a SAAM analizando **múltiples atributos de calidad simultáneamente** y,
sobre todo, los **puntos de compromiso (tradeoffs)**: decisiones que mejoran un
atributo a costa de otro. Sus salidas clave son: *utility tree*, escenarios de
calidad, puntos de sensibilidad, puntos de compromiso, **riesgos** y **no-riesgos**.

---

## 1. Drivers arquitectónicos (atributos de calidad priorizados)

> Atributos según ISO/IEC 25010.

| Atributo | Por qué importa en este sistema |
|---|---|
| **Mantenibilidad** | Sistema en evolución activa; `SaleCreateView` de 115 líneas era inmantenible. Incluye *modificabilidad* y *testeabilidad* como sub-características |
| **Confiabilidad** | El stock no puede quedar negativo ni inconsistente; recuperabilidad ante fallos a mitad de operación (atomicidad) |
| **Eficiencia de ejecución** | La operación de venta debe responder rápido bajo carga moderada |
| **Seguridad** | Trazabilidad / no repudio de operaciones críticas (auditoría de ventas y compras) |
| **Idoneidad funcional** | Corrección de los totales calculados (precisión monetaria) |
| **Portabilidad** | Capacidad de sustituir el backend de datos / ORM sin reescribir la lógica |

---

## 2. Árbol de utilidad (Utility Tree)

Formato: `Atributo → Refinamiento → Escenario (Importancia, Dificultad)`
Escala: A (alta), M (media), B (baja).

```
Utilidad
├── Confiabilidad
│   ├── Tolerancia a fallos / concurrencia
│   │   └── [Q1] Dos ventas simultáneas del mismo item no sobre-venden stock      (A, A)
│   └── Recuperabilidad
│       └── [Q2] Fallo a mitad de venta no deja stock reducido sin venta          (A, M)
│
├── Idoneidad funcional
│   └── Corrección
│       └── [Q3] Los totales no pierden precisión decimal                          (A, B)
│
├── Portabilidad
│   └── Reemplazabilidad
│       └── [Q4] Cambiar de Django ORM a otra fuente toca un solo componente       (M, M)
│
├── Mantenibilidad
│   ├── Modificabilidad
│   │   └── [Q5] Reusar la lógica de venta desde una API REST sin duplicar         (A, B)
│   └── Testeabilidad
│       └── [Q6] Probar reglas de negocio y totales sin levantar BD ni HTTP        (A, B)
│
├── Seguridad
│   └── No repudio / trazabilidad
│       └── [Q7] Toda venta/compra fallida deja traza estructurada y filtrable     (M, B)
│
└── Eficiencia de ejecución
    └── Comportamiento temporal
        └── [Q8] La venta responde < 300 ms con stock disponible bajo carga normal (M, M)
```

---

## 3. Análisis de los enfoques arquitectónicos

Para cada escenario de calidad de alta prioridad, qué decisión arquitectónica lo
soporta y qué consecuencias tiene.

### Q1 — Concurrencia en stock
- **Decisión:** `InventoryRepository.reduce_stock()` usa
  `Item.objects.select_for_update()` dentro de `transaction.atomic()` (en el servicio).
- **Efecto:** lock de fila en la BD; ventas concurrentes del mismo item se serializan.
- **Sensibilidad:** depende de un backend que soporte `SELECT FOR UPDATE`
  (PostgreSQL/MySQL). **SQLite no implementa locks de fila reales** → el escenario
  no se cumple en el entorno de desarrollo actual.

### Q2 — Atomicidad
- **Decisión:** el **servicio** define el límite `transaction.atomic()`; los
  repositorios son transaction-agnostic.
- **Efecto:** cualquier fallo entre persistir la venta y reducir stock provoca
  rollback completo. No hay estados intermedios inconsistentes.

### Q3 — Precisión monetaria
- **Decisión:** `domain.Money` usa `Decimal`; el repositorio convierte el
  `FloatField` de `Item.price` vía `Decimal(str(item.price))`.
- **Efecto:** se neutraliza la imprecisión de float en los cálculos.

### Q4 / Q5 — Portabilidad (reemplazabilidad) y Mantenibilidad (modificabilidad)
- **Decisión:** Repository Pattern + Service Layer + Domain puro; regla de
  dependencia hacia el dominio.
- **Efecto:** el ORM se aísla en `repositories.py`; la lógica de venta se invoca
  igual desde una vista función, una CBV o una futura `APIView`.

### Q6 — Mantenibilidad (testeabilidad)
- **Decisión:** `domain.py` sin Django; servicios con inyección de dependencias
  (repos/auditor por constructor) → sustituibles por mocks.
- **Efecto:** 54 tests, 38 sin BD. Ciclo de feedback rápido.

### Q7 — Seguridad (no repudio / trazabilidad)
- **Decisión:** `AuditLogger` con logging `KEY=value`; el servicio llama a
  `log_*_failed` **antes** de re-lanzar cualquier excepción.
- **Efecto:** ningún fallo queda sin traza.

### Q8 — Eficiencia de ejecución
- **Decisión:** `check_stock_availability` (lectura optimista) **antes** de
  `reduce_stock` (con lock); `save(update_fields=['quantity'])`.
- **Efecto:** UPDATE mínimo; pero hay una **lectura extra por item** previa al lock.

---

## 4. Puntos de sensibilidad

Decisiones donde un cambio altera notablemente un atributo de calidad.

| ID | Punto de sensibilidad | Atributo afectado |
|---|---|---|
| S1 | Uso de `select_for_update()` | Confiabilidad |
| S2 | Backend de BD elegido (SQLite vs PostgreSQL) | Confiabilidad / Portabilidad (S1 sólo funciona en PostgreSQL/MySQL) |
| S3 | Ubicación de `transaction.atomic()` en el servicio | Confiabilidad / Mantenibilidad |
| S4 | Inyección de dependencias en los servicios | Mantenibilidad (testeabilidad) |
| S5 | `Decimal(str(...))` para convertir `FloatField` | Idoneidad funcional |

---

## 5. Puntos de compromiso (Tradeoffs)

Decisiones que mejoran un atributo a costa de otro — el corazón de ATAM.

| ID | Tradeoff | Gana | Pierde |
|---|---|---|---|
| T1 | `select_for_update()` serializa ventas del mismo item | **Confiabilidad** | **Eficiencia de ejecución** (throughput) bajo alta contención del mismo item |
| T2 | `check_stock_availability` antes del lock | Usabilidad (error temprano) | **Eficiencia de ejecución**: lectura redundante (el lock vuelve a verificar) |
| T3 | 5 capas (views/services/domain/repos/audit) | **Mantenibilidad** | Mayor complejidad estructural: más archivos e indirección para un cambio trivial |
| T4 | Validación en `__post_init__` de dataclasses frozen | **Idoneidad funcional / Confiabilidad** | Flexibilidad: el agregado no admite estados intermedios "en construcción" |
| T5 | `DO_NOTHING` en FK `Sale.customer` (modelo) | Eficiencia de ejecución (borrado) | **Confiabilidad** (integridad referencial, riesgo de huérfanos) |

---

## 6. Riesgos

| ID | Riesgo | Severidad | Mitigación recomendada |
|---|---|---|---|
| R1 | **SQLite no aplica `select_for_update`**: la protección de concurrencia (Q1/S1) no opera en dev y podría no operar en prod si no se migra | **Alta** | Usar PostgreSQL en prod; test de integración de concurrencia |
| R2 | `Item.price` sigue siendo `FloatField`: la fuente de verdad es imprecisa pese a la conversión | Media | Migrar a `DecimalField` (escenario E2 de SAAM) |
| R3 | `CancelSaleService` no implementado: no hay rollback auditado de ventas | Media | Implementar servicio simétrico (deuda técnica documentada) |
| R4 | Tests de servicios usan mocks: no validan el comportamiento real de `select_for_update` bajo concurrencia | Media | Añadir test de integración con BD real y hilos concurrentes |
| R5 | `Sale.customer` y `SaleDetail.item` con `on_delete=DO_NOTHING`: posibles registros huérfanos | Baja | Revisar política de borrado (`PROTECT`/`RESTRICT`) |
| R6 | `T2` (doble verificación de stock) añade carga innecesaria por item | Baja | Simplificar a verificación única dentro del lock |

---

## 7. No-riesgos

Decisiones que el análisis confirma como **sólidas**:

- **N1** — Aislamiento del ORM en `repositories.py`: el cambio de fuente de datos
  está correctamente acotado.
- **N2** — Lógica de negocio en `domain.py` sin Django: testeable y portable.
- **N3** — `transaction.atomic()` en el servicio garantiza atomicidad real (Q2),
  válido en cualquier backend transaccional.
- **N4** — Auditoría previa al re-lanzamiento: ningún fallo queda sin traza (Q7).
- **N5** — Inyección de dependencias: testeabilidad sin frameworks de mocking de BD.

---

## 8. Conclusión ATAM

La re-arquitectura cumple con fuerza los atributos **mantenibilidad
(modificabilidad y testeabilidad), confiabilidad (atomicidad) y seguridad
(trazabilidad)** (no-riesgos N1–N5). El principal
**riesgo abierto es R1**: la garantía estrella de concurrencia (`select_for_update`)
**solo es efectiva sobre PostgreSQL/MySQL**, no sobre el SQLite usado en desarrollo
— es a la vez el punto de sensibilidad más crítico (S1/S2) y el tradeoff de mayor
impacto (T1). La recomendación prioritaria es **garantizar PostgreSQL en producción
y cubrir la concurrencia con un test de integración real**. Los tradeoffs T2 y T3
son aceptables y conscientes; T5 merece revisión de la política de borrado.
