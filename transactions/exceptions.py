"""
Excepciones de dominio para transacciones.
Independientes de Django — expresan errores de negocio.
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


class InvalidPurchaseError(TransactionError):
    """Datos de compra inválidos."""
    pass


class UnauthorizedOperationError(TransactionError):
    """Usuario no autorizado para esta operación."""
    pass
