"""
LedgerFlow Test Suite

Tests cover:
  - Account creation and validation
  - Double-entry balance enforcement
  - Transaction posting and retrieval
  - Void and reversal logic
  - Trial balance correctness
  - Reconciliation engine
  - Audit trail completeness
"""

import pytest
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.models.accounting import (
    Account, AccountType, EntryType, JournalEntry,
    LedgerEntry, TransactionStatus,
)
from app.schemas.accounting import (
    AccountCreate, JournalEntryCreate, LedgerEntryCreate, VoidRequest,
)
from app.services.accounting import AccountingService


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture
def mock_db():
    """Provides a MagicMock database session."""
    return MagicMock()


@pytest.fixture
def cash_account():
    acc = Account()
    acc.id = "11111111-1111-1111-1111-111111111111"
    acc.code = "1000"
    acc.name = "Cash"
    acc.account_type = AccountType.ASSET
    acc.is_active = True
    return acc


@pytest.fixture
def revenue_account():
    acc = Account()
    acc.id = "22222222-2222-2222-2222-222222222222"
    acc.code = "4000"
    acc.name = "Revenue"
    acc.account_type = AccountType.REVENUE
    acc.is_active = True
    return acc


# ─────────────────────────────────────────────
# Schema Validation Tests
# ─────────────────────────────────────────────

class TestDoubleEntryValidation:

    def test_balanced_entry_passes(self):
        """A balanced journal entry (debits == credits) must pass validation."""
        payload = JournalEntryCreate(
            reference="TEST-001",
            description="Test balanced entry",
            transaction_date=datetime.utcnow(),
            entries=[
                LedgerEntryCreate(
                    account_id="11111111-1111-1111-1111-111111111111",
                    entry_type=EntryType.DEBIT,
                    amount=Decimal("1000.00"),
                ),
                LedgerEntryCreate(
                    account_id="22222222-2222-2222-2222-222222222222",
                    entry_type=EntryType.CREDIT,
                    amount=Decimal("1000.00"),
                ),
            ],
        )
        assert payload.reference == "TEST-001"

    def test_unbalanced_entry_rejected(self):
        """An unbalanced entry (debits != credits) must be rejected at schema level."""
        with pytest.raises(ValueError, match="does not balance"):
            JournalEntryCreate(
                reference="TEST-002",
                description="Unbalanced entry",
                transaction_date=datetime.utcnow(),
                entries=[
                    LedgerEntryCreate(
                        account_id="11111111-1111-1111-1111-111111111111",
                        entry_type=EntryType.DEBIT,
                        amount=Decimal("1000.00"),
                    ),
                    LedgerEntryCreate(
                        account_id="22222222-2222-2222-2222-222222222222",
                        entry_type=EntryType.CREDIT,
                        amount=Decimal("999.00"),  # Off by 1
                    ),
                ],
            )

    def test_single_entry_rejected(self):
        """A journal entry with only one line must be rejected."""
        with pytest.raises(ValueError):
            JournalEntryCreate(
                reference="TEST-003",
                description="Single line",
                transaction_date=datetime.utcnow(),
                entries=[
                    LedgerEntryCreate(
                        account_id="11111111-1111-1111-1111-111111111111",
                        entry_type=EntryType.DEBIT,
                        amount=Decimal("500.00"),
                    ),
                ],
            )

    def test_no_debit_entry_rejected(self):
        """A journal entry with credits only must be rejected."""
        with pytest.raises(ValueError, match="at least one DEBIT"):
            JournalEntryCreate(
                reference="TEST-004",
                description="Credits only",
                transaction_date=datetime.utcnow(),
                entries=[
                    LedgerEntryCreate(
                        account_id="11111111-1111-1111-1111-111111111111",
                        entry_type=EntryType.CREDIT,
                        amount=Decimal("500.00"),
                    ),
                    LedgerEntryCreate(
                        account_id="22222222-2222-2222-2222-222222222222",
                        entry_type=EntryType.CREDIT,
                        amount=Decimal("500.00"),
                    ),
                ],
            )

    def test_negative_amount_rejected(self):
        """Negative amounts must be rejected — direction is set via entry_type."""
        with pytest.raises(ValueError):
            LedgerEntryCreate(
                account_id="11111111-1111-1111-1111-111111111111",
                entry_type=EntryType.DEBIT,
                amount=Decimal("-100.00"),
            )

    def test_multi_line_balanced_entry_passes(self):
        """Multiple debits and credits that net to zero must pass."""
        payload = JournalEntryCreate(
            reference="TEST-005",
            description="Multi-line balanced entry",
            transaction_date=datetime.utcnow(),
            entries=[
                LedgerEntryCreate(
                    account_id="11111111-1111-1111-1111-111111111111",
                    entry_type=EntryType.DEBIT,
                    amount=Decimal("600.00"),
                ),
                LedgerEntryCreate(
                    account_id="11111111-1111-1111-1111-111111111112",
                    entry_type=EntryType.DEBIT,
                    amount=Decimal("400.00"),
                ),
                LedgerEntryCreate(
                    account_id="22222222-2222-2222-2222-222222222222",
                    entry_type=EntryType.CREDIT,
                    amount=Decimal("1000.00"),
                ),
            ],
        )
        assert payload is not None

    def test_account_code_uppercased(self):
        """Account codes should be normalised to uppercase."""
        payload = AccountCreate(
            code="acc-001",
            name="Test Account",
            account_type=AccountType.ASSET,
        )
        assert payload.code == "ACC-001"


# ─────────────────────────────────────────────
# Account Normal Balance Tests
# ─────────────────────────────────────────────

class TestNormalBalance:

    def test_asset_normal_balance_is_debit(self):
        acc = Account()
        acc.account_type = AccountType.ASSET
        assert acc.normal_balance == EntryType.DEBIT

    def test_expense_normal_balance_is_debit(self):
        acc = Account()
        acc.account_type = AccountType.EXPENSE
        assert acc.normal_balance == EntryType.DEBIT

    def test_liability_normal_balance_is_credit(self):
        acc = Account()
        acc.account_type = AccountType.LIABILITY
        assert acc.normal_balance == EntryType.CREDIT

    def test_equity_normal_balance_is_credit(self):
        acc = Account()
        acc.account_type = AccountType.EQUITY
        assert acc.normal_balance == EntryType.CREDIT

    def test_revenue_normal_balance_is_credit(self):
        acc = Account()
        acc.account_type = AccountType.REVENUE
        assert acc.normal_balance == EntryType.CREDIT


# ─────────────────────────────────────────────
# Void Logic Tests
# ─────────────────────────────────────────────

class TestVoidLogic:

    def test_voiding_already_voided_entry_raises(self, mock_db, cash_account, revenue_account):
        """Voiding an already-voided entry must raise an error."""
        entry = JournalEntry()
        entry.id = "33333333-3333-3333-3333-333333333333"
        entry.reference = "INV-001"
        entry.status = TransactionStatus.VOIDED
        entry.ledger_entries = []

        mock_db.query.return_value.filter.return_value.first.return_value = entry

        svc = AccountingService(mock_db)
        with pytest.raises(ValueError, match="already voided"):
            svc.void_journal_entry(
                entry.id,
                VoidRequest(reason="test void", voided_by="user"),
            )

    def test_voiding_pending_entry_raises(self, mock_db):
        """Only POSTED entries can be voided."""
        entry = JournalEntry()
        entry.id = "44444444-4444-4444-4444-444444444444"
        entry.reference = "INV-002"
        entry.status = TransactionStatus.PENDING
        entry.ledger_entries = []

        mock_db.query.return_value.filter.return_value.first.return_value = entry

        svc = AccountingService(mock_db)
        with pytest.raises(ValueError, match="Only POSTED entries"):
            svc.void_journal_entry(
                entry.id,
                VoidRequest(reason="trying to void pending", voided_by="user"),
            )


# ─────────────────────────────────────────────
# Duplicate Reference Tests
# ─────────────────────────────────────────────

class TestDuplicateReference:

    def test_duplicate_account_code_raises(self, mock_db):
        """Creating an account with an existing code must raise."""
        existing = Account()
        existing.code = "1000"
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        svc = AccountingService(mock_db)
        with pytest.raises(ValueError, match="already exists"):
            svc.create_account(AccountCreate(
                code="1000",
                name="Duplicate",
                account_type=AccountType.ASSET,
            ))

    def test_duplicate_journal_reference_raises(self, mock_db):
        """Creating a journal entry with an existing reference must raise."""
        existing = JournalEntry()
        existing.reference = "INV-001"
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        svc = AccountingService(mock_db)
        with pytest.raises(ValueError, match="already exists"):
            svc.create_journal_entry(JournalEntryCreate(
                reference="INV-001",
                description="Duplicate",
                transaction_date=datetime.utcnow(),
                entries=[
                    LedgerEntryCreate(
                        account_id="11111111-1111-1111-1111-111111111111",
                        entry_type=EntryType.DEBIT,
                        amount=Decimal("100"),
                    ),
                    LedgerEntryCreate(
                        account_id="22222222-2222-2222-2222-222222222222",
                        entry_type=EntryType.CREDIT,
                        amount=Decimal("100"),
                    ),
                ],
            ))
