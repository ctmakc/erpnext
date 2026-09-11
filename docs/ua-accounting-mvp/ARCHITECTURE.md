# UA Accounting Compatibility MVP

## Product thesis

Build an accounting product for Ukrainian 1C/BAS users who do not want to relearn their daily workflow.

The product is **not** positioned as a new ERP. The user-facing objective is workflow compatibility: a working accountant should be able to sit down and complete familiar operations with minimal or no training.

ERPNext/Frappe is used as the backend engine where it already provides mature accounting, inventory, sales, purchase, payments, permissions and reporting capabilities. We do not rewrite proven ledger logic unless Ukrainian accounting requirements force us to.

## 30-day technical objective

A pilot company must be able to complete this cycle end-to-end:

1. Create/open a counterparty.
2. Record a purchase.
3. Receive goods into a warehouse.
4. Record a sale.
5. Record incoming/outgoing bank payment.
6. Post accounting entries.
7. Inspect document postings.
8. Open turnover balance / account card equivalent.
9. Verify warehouse and counterparty balances.

The acceptance criterion is not feature count. It is: **an experienced 1C/BAS accountant can execute the cycle without being taught ERPNext.**

## Architecture decision

### Layer 1 — ERPNext/Frappe engine

Reuse existing backend capabilities:

- General Ledger / Journal Entry
- Sales Invoice
- Purchase Invoice
- Payment Entry
- Stock Ledger / Stock Entry
- Warehouses
- Items
- Customers / Suppliers
- Chart of Accounts
- Users, roles and permissions
- Existing financial reports

Keep upstream ERPNext changes as small as practical.

### Layer 2 — Compatibility domain

Add a Ukrainian compatibility layer that maps familiar accounting concepts onto ERPNext objects.

Initial mappings:

| User-facing concept | Backend object / adapter |
| --- | --- |
| Організація | Company |
| Контрагент | Counterparty adapter over Customer/Supplier |
| Номенклатура | Item |
| Склад | Warehouse |
| Рахунок покупцю | Sales Order / Sales Invoice workflow adapter |
| Реалізація товарів/послуг | Sales Invoice |
| Надходження товарів/послуг | Purchase Receipt / Purchase Invoice |
| Банківська виписка | Payment Entry / Bank Transaction adapter |
| Операція / ручні проводки | Journal Entry |
| План рахунків | Account |
| Проводки Дт/Кт | GL Entry presentation |
| ОСВ | Trial Balance / GL aggregation adapter |
| Картка рахунку | General Ledger filtered presentation |

Important: ERPNext separates Customer and Supplier while 1C/BAS accountants think in terms of a single counterparty catalog. The compatibility layer must hide that distinction and present a single `Контрагенти` directory.

### Layer 3 — 1C/BAS-style operator UI

Do not expose standard ERPNext Desk as the primary accountant UI.

Build a dense desktop-oriented operator shell with:

- left navigation by accounting sections;
- document journals as compact tables;
- familiar top command bar;
- `Записати`, `Провести`, `Провести і закрити` actions;
- tabular document lines;
- document status and posting indicator;
- visible `Дт/Кт` action on posted documents;
- list filters and keyboard-first navigation;
- minimal animations and decorative UI;
- Ukrainian language by default.

The interface should optimize for accountants doing hundreds of repetitive operations, not for first-time SaaS users.

## MVP sections

### 1. Головне

- current company;
- period;
- shortcuts to recent documents;
- warnings for unposted/problem documents.

### 2. Довідники

- Організації
- Контрагенти
- Номенклатура
- Склади
- Банківські рахунки
- План рахунків

### 3. Купівлі

- Надходження товарів/послуг
- Повернення постачальнику (after base cycle)
- Розрахунки з постачальниками

### 4. Продажі

- Рахунки
- Реалізація товарів/послуг
- Повернення покупця (after base cycle)
- Розрахунки з покупцями

### 5. Банк і каса

- Вхідний платіж
- Вихідний платіж
- Банківська виписка

### 6. Склад

- Залишки
- Рух товарів
- Переміщення (after base cycle)

### 7. Облік

- Операція
- Проводки
- ОСВ
- Картка рахунку
- Аналіз рахунку (phase 2)

## Posting compatibility

Every business document shown in the compatibility UI must provide a deterministic posting inspection view.

For a posted document show:

- posting date/time;
- debit account;
- credit account;
- amount;
- currency;
- counterparty;
- item/warehouse where relevant;
- source document link.

The accountant must be able to answer "що цей документ зробив в обліку?" without opening ERPNext internals.

## Counterparty adapter

A single counterparty may act as customer, supplier, or both.

Compatibility record fields:

- name;
- legal name;
- EDRPOU / tax identifier;
- VAT status;
- addresses;
- contacts;
- bank details;
- ERPNext Customer link if applicable;
- ERPNext Supplier link if applicable.

Creating a counterparty should lazily create/synchronize Customer and Supplier backend records as required by transactions.

## Data import strategy

### MVP

Support deterministic imports from standard exports:

- counterparties;
- nomenclature;
- chart of accounts;
- opening GL balances;
- warehouse opening balances;
- receivables/payables opening balances.

Input priority: CSV/XLSX and structured XML exported from the source system.

### Phase 2

- standardized 1C/BAS exchange formats where legally and technically practical;
- automated field mapping;
- reconciliation report before commit;
- historical documents;
- migration diagnostics.

Direct parsing of arbitrary `.1CD` databases is explicitly not required for the first pilot.

## Ukrainian accounting localization

Do not attempt the entire Ukrainian regulatory surface in sprint 1.

First pilot:

- Ukrainian chart of accounts template/mapping;
- UAH base currency;
- Ukrainian organization/counterparty identifiers;
- VAT fields sufficient for transaction capture;
- accounting postings and management/financial reports.

Next phases:

- full Ukrainian VAT logic;
- tax invoice workflows;
- statutory financial statements;
- payroll and salary taxes;
- electronic reporting/integrations;
- PRRO/POS integrations where needed.

## Technical principles

1. Backend correctness before visual fidelity.
2. UI workflow fidelity before visual modernity.
3. Avoid deep ERPNext core forks when an adapter/custom page can solve the problem.
4. Every posting flow requires automated tests.
5. Every compatibility screen requires an accountant acceptance scenario.
6. Keep business-domain terminology Ukrainian in the user layer and backend identifiers stable in code.
7. No mandatory external SaaS infrastructure: deployment must work on our own Linux server with Docker-compatible services.

## 30-day execution plan

### Week 1 — accounting shell

- compatibility navigation shell;
- company/period context;
- Counterparty adapter;
- Items and Warehouses lists;
- familiar document journal component;
- first `Дт/Кт` posting viewer;
- Ukrainian terminology dictionary.

### Week 2 — purchase and sale

- purchase document workflow;
- sales document workflow;
- posting inspection;
- stock effects;
- counterparties balance checks;
- automated golden-path tests.

### Week 3 — bank and reports

- incoming/outgoing payments;
- bank statement-style journal;
- ОСВ compatibility report;
- account card report;
- opening balances importer.

### Week 4 — real accountant pilot

- migrate one test company;
- execute one complete monthly mini-cycle;
- record every point where the accountant asks "а де це?";
- remove those workflow mismatches;
- freeze pilot scope;
- decide whether to continue on ERPNext or replace any subsystem that materially blocks compatibility.

## Explicitly out of scope for first 30 days

- payroll;
- production/MRP customization;
- fixed assets localization beyond what ERPNext provides;
- full tax reporting;
- electronic tax-invoice registration;
- direct arbitrary 1CD parsing;
- mobile accountant UI;
- AI features;
- CRM redesign;
- full configurator/platform clone.

## Go / no-go metrics

Continue after pilot only if all are true:

1. The full purchase → stock → sale → bank → ledger → ОСВ cycle works.
2. Accounting entries reconcile with the agreed test scenario.
3. An experienced 1C/BAS accountant completes the cycle with no formal training.
4. Fewer than 10 material workflow mismatches remain after the pilot correction pass.
5. We can keep most customization outside heavily modified ERPNext core code.

If #5 fails, treat ERPNext as a reference/prototype engine and evaluate extracting the compatibility layer onto a purpose-built backend.