# LedgerFlow

**A transactionally correct double-entry accounting engine with ACID guarantees, immutable audit trail, and automated reconciliation.**

[![CI](https://github.com/yourusername/ledgerflow/actions/workflows/ci.yml/badge.svg)](https://github.com/yourusername/ledgerflow/actions)
[![Python](https://img.shields.io/badge/python-3.11-blue.svg)](https://python.org)
[![PostgreSQL](https://img.shields.io/badge/postgresql-15-336791.svg)](https://postgresql.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## What is this?

LedgerFlow implements the **double-entry bookkeeping model** from first principles — the same accounting model that underpins every bank, financial institution, and ERP system in the world.

In double-entry accounting, every transaction has two sides that must always balance:

```
Debit  Cash (Asset)          +$45,000
Credit Service Revenue       +$45,000
─────────────────────────────────────
Net effect on equation:       balanced ✓
```

This constraint — that debits must always equal credits — is enforced at three independent layers in this system:

1. **Pydantic schema validation** — rejects unbalanced requests before they reach the service layer
2. **Service layer assertion** — re-validates after building the ledger lines, before committing
3. **Database constraint** — `CHECK (amount > 0)` ensures no zero or negative line items ever reach the DB

If all three layers are somehow bypassed, the reconciliation endpoint will detect the discrepancy.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   HTTP Clients                   │
│         (REST API / curl / Postman)              │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│              FastAPI Application                  │
│                                                   │
│  /api/accounts      → AccountsRouter             │
│  /api/transactions  → TransactionsRouter         │
│  /api/reports       → ReportsRouter              │
│  /api/health        → HealthRouter               │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│             AccountingService                     │
│                                                   │
│  create_account()          list_accounts()        │
│  create_journal_entry()    void_journal_entry()   │
│  get_account_balance()     trial_balance()        │
│  reconcile()               get_audit_logs()       │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│           PostgreSQL (via SQLAlchemy)             │
│                                                   │
│  accounts          journal_entries                │
│  ledger_entries    audit_logs                     │
└─────────────────────────────────────────────────┘
```

---

## Data Model

### The four tables

| Table | Purpose |
|---|---|
| `accounts` | Chart of accounts. Each account has a type (Asset, Liability, Equity, Revenue, Expense) that defines its normal balance direction. |
| `journal_entries` | The top-level transaction record. Immutable once posted. Supports PENDING → POSTED → VOIDED transitions. |
| `ledger_entries` | Individual debit or credit lines belonging to a journal entry. Amount is always positive; direction is set via `entry_type`. |
| `audit_logs` | Append-only log of every create, post, and void operation. Rows are never modified or deleted. |

### Account types and normal balances

| Account Type | Normal Balance | Increased by | Decreased by |
|---|---|---|---|
| Asset | Debit | Debit | Credit |
| Expense | Debit | Debit | Credit |
| Liability | Credit | Credit | Debit |
| Equity | Credit | Credit | Debit |
| Revenue | Credit | Credit | Debit |

This follows the **accounting equation**: `Assets = Liabilities + Equity`

---

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development without Docker)

### Run with Docker (recommended)

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/ledgerflow.git
cd ledgerflow

# 2. Copy environment config
cp .env.example .env

# 3. Start the database and API
docker compose up --build

# 4. In a separate terminal, run migrations and seed data
docker compose exec api alembic upgrade head
docker compose exec api python scripts/seed.py
```

The API is now running at **http://localhost:8000**

- Interactive API docs: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc
- Health check: http://localhost:8000/api/health

### Run locally (without Docker)

```bash
# 1. Create a virtual environment
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up environment
cp .env.example .env
# Edit .env with your PostgreSQL connection string

# 4. Run migrations
alembic upgrade head

# 5. Seed sample data
python scripts/seed.py

# 6. Start the server
uvicorn app.main:app --reload
```

---

## API Reference

### Accounts

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/accounts/` | Create a new account |
| `GET` | `/api/accounts/` | List all accounts |
| `GET` | `/api/accounts/{id}` | Get account by ID |
| `GET` | `/api/accounts/{id}/balance` | Get current account balance |

**Create an account:**
```bash
curl -X POST http://localhost:8000/api/accounts/ \
  -H "Content-Type: application/json" \
  -d '{
    "code": "1000",
    "name": "Cash and Cash Equivalents",
    "account_type": "ASSET"
  }'
```

---

### Transactions (Journal Entries)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/transactions/` | Post a new journal entry |
| `GET` | `/api/transactions/` | List entries (filterable by status, date range) |
| `GET` | `/api/transactions/{id}` | Get a single entry with all ledger lines |
| `POST` | `/api/transactions/{id}/void` | Void a posted entry (creates reversal) |

**Post a journal entry (cash sale):**
```bash
curl -X POST http://localhost:8000/api/transactions/ \
  -H "Content-Type: application/json" \
  -d '{
    "reference": "INV-2024-001",
    "description": "Cash sale to Acme Corp",
    "transaction_date": "2024-01-15T10:00:00Z",
    "created_by": "finance@company.com",
    "entries": [
      {
        "account_id": "<cash-account-uuid>",
        "entry_type": "DEBIT",
        "amount": "10000.00",
        "description": "Cash received"
      },
      {
        "account_id": "<revenue-account-uuid>",
        "entry_type": "CREDIT",
        "amount": "10000.00",
        "description": "Service revenue recognised"
      }
    ]
  }'
```

**What happens if the entry doesn't balance?**
```json
{
  "error": "Journal entry does not balance: debits=10000.00, credits=9999.00. Difference=1.00"
}
```

**Void an entry:**
```bash
curl -X POST http://localhost:8000/api/transactions/{id}/void \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Duplicate transaction — correct entry is INV-2024-002",
    "voided_by": "finance@company.com"
  }'
```

Voiding creates a new reversal entry (`VOID-INV-2024-001`) with debits and credits swapped, and marks the original as `VOIDED`. Nothing is deleted.

---

### Reports

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/reports/trial-balance` | Trial balance across all accounts |
| `GET` | `/api/reports/reconciliation` | Scan all entries for imbalances |
| `GET` | `/api/reports/audit-logs` | Full audit trail (filterable) |

**Trial balance:**
```bash
curl http://localhost:8000/api/reports/trial-balance
```

```json
{
  "as_of_date": "2024-01-31T00:00:00",
  "rows": [
    {
      "account_code": "1000",
      "account_name": "Cash and Cash Equivalents",
      "account_type": "ASSET",
      "debit_total": "510000.0000",
      "credit_total": "35000.0000",
      "balance": "475000.0000"
    },
    ...
  ],
  "total_debits": "708000.0000",
  "total_credits": "708000.0000",
  "is_balanced": true
}
```

`is_balanced: true` means every posted transaction in the system is correct. If this is ever `false`, the reconciliation endpoint identifies which entries are responsible.

---

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage report
pytest tests/ -v --cov=app --cov-report=term-missing

# Run a specific test class
pytest tests/test_accounting.py::TestDoubleEntryValidation -v
```

**Test coverage includes:**
- Balanced entry validation passes
- Unbalanced entry (debits ≠ credits) is rejected with a clear error
- Single-line entry (no counterpart) is rejected
- Credits-only or debits-only entry is rejected
- Negative amounts are rejected
- Multi-line complex entries that balance are accepted
- Account code normalisation (lowercase → uppercase)
- Normal balance direction for all 5 account types
- Voiding an already-voided entry raises an error
- Voiding a PENDING (not yet posted) entry raises an error
- Duplicate account code raises an error
- Duplicate journal entry reference raises an error

---

## Key Design Decisions

### Why PostgreSQL?
Financial data requires ACID transactions. Every journal entry write either completes entirely or rolls back entirely — there is no partial success. PostgreSQL's transaction model guarantees this at the database level, independent of the application code.

### Why is amount always positive?
In double-entry accounting, a negative debit is logically equivalent to a credit. Allowing negative amounts introduces ambiguity. This system forces the direction to be explicit (`entry_type: DEBIT` or `CREDIT`) and requires the amount to always be positive. The database enforces this with a `CHECK (amount > 0)` constraint.

### Why is voiding a reversal, not a deletion?
Deleting financial records is not acceptable in any regulated or audited environment. When an entry is voided, the system:
1. Marks the original entry as `VOIDED` with a timestamp and reason
2. Creates a new reversal entry (`VOID-{reference}`) with all debits and credits swapped
3. The net effect on all account balances returns to zero

The original transaction, the void, and the reversal are all permanently visible in the audit log.

### Why validate balance at three layers?
Defense in depth. The Pydantic schema catches malformed requests instantly. The service layer catches any edge case the schema misses. The reconciliation endpoint can detect any discrepancy that somehow reached the database. In a production financial system, you want every layer to be independently correct.

---

## Project Structure

```
ledgerflow/
├── app/
│   ├── main.py                  # FastAPI app, middleware, router registration
│   ├── core/
│   │   ├── config.py            # Pydantic settings (reads from .env)
│   │   └── database.py          # SQLAlchemy engine, session factory
│   ├── models/
│   │   └── accounting.py        # ORM models: Account, JournalEntry, LedgerEntry, AuditLog
│   ├── schemas/
│   │   └── accounting.py        # Pydantic request/response schemas + balance validation
│   ├── services/
│   │   └── accounting.py        # All business logic: create, post, void, balance, reconcile
│   └── routes/
│       ├── accounts.py          # GET/POST /api/accounts/
│       ├── transactions.py      # GET/POST /api/transactions/
│       ├── reports.py           # GET /api/reports/
│       └── health.py            # GET /api/health
├── migrations/
│   ├── env.py                   # Alembic environment config
│   └── versions/
│       └── 001_initial.py       # Initial schema migration
├── tests/
│   └── test_accounting.py       # Unit tests for all core invariants
├── scripts/
│   └── seed.py                  # Loads chart of accounts + sample transactions
├── .github/
│   └── workflows/
│       └── ci.yml               # GitHub Actions: test + lint on every push
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── alembic.ini
└── .env.example
```

---

## Concepts Demonstrated

| Concept | Where |
|---|---|
| Double-entry bookkeeping invariant | `app/schemas/accounting.py` → `validate_double_entry` |
| ACID transaction safety | `app/core/database.py`, `app/services/accounting.py` |
| Immutable audit trail | `app/models/accounting.py` → `AuditLog` |
| Soft-delete via reversal (void pattern) | `app/services/accounting.py` → `void_journal_entry` |
| Defense-in-depth validation | Schema → Service → Reconciliation endpoint |
| Decimal precision for money | `Numeric(precision=20, scale=4)` — never float |
| Database migrations | `migrations/versions/001_initial.py` |
| Paginated API responses | `GET /api/transactions/` |
| CI/CD pipeline | `.github/workflows/ci.yml` |

---

## License

MIT — see [LICENSE](LICENSE) for details.
