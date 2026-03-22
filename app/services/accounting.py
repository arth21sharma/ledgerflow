"""
AccountingService — the core business logic layer.

All double-entry rules, balance validation, and posting logic lives here.
Routes delegate to this service; the service owns all database mutations.

Key invariants enforced:
  1. Every journal entry must balance (debits == credits)
  2. Posted entries are immutable — only voiding is allowed
  3. Every state change is recorded in the audit log
  4. All mutations happen inside a single database transaction
"""

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.models.accounting import (
    Account, AuditLog, EntryType, JournalEntry,
    LedgerEntry, TransactionStatus,
)
from app.schemas.accounting import (
    AccountCreate, JournalEntryCreate,
    ReconciliationIssue, TrialBalanceRow, VoidRequest,
)

logger = logging.getLogger(__name__)


class AccountingService:

    def __init__(self, db: Session):
        self.db = db

    # ─────────────────────────────────────────────
    # Accounts
    # ─────────────────────────────────────────────

    def create_account(self, payload: AccountCreate) -> Account:
        """Create a new account in the chart of accounts."""
        existing = self.db.query(Account).filter(Account.code == payload.code).first()
        if existing:
            raise ValueError(f"Account with code '{payload.code}' already exists")

        if payload.parent_id:
            parent = self.db.query(Account).filter(Account.id == payload.parent_id).first()
            if not parent:
                raise ValueError(f"Parent account {payload.parent_id} not found")

        account = Account(**payload.model_dump())
        self.db.add(account)
        self.db.flush()

        self._audit(
            entity_type="Account",
            entity_id=account.id,
            action="CREATE",
            details={"code": account.code, "name": account.name, "type": account.account_type},
        )

        self.db.commit()
        self.db.refresh(account)
        logger.info(f"Created account {account.code}: {account.name}")
        return account

    def get_account(self, account_id: UUID) -> Account:
        account = self.db.query(Account).filter(Account.id == account_id).first()
        if not account:
            raise ValueError(f"Account {account_id} not found")
        return account

    def list_accounts(self, active_only: bool = True) -> List[Account]:
        q = self.db.query(Account)
        if active_only:
            q = q.filter(Account.is_active == True)
        return q.order_by(Account.code).all()

    def get_account_balance(self, account_id: UUID) -> Tuple[Decimal, Decimal, Decimal]:
        """
        Returns (debit_total, credit_total, balance) for an account.
        Balance is computed according to the account's normal balance type.
        """
        account = self.get_account(account_id)

        result = (
            self.db.query(
                func.coalesce(
                    func.sum(case((LedgerEntry.entry_type == EntryType.DEBIT, LedgerEntry.amount), else_=0)),
                    Decimal("0"),
                ).label("debits"),
                func.coalesce(
                    func.sum(case((LedgerEntry.entry_type == EntryType.CREDIT, LedgerEntry.amount), else_=0)),
                    Decimal("0"),
                ).label("credits"),
            )
            .join(JournalEntry, LedgerEntry.journal_entry_id == JournalEntry.id)
            .filter(
                LedgerEntry.account_id == account_id,
                JournalEntry.status == TransactionStatus.POSTED,
            )
            .one()
        )

        debit_total = result.debits or Decimal("0")
        credit_total = result.credits or Decimal("0")

        if account.normal_balance == EntryType.DEBIT:
            balance = debit_total - credit_total
        else:
            balance = credit_total - debit_total

        return debit_total, credit_total, balance

    # ─────────────────────────────────────────────
    # Journal Entries
    # ─────────────────────────────────────────────

    def create_journal_entry(self, payload: JournalEntryCreate) -> JournalEntry:
        """
        Creates and immediately posts a balanced journal entry.

        Validation steps (all must pass before any DB write):
          1. Reference must be unique
          2. All accounts must exist and be active
          3. Total debits must equal total credits (enforced by schema + here)
        """
        # Uniqueness check
        existing = self.db.query(JournalEntry).filter(
            JournalEntry.reference == payload.reference
        ).first()
        if existing:
            raise ValueError(f"Journal entry with reference '{payload.reference}' already exists")

        # Validate all accounts exist and are active
        account_ids = {e.account_id for e in payload.entries}
        accounts = self.db.query(Account).filter(Account.id.in_(account_ids)).all()
        found_ids = {a.id for a in accounts}
        missing = account_ids - found_ids
        if missing:
            raise ValueError(f"Account(s) not found: {missing}")
        inactive = {a.id for a in accounts if not a.is_active}
        if inactive:
            raise ValueError(f"Account(s) are inactive: {inactive}")

        # Build journal entry
        journal = JournalEntry(
            reference=payload.reference,
            description=payload.description,
            transaction_date=payload.transaction_date,
            created_by=payload.created_by,
            status=TransactionStatus.POSTED,
            posted_at=datetime.utcnow(),
        )
        self.db.add(journal)
        self.db.flush()

        # Build ledger lines
        for entry_data in payload.entries:
            entry = LedgerEntry(
                journal_entry_id=journal.id,
                account_id=entry_data.account_id,
                entry_type=entry_data.entry_type,
                amount=entry_data.amount,
                description=entry_data.description,
            )
            self.db.add(entry)

        self.db.flush()

        # Final balance assertion (belt-and-suspenders after schema validation)
        self._assert_entry_balances(journal.id)

        self._audit(
            entity_type="JournalEntry",
            entity_id=journal.id,
            action="POST",
            details={
                "reference": journal.reference,
                "description": journal.description,
                "lines": len(payload.entries),
            },
            performed_by=payload.created_by,
        )

        self.db.commit()
        self.db.refresh(journal)
        logger.info(f"Posted journal entry {journal.reference}")
        return journal

    def get_journal_entry(self, entry_id: UUID) -> JournalEntry:
        entry = self.db.query(JournalEntry).filter(JournalEntry.id == entry_id).first()
        if not entry:
            raise ValueError(f"Journal entry {entry_id} not found")
        return entry

    def list_journal_entries(
        self,
        status: Optional[TransactionStatus] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[JournalEntry], int]:
        q = self.db.query(JournalEntry)
        if status:
            q = q.filter(JournalEntry.status == status)
        if from_date:
            q = q.filter(JournalEntry.transaction_date >= from_date)
        if to_date:
            q = q.filter(JournalEntry.transaction_date <= to_date)

        total = q.count()
        items = (
            q.order_by(JournalEntry.transaction_date.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def void_journal_entry(self, entry_id: UUID, void_request: VoidRequest) -> JournalEntry:
        """
        Voids a posted journal entry.

        Voiding does NOT delete the entry — it creates a reversal
        (a new journal entry with debits and credits swapped) and marks
        the original as VOIDED. This preserves the full audit trail.
        """
        entry = self.get_journal_entry(entry_id)

        if entry.status == TransactionStatus.VOIDED:
            raise ValueError(f"Journal entry {entry.reference} is already voided")
        if entry.status != TransactionStatus.POSTED:
            raise ValueError(f"Only POSTED entries can be voided (current: {entry.status})")

        now = datetime.utcnow()
        entry.status = TransactionStatus.VOIDED
        entry.voided_at = now
        entry.void_reason = void_request.reason

        # Create the reversal entry
        reversal = JournalEntry(
            reference=f"VOID-{entry.reference}",
            description=f"Reversal of {entry.reference}: {void_request.reason}",
            transaction_date=now,
            status=TransactionStatus.POSTED,
            posted_at=now,
            created_by=void_request.voided_by,
        )
        self.db.add(reversal)
        self.db.flush()

        for original_line in entry.ledger_entries:
            reversal_type = (
                EntryType.CREDIT
                if original_line.entry_type == EntryType.DEBIT
                else EntryType.DEBIT
            )
            reversal_line = LedgerEntry(
                journal_entry_id=reversal.id,
                account_id=original_line.account_id,
                entry_type=reversal_type,
                amount=original_line.amount,
                description=f"Reversal: {original_line.description or ''}",
            )
            self.db.add(reversal_line)

        self._audit(
            entity_type="JournalEntry",
            entity_id=entry.id,
            action="VOID",
            details={"reason": void_request.reason, "reversal_reference": f"VOID-{entry.reference}"},
            performed_by=void_request.voided_by,
        )

        self.db.commit()
        self.db.refresh(entry)
        logger.info(f"Voided journal entry {entry.reference}")
        return entry

    # ─────────────────────────────────────────────
    # Reports
    # ─────────────────────────────────────────────

    def trial_balance(self, as_of: Optional[datetime] = None) -> dict:
        """
        Produces a trial balance report.
        If the ledger is correct, total_debits == total_credits.
        """
        as_of = as_of or datetime.utcnow()

        accounts = self.db.query(Account).filter(Account.is_active == True).order_by(Account.code).all()
        rows = []
        total_debits = Decimal("0")
        total_credits = Decimal("0")

        for account in accounts:
            d, c, balance = self.get_account_balance(account.id)
            if d == 0 and c == 0:
                continue
            rows.append(
                TrialBalanceRow(
                    account_code=account.code,
                    account_name=account.name,
                    account_type=account.account_type,
                    debit_total=d,
                    credit_total=c,
                    balance=balance,
                )
            )
            total_debits += d
            total_credits += c

        return {
            "as_of_date": as_of,
            "rows": rows,
            "total_debits": total_debits,
            "total_credits": total_credits,
            "is_balanced": round(total_debits, 4) == round(total_credits, 4),
        }

    def reconcile(self) -> dict:
        """
        Scans all POSTED journal entries and finds any that don't balance.
        Returns a reconciliation report with discrepancies.
        Should always return zero issues if the system is healthy.
        """
        entries = (
            self.db.query(JournalEntry)
            .filter(JournalEntry.status == TransactionStatus.POSTED)
            .all()
        )

        issues = []
        for entry in entries:
            debits = sum(
                l.amount for l in entry.ledger_entries if l.entry_type == EntryType.DEBIT
            )
            credits = sum(
                l.amount for l in entry.ledger_entries if l.entry_type == EntryType.CREDIT
            )
            if round(debits, 4) != round(credits, 4):
                issues.append(
                    ReconciliationIssue(
                        journal_entry_id=entry.id,
                        reference=entry.reference,
                        description=entry.description,
                        total_debits=debits,
                        total_credits=credits,
                        difference=abs(debits - credits),
                    )
                )

        return {
            "checked_at": datetime.utcnow(),
            "total_entries_checked": len(entries),
            "issues_found": len(issues),
            "issues": issues,
            "is_clean": len(issues) == 0,
        }

    def get_audit_logs(
        self,
        entity_type: Optional[str] = None,
        entity_id: Optional[UUID] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[AuditLog], int]:
        q = self.db.query(AuditLog)
        if entity_type:
            q = q.filter(AuditLog.entity_type == entity_type)
        if entity_id:
            q = q.filter(AuditLog.entity_id == entity_id)
        total = q.count()
        items = (
            q.order_by(AuditLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    # ─────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────

    def _assert_entry_balances(self, journal_entry_id: UUID):
        """
        Belt-and-suspenders check: re-query the DB to confirm balance.
        Raises immediately if anything is off — transaction will be rolled back.
        """
        result = (
            self.db.query(
                func.coalesce(
                    func.sum(case((LedgerEntry.entry_type == EntryType.DEBIT, LedgerEntry.amount), else_=0)),
                    Decimal("0"),
                ).label("debits"),
                func.coalesce(
                    func.sum(case((LedgerEntry.entry_type == EntryType.CREDIT, LedgerEntry.amount), else_=0)),
                    Decimal("0"),
                ).label("credits"),
            )
            .filter(LedgerEntry.journal_entry_id == journal_entry_id)
            .one()
        )
        if round(result.debits, 4) != round(result.credits, 4):
            raise ValueError(
                f"CRITICAL: Ledger imbalance detected after write. "
                f"Debits={result.debits}, Credits={result.credits}. "
                f"Transaction will be rolled back."
            )

    def _audit(self, entity_type: str, entity_id: UUID, action: str, details: dict = None, performed_by: str = None):
        log = AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            performed_by=performed_by,
            details=json.dumps(details) if details else None,
        )
        self.db.add(log)
