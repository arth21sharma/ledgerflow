"""Transactions endpoints — journal entry management."""

import math
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.accounting import TransactionStatus
from app.schemas.accounting import JournalEntryCreate, JournalEntryResponse, VoidRequest
from app.services.accounting import AccountingService

router = APIRouter()


@router.post("/", response_model=JournalEntryResponse, status_code=201)
def create_journal_entry(payload: JournalEntryCreate, db: Session = Depends(get_db)):
    """
    Create and post a balanced journal entry.

    The request body must include at least two ledger lines where
    total debits == total credits. Unbalanced entries are rejected with HTTP 400.
    """
    return AccountingService(db).create_journal_entry(payload)


@router.get("/", response_model=dict)
def list_journal_entries(
    status: Optional[TransactionStatus] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List journal entries with optional filters and pagination."""
    items, total = AccountingService(db).list_journal_entries(
        status=status, from_date=from_date, to_date=to_date, page=page, page_size=page_size
    )
    return {
        "items": [JournalEntryResponse.model_validate(i) for i in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size),
    }


@router.get("/{entry_id}", response_model=JournalEntryResponse)
def get_journal_entry(entry_id: UUID, db: Session = Depends(get_db)):
    """Get a single journal entry with all its ledger lines."""
    return AccountingService(db).get_journal_entry(entry_id)


@router.post("/{entry_id}/void", response_model=JournalEntryResponse)
def void_journal_entry(
    entry_id: UUID,
    void_request: VoidRequest,
    db: Session = Depends(get_db),
):
    """
    Void a posted journal entry.

    This creates a reversal entry (debits ↔ credits swapped) and marks
    the original as VOIDED. The original entry is never deleted.
    """
    return AccountingService(db).void_journal_entry(entry_id, void_request)
