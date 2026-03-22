"""
Seed script — loads a realistic chart of accounts and sample transactions.
Run: python scripts/seed.py

Creates a standard chart of accounts and a few sample journal entries
so you can immediately explore the API with real data.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from decimal import Decimal

from app.core.database import SessionLocal
from app.models.accounting import Account, AccountType
from app.schemas.accounting import AccountCreate, JournalEntryCreate, LedgerEntryCreate
from app.models.accounting import EntryType
from app.services.accounting import AccountingService


CHART_OF_ACCOUNTS = [
    # Assets
    ("1000", "Cash and Cash Equivalents",    AccountType.ASSET),
    ("1100", "Accounts Receivable",          AccountType.ASSET),
    ("1200", "Inventory",                    AccountType.ASSET),
    ("1500", "Property, Plant & Equipment",  AccountType.ASSET),
    # Liabilities
    ("2000", "Accounts Payable",             AccountType.LIABILITY),
    ("2100", "Accrued Liabilities",          AccountType.LIABILITY),
    ("2500", "Long-term Debt",               AccountType.LIABILITY),
    # Equity
    ("3000", "Common Stock",                 AccountType.EQUITY),
    ("3100", "Retained Earnings",            AccountType.EQUITY),
    # Revenue
    ("4000", "Service Revenue",              AccountType.REVENUE),
    ("4100", "Product Revenue",              AccountType.REVENUE),
    # Expenses
    ("5000", "Cost of Goods Sold",           AccountType.EXPENSE),
    ("5100", "Salaries Expense",             AccountType.EXPENSE),
    ("5200", "Rent Expense",                 AccountType.EXPENSE),
    ("5300", "Utilities Expense",            AccountType.EXPENSE),
]


def seed():
    db = SessionLocal()
    svc = AccountingService(db)

    print("Creating chart of accounts...")
    account_map = {}
    for code, name, atype in CHART_OF_ACCOUNTS:
        existing = db.query(Account).filter(Account.code == code).first()
        if existing:
            account_map[code] = existing
            print(f"  ✓ {code} {name} (already exists)")
        else:
            acc = svc.create_account(AccountCreate(code=code, name=name, account_type=atype))
            account_map[code] = acc
            print(f"  + {code} {name}")

    print("\nCreating sample journal entries...")

    # 1. Owner invests capital
    svc.create_journal_entry(JournalEntryCreate(
        reference="JE-001",
        description="Owner equity investment — initial capitalisation",
        transaction_date=datetime.utcnow() - timedelta(days=30),
        created_by="seed_script",
        entries=[
            LedgerEntryCreate(account_id=account_map["1000"].id, entry_type=EntryType.DEBIT,  amount=Decimal("500000.00"), description="Cash received"),
            LedgerEntryCreate(account_id=account_map["3000"].id, entry_type=EntryType.CREDIT, amount=Decimal("500000.00"), description="Common stock issued"),
        ],
    ))
    print("  + JE-001: Owner investment $500,000")

    # 2. Purchase inventory on credit
    svc.create_journal_entry(JournalEntryCreate(
        reference="JE-002",
        description="Purchase of inventory on credit from supplier",
        transaction_date=datetime.utcnow() - timedelta(days=25),
        created_by="seed_script",
        entries=[
            LedgerEntryCreate(account_id=account_map["1200"].id, entry_type=EntryType.DEBIT,  amount=Decimal("80000.00")),
            LedgerEntryCreate(account_id=account_map["2000"].id, entry_type=EntryType.CREDIT, amount=Decimal("80000.00")),
        ],
    ))
    print("  + JE-002: Inventory purchase $80,000")

    # 3. Record a sale (revenue + COGS)
    svc.create_journal_entry(JournalEntryCreate(
        reference="JE-003",
        description="Product sale — invoice INV-2024-001",
        transaction_date=datetime.utcnow() - timedelta(days=20),
        created_by="seed_script",
        entries=[
            LedgerEntryCreate(account_id=account_map["1100"].id, entry_type=EntryType.DEBIT,  amount=Decimal("45000.00"), description="AR from client"),
            LedgerEntryCreate(account_id=account_map["4100"].id, entry_type=EntryType.CREDIT, amount=Decimal("45000.00"), description="Product revenue"),
        ],
    ))
    svc.create_journal_entry(JournalEntryCreate(
        reference="JE-004",
        description="COGS recognition for INV-2024-001",
        transaction_date=datetime.utcnow() - timedelta(days=20),
        created_by="seed_script",
        entries=[
            LedgerEntryCreate(account_id=account_map["5000"].id, entry_type=EntryType.DEBIT,  amount=Decimal("28000.00")),
            LedgerEntryCreate(account_id=account_map["1200"].id, entry_type=EntryType.CREDIT, amount=Decimal("28000.00")),
        ],
    ))
    print("  + JE-003/004: Sale $45,000 + COGS $28,000")

    # 4. Pay salaries
    svc.create_journal_entry(JournalEntryCreate(
        reference="JE-005",
        description="Monthly salary disbursement — January 2024",
        transaction_date=datetime.utcnow() - timedelta(days=10),
        created_by="seed_script",
        entries=[
            LedgerEntryCreate(account_id=account_map["5100"].id, entry_type=EntryType.DEBIT,  amount=Decimal("35000.00")),
            LedgerEntryCreate(account_id=account_map["1000"].id, entry_type=EntryType.CREDIT, amount=Decimal("35000.00")),
        ],
    ))
    print("  + JE-005: Salary payment $35,000")

    # 5. Collect receivable
    svc.create_journal_entry(JournalEntryCreate(
        reference="JE-006",
        description="Cash collected from client — INV-2024-001",
        transaction_date=datetime.utcnow() - timedelta(days=5),
        created_by="seed_script",
        entries=[
            LedgerEntryCreate(account_id=account_map["1000"].id, entry_type=EntryType.DEBIT,  amount=Decimal("45000.00")),
            LedgerEntryCreate(account_id=account_map["1100"].id, entry_type=EntryType.CREDIT, amount=Decimal("45000.00")),
        ],
    ))
    print("  + JE-006: Cash collected $45,000")

    db.close()
    print("\n✅ Seed complete. Visit http://localhost:8000/api/docs to explore the API.")


if __name__ == "__main__":
    seed()
