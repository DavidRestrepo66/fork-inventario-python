# Evaluación SAAM — Re-arquitectura de `transactions/`

> Método: **SAAM** (Software Architecture Analysis Method, Kazman et al., 1994)
> Objeto: arquitectura por capas resultante de la re-arquitectura de `transactions/`
> Fecha: 2026-05-25

SAAM es un método de evaluación de arquitectura **basado en escenarios**,
orientado principalmente a la **mantenibilidad** (en su sub-característica de
modificabilidad, ISO/IEC 25010). Compara una o más arquitecturas frente a un
conjunto de escenarios de cambio y mide el esfuerzo/impacto de cada uno.

Aquí se compara la **arquitectura anterior** (toda la lógica en `views.py`,
commit `3fab4a4`) contra la **arquitectura nueva** por capas (commit `a09d22f`).

---

## 1. Descripción de las arquitecturas

### Arquitectura A — "Vista gorda" (antes)

```
Browser → views.py (parsing + validación + lógica + ORM + stock + auditoría)
                        └→ store.models.Item   (acoplamiento directo)
                        └→ transactions.models  (Sale, SaleDetail, Purchase)
```

- `SaleCreateView`: ~115 líneas, todo mezclado.
- Sin excepciones de dominio, sin tests, race condition en stock.

### Arquitectura B — Por capas (después)

```
Browser → views.py → services.py → repositories.py → ORM/BD
                         └→ domain.py (puro)
                         └→ audit.py / exceptions.py (transversales)
```

- Capas: HTTP, Servicio, Dominio, Repositorio, ORM.
- Regla de dependencia hacia el dominio; única importación de `Item` en repos.

---

## 2. Desarrollo de escenarios

Escenarios de cambio representativos de la evolución esperada del sistema.

| # | Escenario | Stakeholder | Tipo |
|---|---|---|---|
| E1 | Migrar el ORM de Django a SQLAlchemy / otra fuente de datos | Desarrollador | Indirecto |
| E2 | Cambiar `Item.price` de `FloatField` a `DecimalField` | Desarrollador | Indirecto |
| E3 | Añadir un nuevo canal de salida (API REST/DRF) reutilizando la lógica de venta | Desarrollador / Producto | Indirecto |
| E4 | Añadir reglas de negocio (descuentos, límite por cliente) a la venta | Producto | Indirecto |
| E5 | Auditar a un sistema externo (Splunk/Loki) en vez de logging local | Ops | Indirecto |
| E6 | Añadir un nuevo tipo de excepción de dominio y su respuesta HTTP | Desarrollador | Directo |
| E7 | Probar la lógica de cálculo de totales sin levantar base de datos | QA / Desarrollador | Indirecto |
| E8 | Implementar `CancelSaleService` (rollback de stock + auditoría) | Producto | Indirecto |

> *Directo*: la arquitectura ya lo soporta sin cambios estructurales.
> *Indirecto*: requiere modificar componentes.

---

## 3. Evaluación de escenarios indirectos (esfuerzo e impacto)

Para cada escenario se listan los componentes que deben cambiar en cada arquitectura.

| # | Arq. A (vista gorda) — componentes a tocar | Arq. B (capas) — componentes a tocar | Veredicto |
|---|---|---|---|
| E1 | `views.py` completo + cualquier acceso disperso a `Item` | Solo `repositories.py` | **B** mucho mejor |
| E2 | Buscar todos los `float(...)` en la vista (6 ocurrencias) | `repositories.py` (1 punto: `Decimal(str(...))`) + migración | **B** mejor |
| E3 | Reescribir la lógica completa en la nueva vista (duplicación) | Nueva vista que instancia `CreateSaleService` (reuso total) | **B** decisivo |
| E4 | Insertar `if/else` dentro de la vista de 115 líneas | `domain.SaleAggregate` o nuevo método de servicio | **B** mejor (aislado) |
| E5 | Reemplazar `logger.info` dispersos | `audit.py` (1 componente, 4 métodos) | **B** mejor |
| E6 | Añadir `except` genérico más en la vista | `exceptions.py` + 1 `except` en `views.py` | Empate, **B** más limpio |
| E7 | Imposible sin servidor HTTP + BD | `domain.py`/`services.py` testeables con mocks (54 tests) | **B** decisivo |
| E8 | Replicar toda la lógica inversa en otra vista | Nuevo servicio simétrico reutilizando repos + audit | **B** mejor |

---

## 4. Interacción de escenarios

La **interacción de escenarios** revela cuándo varios escenarios afectan al mismo
componente: alta concentración indica una posible mala asignación de
responsabilidades.

### Arquitectura A
- **E1, E2, E3, E4, E5, E6 → todos tocan `views.py`.**
- Concentración crítica: `views.py` es un punto de cambio para 6 de 8 escenarios.
  Cualquier evolución pasa por el mismo archivo monolítico → alto riesgo de
  regresión y conflictos de merge.

### Arquitectura B
- E1, E2 → `repositories.py`
- E3, E8 → `views.py` + `services.py` (reuso)
- E4 → `domain.py` / `services.py`
- E5 → `audit.py`
- E6 → `exceptions.py`
- E7 → `domain.py` / `services.py` (con mocks)
- **Dispersión sana**: cada escenario se localiza en el componente con esa
  responsabilidad. Ningún componente concentra más de 2-3 escenarios.

---

## 5. Evaluación global y ponderación

Ponderación de escenarios por probabilidad e impacto de negocio (1 bajo – 5 alto).

| # | Escenario | Probabilidad | Impacto | Peso | Favorece |
|---|---|---|---|---|---|
| E3 | Nuevo canal API reutilizando lógica | 4 | 5 | 20 | B |
| E7 | Testeo sin BD | 5 | 4 | 20 | B |
| E4 | Nuevas reglas de negocio | 5 | 4 | 20 | B |
| E1 | Cambio de ORM/fuente de datos | 2 | 5 | 10 | B |
| E8 | CancelSaleService | 4 | 3 | 12 | B |
| E2 | Float → Decimal | 3 | 3 | 9 | B |
| E5 | Auditoría externa | 3 | 2 | 6 | B |
| E6 | Nueva excepción de dominio | 4 | 2 | 8 | B (leve) |

**Conclusión SAAM:** en los 8 escenarios la Arquitectura B reduce el número de
componentes afectados y elimina la concentración de cambios en `views.py`. Los
escenarios de mayor peso (E3, E4, E7) son precisamente los que la nueva separación
en capas resuelve de forma decisiva. La re-arquitectura está **justificada desde la
mantenibilidad** (modificabilidad y testeabilidad), sin penalizar los escenarios
de bajo peso.

---

## 6. Limitaciones de este análisis SAAM

- SAAM evalúa principalmente **mantenibilidad** (modificabilidad); atributos como
  eficiencia de ejecución, confiabilidad y seguridad se analizan en la evaluación
  **ATAM** (ver `EVALUACION_ATAM.md`).
- Los pesos son estimaciones; deberían validarse con los stakeholders reales.
- E8 (`CancelSaleService`) sigue siendo **deuda técnica pendiente**: el análisis
  muestra que la arquitectura lo facilita, pero aún no está implementado.
