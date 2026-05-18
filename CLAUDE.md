# Proyecto: Fork Inventario Python

## Contexto
Sistema Django de inventario y transacciones. Actualmente en proceso de re-arquitectura.

## Problema principal
- `transactions/views.py` tiene vistas gordas (115 líneas en SaleCreateView)
- Acoplamiento directo entre transactions y store.models.Item
- Sin auditoría, sin repositorios, sin capa de servicios
- Race conditions en actualización de stock

## Arquitectura objetivo
Crear en `transactions/`:
1. `exceptions.py` - Excepciones de dominio
2. `domain.py` - Entidades puras (SaleAggregate, SaleLineItem)
3. `repositories.py` - InventoryRepository, SaleRepository
4. `services.py` - CreateSaleService, CancelSaleService
5. `audit.py` - AuditLogger
6. Refactorizar `views.py` para usar servicios

## Estado actual
- [ ] Paso 1: exceptions.py
- [ ] Paso 2: domain.py
- [ ] Paso 3: repositories.py
- [ ] Paso 4: services.py
- [ ] Paso 5: audit.py
- [ ] Paso 6: refactorizar views.py
- [ ] Paso 7: tests unitarios

## Reglas importantes
- Los servicios NO importan django.http ni django.views
- Solo repositories.py importa store.models.Item
- Cada paso debe tener tests unitarios antes de continuar
- Usar select_for_update() en operaciones de stock