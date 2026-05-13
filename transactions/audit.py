"""
Auditoría de operaciones críticas de transacciones.
"""

import logging
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger(__name__)


class AuditLogger:
    """Registra eventos de transacciones para auditoría."""

    def log_sale_created(
        self,
        sale_id: int,
        customer_id: int,
        total: Decimal,
        user_id: int | None = None,
    ) -> None:
        logger.info(
            f"SALE_CREATED | sale_id={sale_id} | customer_id={customer_id} | "
            f"total={total} | user_id={user_id} | "
            f"timestamp={datetime.now().isoformat()}"
        )

    def log_sale_failed(
        self,
        customer_id: int | None,
        reason: str,
        user_id: int | None = None,
    ) -> None:
        logger.warning(
            f"SALE_FAILED | customer_id={customer_id} | reason={reason} | "
            f"user_id={user_id} | timestamp={datetime.now().isoformat()}"
        )

    def log_purchase_created(
        self,
        purchase_id: int,
        item_id: int,
        vendor_id: int,
        quantity: int,
        total_value: Decimal,
        user_id: int | None = None,
    ) -> None:
        logger.info(
            f"PURCHASE_CREATED | purchase_id={purchase_id} | "
            f"item_id={item_id} | vendor_id={vendor_id} | "
            f"quantity={quantity} | total_value={total_value} | "
            f"user_id={user_id} | timestamp={datetime.now().isoformat()}"
        )

    def log_purchase_failed(
        self,
        item_id: int | None,
        vendor_id: int | None,
        reason: str,
        user_id: int | None = None,
    ) -> None:
        logger.warning(
            f"PURCHASE_FAILED | item_id={item_id} | vendor_id={vendor_id} | "
            f"reason={reason} | user_id={user_id} | "
            f"timestamp={datetime.now().isoformat()}"
        )
