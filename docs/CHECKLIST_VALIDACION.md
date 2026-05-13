# ✅ Checklist de Validación Arquitectónica

## 📊 Instrucciones
- Marca cada punto según tu grado de cumplimiento
- Una implementación "correcta" debe tener ✅ en TODOS los puntos
- Los puntos con ⚠️ son recomendaciones de mejora (no bloqueantes)
- Los puntos con 🔴 son críticos (pueden causar problemas)

---

## 🏗️ A. DESACOPLAMIENTO Y SEPARACIÓN DE RESPONSABILIDADES

### A1. Capa de Servicios ✅
- [ ] Existe `services.py` con al menos 2 servicios (`CreateSaleService`, `CancelSaleService`)
- [ ] La lógica de negocio está en servicios, NO en vistas
- [ ] Los servicios NO importan `django.http` o `django.views`
- [ ] Los servicios NO acceden directamente a `Item` (store)
- [ ] Los servicios usan inyección de dependencias (constructores)

**Validación**: 
```bash
# Estos comandos NO deberían encontrar imports de Django en services.py
grep -n "from django.http\|from django.views\|from django.shortcuts" transactions/services.py

# Verificar que servicios usan repositorios
grep -n "self.inventory\|self.sales\|self.repo" transactions/services.py
```

---

### A2. Capa de Repositorios 🔴
- [ ] Existe `repositories.py` con `InventoryRepository` y `SaleRepository`
- [ ] Repositorio es la ÚNICA forma de acceder a `Item` desde transactions
- [ ] Los cambios en `store/models.py` SOLO afectan `repositories.py`
- [ ] Repositorios usan `select_for_update()` para evitar race conditions
- [ ] Repositorios manejan excepciones y las convierten a excepciones de negocio

**Validación**:
```python
# En transactions/views.py NO debería haber:
from store.models import Item  # ❌ NUNCA

# En transactions/services.py DEBERÍA estar:
self.inventory.get_item_price(item_id)  # ✅ A través de repo
```

---

### A3. Entidades de Dominio Puro ⚠️
- [ ] Existe `domain.py` con `SaleAggregate`, `SaleLineItem`
- [ ] Las entidades son clases Python puras (NO heredan de `models.Model`)
- [ ] Las entidades son inmutables (usar `@dataclass(frozen=True)` o `namedtuple`)
- [ ] Las entidades expresan reglas de negocio (validaciones en `__post_init__`)
- [ ] Las entidades pueden ser instanciadas SIN conexión a BD

**Validación**:
```bash
# Esto debe funcionar SIN Django:
cd /home/claude/proyecto-inventario
python << 'EOF'
from transactions.domain import SaleAggregate, SaleLineItem, PriceSnapshot
from datetime import datetime
from decimal import Decimal

price = PriceSnapshot(Decimal("100"), datetime.now(), 1)
line = SaleLineItem(1, 5, price)
# Si llegaste aquí sin errores, ✅ funciona
EOF
```

---

### A4. Excepciones de Dominio ✅
- [ ] Existe `exceptions.py` con excepciones específicas
- [ ] Excepciones heredan de excepción base personalizada
- [ ] Cada excepción representa un error de negocio (no técnico)
- [ ] Las vistas atrapan excepciones y convierten a respuestas HTTP

**Ejemplos**:
```python
# ✅ CORRECTO
class InsufficientStockError(TransactionError):
    def __init__(self, item_id, requested, available):
        self.item_id = item_id
        ...

# ❌ INCORRECTO
class ItemDoesNotExistError(TransactionError):
    # Muy técnico, usar ItemNotFoundError
```

---

## 🔒 B. ATOMICIDAD Y CONSISTENCIA

### B1. Transacciones Completas 🔴
- [ ] `CreateSaleService` usa `transaction.atomic()` internamente
- [ ] Todas las operaciones (crear Sale, SaleDetail, reducir stock) están dentro de la transacción
- [ ] Si cualquier paso falla, TODO se revierte automáticamente
- [ ] Se usa `select_for_update()` para locks de DB en operaciones concurrentes

**Validación**:
```python
# En repositories.py, debería verse:
with transaction.atomic():
    item = Item.objects.select_for_update().get(id=item_id)
    item.quantity -= quantity
    item.save()
```

### B2. Race Conditions Prevenidas 🔴
- [ ] No hay actualización de stock sin `select_for_update()`
- [ ] No hay deadlocks documentados
- [ ] Se ha testeado concurrencia (múltiples transacciones simultáneas)

**Test de concurrencia**:
```bash
# Simular 10 usuarios vendiendo del mismo item simultáneamente
python << 'EOF'
from threading import Thread
from transactions.services import CreateSaleService

def sell():
    service = CreateSaleService(...)
    service.execute(customer_id=1, items=[{'item_id': 1, 'qty': 1}])

threads = [Thread(target=sell) for _ in range(10)]
for t in threads:
    t.start()
for t in threads:
    t.join()

# Si llega aquí sin errores, las transacciones son seguras
EOF
```

---

### B3. Efectos Secundarios Eliminados 🔴
- [ ] `Purchase.save()` NO modifica `Item.quantity` implícitamente
- [ ] NO hay lógica de negocio en métodos `save()` de modelos
- [ ] Toda lógica está en servicios y repositorios

**Validación**:
```bash
# Buscar lógica en save():
grep -n "def save" transactions/models.py
# Si ve "item.quantity += ..." dentro, ❌ aún hay acoplamiento
```

---

## 🧪 C. TESTABILIDAD

### C1. Tests Unitarios Sin BD 🔴
- [ ] Existe `tests/test_services.py` con tests que NO usan BD
- [ ] Los tests usan mocks para repositorios
- [ ] Los tests corren en < 2 segundos
- [ ] Cobertura de servicios > 80%

**Validación**:
```bash
cd proyecto-inventario
pytest transactions/tests/test_services.py -v --tb=short

# Debería ver algo como:
# test_create_sale_success PASSED
# test_create_sale_insufficient_stock PASSED
# ... (en menos de 2 segundos)
```

### C2. Tests de Repositorios 🔴
- [ ] Existe `tests/test_repositories.py`
- [ ] Los tests usan fixtures de BD (TestCase de Django)
- [ ] Se testean casos de error (ItemNotFound, InsufficientStock)

### C3. Tests de Dominio ⚠️
- [ ] Existe `tests/test_domain.py`
- [ ] Se testean validaciones de entidades
- [ ] Se testa inmutabilidad

**Ejemplo**:
```python
def test_sale_aggregate_invalid_quantity():
    with pytest.raises(ValueError):
        SaleLineItem(item_id=1, quantity=0, ...)
```

---

## 📋 D. DESACOPLAMIENTO DE MODELOS

### D1. Store → Transactions 🔴
- [ ] `transactions/models.py` NO importa de `store.models`
- [ ] Si lo hace, SOLO a través de ForeignKey (aceptable)

**Validación**:
```bash
grep -n "from store.models import" transactions/models.py
# ❌ Si encuentra algo, hay acoplamiento
```

### D2. Transactions → Store 🔴
- [ ] `transactions/views.py` NO importa `Item` directamente
- [ ] `transactions/services.py` NO importa `Item` directamente
- [ ] SOLO `repositories.py` importa de store

**Validación**:
```bash
# Buscar imports directos en vistas y servicios
grep -n "from store.models" transactions/views.py
grep -n "from store.models" transactions/services.py
# Ambos deberían retornar vacío
```

### D3. Cambio en Estructura de Item 🔴
- [ ] Se ha documentado qué cambiaría si Item tuviera múltiples almacenes
- [ ] Solo `repositories.py` necesitaría cambios
- [ ] Servicios y vistas permanecerían igual

**Validación**:
```markdown
# Crear documento CAMBIO_FUTURO.md que documente:
Si Item ahora tiene warehouse_id:
- Cambio en store/models.py ✓
- Cambio en transactions/repositories.py ✓
- ¿Cambio en services.py? ✗ NO
- ¿Cambio en views.py? ✗ NO
```

---

## 📝 E. AUDITORÍA Y LOGGING

### E1. Auditoría Centralizada ⚠️
- [ ] Existe `audit.py` con `AuditLogger`
- [ ] Se registra: SALE_CREATED, SALE_CANCELLED, SALE_FAILED
- [ ] Se incluye: timestamp, user_id, customer_id, sale_id, resultado

**Validación**:
```bash
# Buscar logs de una venta creada
tail -100 /var/log/django.log | grep "SALE_CREATED"
```

### E2. Intentos Fallidos Registrados ⚠️
- [ ] Se registran intentos fallidos de operaciones críticas
- [ ] Se registra la razón del fallo
- [ ] Se puede auditar intentos no autorizados

---

## 📦 F. VISTAS REFACTORIZADAS

### F1. Vistas Delgadas 🔴
- [ ] `SaleCreateView`: < 40 líneas
- [ ] Tiene MÁXIMO 3 responsabilidades: parsear HTTP, llamar servicio, responder
- [ ] NO tiene validaciones de negocio
- [ ] NO accede a BD directamente

**Validación**:
```bash
wc -l transactions/views.py  # Debería ser < 400 líneas total
# Antiguo: 366 líneas
# Nuevo: < 200 líneas esperado
```

### F2. Manejo de Errores Consistente 🔴
- [ ] Vistas atrapan excepciones de negocio
- [ ] Convierten a respuestas HTTP apropiadas (400, 401, 500)
- [ ] Usan los mismos códigos de error en web y API

---

## 🔐 G. SEGURIDAD Y AUTORIZACIÓN

### G1. Autorización Centralizada ⚠️
- [ ] Existe `authorization_service.py` (opcional pero recomendado)
- [ ] Se valida autorización DENTRO de servicios, no solo en vistas
- [ ] Mismo usuario no puede cancelar venta de otro

### G2. Sin Información Sensible en Logs 🔴
- [ ] No se loguean datos sensibles (contraseñas, nros de tarjeta)
- [ ] Se loguean IDs, no nombres de clientes

---

## 🚀 H. DOCUMENTACIÓN

### H1. README de Arquitectura ⚠️
- [ ] Existe documento explicando la arquitectura
- [ ] Se menciona: servicios, repositorios, dominio
- [ ] Se incluye diagrama (incluso ASCII art)

**Ejemplo**:
```
┌─────────────────────────────────┐
│       HTTP Request              │
│   (SaleCreateView)              │
└──────────┬──────────────────────┘
           │
           v
┌─────────────────────────────────┐
│    CreateSaleService            │
│   (Lógica de negocio)           │
└──────────┬──────────────────────┘
           │
      ┌────┴────┐
      v         v
┌──────────┐ ┌──────────┐
│Inventory │ │   Sale   │
│Repo      │ │Repo      │
└────┬─────┘ └────┬─────┘
     │            │
     v            v
┌─────────────────────────┐
│      Django ORM         │
│   (store, trans)        │
└─────────────────────────┘
```

### H2. Docstrings en Servicios ⚠️
- [ ] Cada servicio tiene docstring con: qué hace, args, returns, raises
- [ ] Docstrings en español o inglés, pero consistentes

---

## 🐳 I. CONTAINERIZACIÓN Y REPRODUCIBILIDAD

### I1. Dockerfile Optimizado ⚠️
- [ ] Dockerfile existe y funciona
- [ ] Se usa multi-stage build (si es posible)
- [ ] Las dependencias se instalan correctamente

**Validación**:
```bash
docker build -t inventario:latest .
docker run inventario:latest python manage.py test transactions
```

### I2. Docker Compose ⚠️
- [ ] Existe `docker-compose.yml`
- [ ] Se pueden levantar servicios con `docker-compose up`
- [ ] Se incluye base de datos (PostgreSQL o similar)

---

## 📊 J. MÉTRICAS TÉCNICAS

### Checklist de Números

Antes de refactorizar:
```
SaleCreateView: 115 líneas
Cobertura de tests: ~20%
Tests en BD: >30 segundos
Acoplamiento (store ↔ transactions): Directo
```

Después de refactorizar (Goals):
```
SaleCreateView: <40 líneas
Cobertura de tests: >80%
Tests unitarios: <2 segundos
Acoplamiento: A través de repositorio
```

---

## 🎯 RESUMEN DE EVALUACIÓN

### Críticos (Todos deben estar ✅)
- [ ] Existe capa de servicios
- [ ] Existe capa de repositorios
- [ ] Vistas NO acceden directamente a `Item`
- [ ] Transacciones son atómicas con `select_for_update()`
- [ ] Tests unitarios SIN BD

### Recomendados (Mínimo 70% ✅)
- [ ] Entidades de dominio
- [ ] Auditoría centralizada
- [ ] Tests de integración
- [ ] Documentación arquitectónica
- [ ] Docker funcional

### Opcionales (Nice to have)
- [ ] Servicio de autorización
- [ ] API REST reutilizando servicios
- [ ] Event sourcing para auditoría completa
- [ ] CQRS (Command Query Responsibility Segregation)

---

## 📋 Plantilla de Autoevaluación

Completa esta tabla después de implementar:

| Aspecto | Estado | Notas | Deadline |
|---------|--------|-------|----------|
| Servicios creados | ✅ | 2 servicios | Semana 1 |
| Repositorios creados | ✅ | 2 repos | Semana 1 |
| Vistas refactorizadas | ❌ | En progreso | Semana 2 |
| Tests unitarios | ✅ | 80% cobertura | Semana 2 |
| Auditoría | ⚠️ | Básica | Semana 3 |
| Documentación | ⚠️ | En progreso | Semana 3 |
| Dockerfile | ⚠️ | Pendiente | Semana 4 |

---

## 🔗 Validación Final

Ejecuta este script para validación automática:

```bash
#!/bin/bash

echo "=== VALIDACIÓN ARQUITECTÓNICA ==="

echo "1. Verificando imports en vistas..."
if grep -q "from store.models import Item" transactions/views.py; then
    echo "❌ FALLA: Item importado directamente en vistas"
else
    echo "✅ PASS: No hay imports directos de Item"
fi

echo "2. Verificando services.py existe..."
if [ -f transactions/services.py ]; then
    echo "✅ PASS: services.py existe"
else
    echo "❌ FALLA: services.py no existe"
fi

echo "3. Verificando repositories.py existe..."
if [ -f transactions/repositories.py ]; then
    echo "✅ PASS: repositories.py existe"
else
    echo "❌ FALLA: repositories.py no existe"
fi

echo "4. Ejecutando tests..."
python manage.py test transactions
if [ $? -eq 0 ]; then
    echo "✅ PASS: Todos los tests pasan"
else
    echo "❌ FALLA: Algunos tests fallan"
fi

echo "=== FIN VALIDACIÓN ==="
```

---

## 💡 Preguntas de Autoevaluación

Responde honestamente:

1. **¿Puedo crear una venta sin Django?**
   - Si la respuesta es NO, falta desacoplamiento
   
2. **¿Cuántos archivos debo cambiar si Item tiene warehouse_id?**
   - Respuesta correcta: 1-2 (solo repositories.py y models.py)
   - Si es >3, hay acoplamiento
   
3. **¿Cuánto tardan los tests unitarios?**
   - Aceptable: <2 segundos
   - Inaceptable: >10 segundos (probablemente acceden a BD)
   
4. **¿Puede un frontend distinto usar la misma lógica de servicios?**
   - Debe poder: web form, API REST, CLI, etc.
   
5. **¿Puedo rastrear quién cancela cada venta y cuándo?**
   - DEBE poder sin búsqueda manual en logs

---

## 📞 Próximo Paso

Cuando hayas completado este checklist:
1. Copia y pega tus respuestas
2. Comparte con el equipo
3. Usa como base para code review
4. Itera hasta que TODOS los críticos estén ✅
