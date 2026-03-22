"""
Core accounting models.

Double-entry bookkeeping requires that every transaction has:
  - At least one DEBIT entry
  - At least one CREDIT entry
  - Total debits == Total credits (the accounting equation)

This is enforced at both the application and database level.
"""

import uuid
from decimal import Decimal
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Column, String, Numeric, DateTime, ForeignKey,
    Enum as SAEnum, Text, Boolean, Index, CheckConstraint, event
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class AccountType(str, Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class EntryType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class Account(Base):
    """
    Chart of Accounts entry.
    Each account has a type that determines how debits/credits affect its balance.

    Normal balance rules (double-entry):
      ASSET, EXPENSE     → increased by DEBIT,  decreased by CREDIT
      LIABILITY, EQUITY, REVENUE → increased by CREDIT, decreased by DEBIT
    """
    __tablename__ = "accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    account_type = Column(SAEnum(AccountType), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    parent = relationship("Account", remote_side=[id], backref="children")
    ledger_entries = relationship("LedgerEntry", back_populates="account")

    def __repr__(self):
        return f"<Account {self.code}: {self.name} ({self.account_type})>"

    @property
    def normal_balance(self) -> EntryType:
        """Returns the entry type that increases this account's balance."""
        if self.account_type in (AccountType.ASSET, AccountType.EXPENSE):
            return EntryType.DEBIT
        return EntryType.CREDIT


class JournalEntry(Base):
    """
    A journal entry is the top-level transaction record.
    It groups one or more LedgerEntries that together must balance.

    Immutability: Posted entries cannot be modified — only voided.
    Every void creates a reversal entry (audit trail).
    """
    __tablename__ = "journal_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=False)
    status = Column(
        SAEnum(TransactionStatus),
        nullable=False,
        default=TransactionStatus.PENDING,
    )
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    posted_at = Column(DateTime(timezone=True), nullable=True)
    voided_at = Column(DateTime(timezone=True), nullable=True)
    void_reason = Column(Text, nullable=True)

    # Metadata
    created_by = Column(String(255), nullable=True)
    metadata_ = Column("metadata", Text, nullable=True)   # JSON blob for extra context

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationship
    ledger_entries = relationship(
        "LedgerEntry",
        back_populates="journal_entry",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_journal_entries_transaction_date", "transaction_date"),
        Index("ix_journal_entries_status", "status"),
    )

    def __repr__(self):
        return f"<JournalEntry {self.reference} [{self.status}]>"


class LedgerEntry(Base):
    """
    A single line in a journal entry — either a DEBIT or a CREDIT
    against a specific account for a specific amount.

    The sum of all DEBIT amounts must equal the sum of all CREDIT amounts
    within a single JournalEntry. This is validated in the service layer
    before posting.
    """
    __tablename__ = "ledger_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    journal_entry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id"),
        nullable=False,
        index=True,
    )
    entry_type = Column(SAEnum(EntryType), nullable=False)
    amount = Column(Numeric(precision=20, scale=4), nullable=False)
    description = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    journal_entry = relationship("JournalEntry", back_populates="ledger_entries")
    account = relationship("Account", back_populates="ledger_entries")

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_ledger_entries_positive_amount"),
    )

    def __repr__(self):
        return f"<LedgerEntry {self.entry_type} {self.amount} on account {self.account_id}>"


class AuditLog(Base):
    """
    Immutable audit trail.
    Every create, update, and void operation is recorded here.
    Rows in this table are NEVER deleted or modified.
    """
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    action = Column(String(50), nullable=False)       # CREATE, UPDATE, VOID, POST
    performed_by = Column(String(255), nullable=True)
    details = Column(Text, nullable=True)             # JSON snapshot
    ip_address = Column(String(45), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    def __repr__(self):
        return f"<AuditLog {self.action} on {self.entity_type}/{self.entity_id}>"
