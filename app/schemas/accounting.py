"""
Pydantic schemas for request validation and response serialisation.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator, model_validator

from app.models.accounting import AccountType, EntryType, TransactionStatus


# ─────────────────────────────────────────────
# Account Schemas
# ─────────────────────────────────────────────

class AccountCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=20, example="1000")
    name: str = Field(..., min_length=1, max_length=255, example="Cash and Cash Equivalents")
    account_type: AccountType
    description: Optional[str] = None
    parent_id: Optional[UUID] = None

    @validator("code")
    def code_alphanumeric(cls, v):
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Account code must be alphanumeric (hyphens and underscores allowed)")
        return v.upper()


class AccountResponse(BaseModel):
    id: UUID
    code: str
    name: str
    account_type: AccountType
    description: Optional[str]
    is_active: bool
    parent_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AccountBalanceResponse(BaseModel):
    account: AccountResponse
    debit_total: Decimal
    credit_total: Decimal
    balance: Decimal
    normal_balance: EntryType

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────
# Ledger Entry Schemas
# ─────────────────────────────────────────────

class LedgerEntryCreate(BaseModel):
    account_id: UUID
    entry_type: EntryType
    amount: Decimal = Field(..., gt=0, description="Must be positive; entry_type determines direction")
    description: Optional[str] = None


class LedgerEntryResponse(BaseModel):
    id: UUID
    account_id: UUID
    entry_type: EntryType
    amount: Decimal
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────
# Journal Entry Schemas
# ─────────────────────────────────────────────

class JournalEntryCreate(BaseModel):
    reference: str = Field(..., min_length=1, max_length=100, example="INV-2024-001")
    description: str = Field(..., min_length=1, example="Customer invoice payment received")
    transaction_date: datetime
    created_by: Optional[str] = None
    entries: List[LedgerEntryCreate] = Field(..., min_items=2)

    @model_validator(mode="after")
    def validate_double_entry(self):
        entries = self.entries
        if len(entries) < 2:
            raise ValueError("A journal entry must have at least 2 ledger lines")

        total_debits = sum(e.amount for e in entries if e.entry_type == EntryType.DEBIT)
        total_credits = sum(e.amount for e in entries if e.entry_type == EntryType.CREDIT)

        if total_debits == 0:
            raise ValueError("Journal entry must have at least one DEBIT entry")
        if total_credits == 0:
            raise ValueError("Journal entry must have at least one CREDIT entry")
        if round(total_debits, 4) != round(total_credits, 4):
            raise ValueError(
                f"Journal entry does not balance: "
                f"debits={total_debits}, credits={total_credits}. "
                f"Difference={abs(total_debits - total_credits)}"
            )
        return self


class JournalEntryResponse(BaseModel):
    id: UUID
    reference: str
    description: str
    status: TransactionStatus
    transaction_date: datetime
    posted_at: Optional[datetime]
    voided_at: Optional[datetime]
    void_reason: Optional[str]
    created_by: Optional[str]
    created_at: datetime
    ledger_entries: List[LedgerEntryResponse]

    class Config:
        from_attributes = True


class VoidRequest(BaseModel):
    reason: str = Field(..., min_length=5, example="Duplicate transaction - correct entry is REF-002")
    voided_by: Optional[str] = None


# ─────────────────────────────────────────────
# Report Schemas
# ─────────────────────────────────────────────

class TrialBalanceRow(BaseModel):
    account_code: str
    account_name: str
    account_type: AccountType
    debit_total: Decimal
    credit_total: Decimal
    balance: Decimal

class TrialBalanceResponse(BaseModel):
    as_of_date: datetime
    rows: List[TrialBalanceRow]
    total_debits: Decimal
    total_credits: Decimal
    is_balanced: bool


class ReconciliationIssue(BaseModel):
    journal_entry_id: UUID
    reference: str
    description: str
    total_debits: Decimal
    total_credits: Decimal
    difference: Decimal


class ReconciliationResponse(BaseModel):
    checked_at: datetime
    total_entries_checked: int
    issues_found: int
    issues: List[ReconciliationIssue]
    is_clean: bool


class AuditLogResponse(BaseModel):
    id: UUID
    entity_type: str
    entity_id: UUID
    action: str
    performed_by: Optional[str]
    details: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    total_pages: int
