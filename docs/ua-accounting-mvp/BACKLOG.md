# UA Accounting MVP — First Backlog

This backlog is ordered by dependency. Do not start regulatory breadth until the golden accounting cycle works.

## P0 — Compatibility shell

### Deliverable
A dedicated accountant-facing shell that does not require navigating standard ERPNext Desk.

### Required UI
- Sections: Головне, Довідники, Купівлі, Продажі, Банк і каса, Склад, Облік.
- Company selector.
- Accounting period selector.
- Dense journals/tables.
- Standard command bar: `Створити`, `Записати`, `Провести`, `Провести і закрити`, `Дт/Кт`.
- Posted/unposted state visible in every journal.

### Acceptance
An accountant can open the shell and identify where to find counterparties, purchases, sales, bank and reports without explanation.

## P0 — Counterparty compatibility adapter

### Problem
ERPNext separates Customer and Supplier. 1C/BAS users expect one `Контрагенти` directory.

### Deliverable
One compatibility record that can represent customer, supplier, or both and synchronizes the required ERPNext entities.

### Required fields
- Display name
- Legal name
- EDRPOU / tax ID
- VAT status
- Address
- Contacts
- Bank details
- Customer backend link
- Supplier backend link

### Acceptance
A counterparty is created once. Sales can use it as a customer and purchases can use the same record as a supplier without the accountant creating duplicates.

## P0 — Posting viewer (`Дт/Кт`)

### Deliverable
Reusable posting inspection panel for any posted compatibility document.

### Columns
- Date
- Debit
- Credit
- Amount
- Currency
- Counterparty
- Item
- Warehouse
- Source document

### Acceptance
For every posted purchase, sale, payment and manual operation, the accountant can inspect the resulting postings from one `Дт/Кт` action.

## P0 — Purchase workflow

### User path
`Купівлі → Надходження товарів/послуг → Створити → Записати → Провести → Дт/Кт`

### Acceptance
- Supplier/counterparty selectable from compatibility directory.
- Items and services supported.
- Warehouse quantities update where applicable.
- Payable balance updates.
- GL entries are inspectable.
- Reopening a posted document does not silently alter accounting state.

## P0 — Sales workflow

### User path
`Продажі → Реалізація товарів/послуг → Створити → Записати → Провести → Дт/Кт`

### Acceptance
- Customer/counterparty selectable from compatibility directory.
- Stock decreases where applicable.
- Receivable balance updates.
- Revenue/COGS postings reconcile.
- GL entries are inspectable.

## P0 — Bank workflow

### User path
`Банк і каса → Банківська виписка`

### Deliverable
A bank-statement-like journal over ERPNext Bank Transaction / Payment Entry capabilities.

### Acceptance
- Incoming payment can settle a receivable.
- Outgoing payment can settle a payable.
- Unmatched payment remains visible.
- The accountant can open source postings with `Дт/Кт`.

## P0 — ОСВ compatibility report

### Deliverable
Turnover balance report using familiar columns:

- Рахунок
- Сальдо на початок Дт
- Сальдо на початок Кт
- Оборот Дт
- Оборот Кт
- Сальдо на кінець Дт
- Сальдо на кінець Кт

### Acceptance
For the golden scenario, every account total ties to the underlying GL entries and the report can drill into account card details.

## P0 — Account card

### Deliverable
A familiar account-card view over General Ledger data.

### Acceptance
- Filter by account and period.
- Show source document, debit/credit counterpart account, amount and running balance.
- Click through to source document.

## P0 — Golden accounting scenario

Create an automated and manually reproducible test scenario:

1. Opening cash/bank balance: UAH 100,000.
2. Purchase 10 units at UAH 1,000 net each.
3. Record supplier payable.
4. Pay supplier from bank.
5. Sell 4 units at UAH 1,500 net each.
6. Record customer receivable.
7. Receive customer payment.
8. Verify stock balance: 6 units.
9. Verify bank movement.
10. Verify payables/receivables cleared.
11. Verify revenue and COGS.
12. Verify ОСВ balances.

The exact VAT handling is intentionally deferred until the base postings and workflow are stable.

### Go/no-go
Golden scenario must pass both automated reconciliation and manual accountant review before P1 work starts.

## P1 — Opening balance importer

- Chart of accounts
- Counterparties
- Items
- Warehouse balances
- GL opening balances
- AR/AP opening balances
- Pre-import validation and reconciliation summary

## P1 — Ukrainian chart of accounts template

Create the Ukrainian chart mapping required for the pilot company. Keep mapping configurable instead of hardcoding document logic directly to account numbers.

## P1 — VAT transaction fields

Add tax metadata needed to capture Ukrainian transactions while deferring complete electronic tax-invoice/reporting workflows.

## P2 — Regulatory localization

Only after P0/P1 are proven:
- Ukrainian VAT rules
- tax invoices
- statutory reporting
- payroll
- salary taxes
- electronic filing/integrations
- PRRO integrations

## Development rule

Every compatibility feature must answer two questions before merge:

1. Does the accounting result reconcile?
2. Can a 1C/BAS accountant find and execute it without being taught ERPNext terminology?
