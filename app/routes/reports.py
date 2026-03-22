"""Reports endpoints — trial balance, reconciliation, audit logs."""

import math
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.accounting import (
    AuditLogResponse,
    ReconciliationResponse,
    TrialBalanceResponse,
)
from app.services.accounting import AccountingService

router = APIRouter()


@router.get("/trial-balance", response_model=TrialBalanceResponse)
def trial_balance(
    as_of: Optional[datetime] = Query(None, description="Point-in-time for the report (defaults to now)"),
    db: Session = Depends(get_db),
):
    """
    Generate a trial balance report.

    A healthy ledger will always have is_balanced=true.
    If is_balanced=false, the reconciliation endpoint will identify which entries are at fault.
    """
    return AccountingService(db).trial_balance(as_of=as_of)


@router.get("/reconciliation", response_model=ReconciliationResponse)
def reconciliation(db: Session = Depends(get_db)):
    """
    Run a full ledger reconciliation check.

    Scans every POSTED journal entry and verifies that debits == credits.
    Returns a list of any entries that fail this check.
    In a healthy system, issues_found will always be 0.
    """
    return AccountingService(db).reconcile()


@router.get("/audit-logs", response_model=dict)
def audit_logs(
    entity_type: Optional[str] = None,
    entity_id: Optional[UUID] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """
    Retrieve the immutable audit trail.

    Every account creation, transaction posting, and void operation
    is recorded here. Audit log records are never deleted or modified.
    """
    items, total = AccountingService(db).get_audit_logs(
        entity_type=entity_type, entity_id=entity_id, page=page, page_size=page_size
    )
    return {
        "items": [AuditLogResponse.model_validate(i) for i in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size),
    }
