"""Accounts endpoints — chart of accounts management."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.accounting import AccountCreate, AccountBalanceResponse, AccountResponse
from app.services.accounting import AccountingService

router = APIRouter()


@router.post("/", response_model=AccountResponse, status_code=201)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    """Create a new account in the chart of accounts."""
    return AccountingService(db).create_account(payload)


@router.get("/", response_model=list[AccountResponse])
def list_accounts(
    active_only: bool = Query(True, description="Filter to active accounts only"),
    db: Session = Depends(get_db),
):
    """List all accounts."""
    return AccountingService(db).list_accounts(active_only=active_only)


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(account_id: UUID, db: Session = Depends(get_db)):
    """Get a single account by ID."""
    return AccountingService(db).get_account(account_id)


@router.get("/{account_id}/balance", response_model=AccountBalanceResponse)
def get_account_balance(account_id: UUID, db: Session = Depends(get_db)):
    """Get the current balance of an account (based on all POSTED entries)."""
    svc = AccountingService(db)
    account = svc.get_account(account_id)
    debit_total, credit_total, balance = svc.get_account_balance(account_id)
    return AccountBalanceResponse(
        account=account,
        debit_total=debit_total,
        credit_total=credit_total,
        balance=balance,
        normal_balance=account.normal_balance,
    )
