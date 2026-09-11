# UA Accounting MVP — Golden Scenario

This scenario is the regression gate for the first usable release. Every new compatibility feature must preserve it.

## Scope

No VAT, payroll, manufacturing, tax invoices or statutory reporting in this gate. The purpose is to prove the core commercial accounting cycle and 1C/BAS-style operator workflow.

## Test company

- Base currency: UAH.
- One operating company.
- One bank account.
- One warehouse.
- One stock item.
- One supplier.
- One customer.

## Opening state

- Bank balance: UAH 100,000.
- Stock: 0 units.
- Supplier payable: 0.
- Customer receivable: 0.

## Transaction 1 — purchase and receipt

Create `Надходження товарів/послуг`:

- supplier: Test Supplier;
- item: Test Item;
- quantity: 10;
- unit cost: UAH 1,000;
- total: UAH 10,000;
- warehouse: Main Warehouse.

Expected after `Провести`:

- stock quantity = 10;
- inventory value increases by UAH 10,000 (subject to configured inventory accounts);
- supplier payable increases by UAH 10,000;
- document is marked `Проведено`;
- `Дт/Кт` opens paired postings whose total debit equals total credit and equals the relevant transaction value.

## Transaction 2 — supplier payment

Create outgoing bank payment for UAH 10,000 and allocate it to the purchase.

Expected:

- bank decreases from UAH 100,000 to UAH 90,000;
- supplier payable returns to 0;
- payment document has inspectable `Дт/Кт` postings.

## Transaction 3 — sale

Create `Реалізація товарів/послуг`:

- customer: Test Customer;
- item: Test Item;
- quantity: 4;
- unit sales price: UAH 1,500;
- total revenue: UAH 6,000;
- warehouse: Main Warehouse.

Expected after `Провести`:

- stock quantity = 6;
- customer receivable = UAH 6,000;
- revenue = UAH 6,000;
- COGS reflects 4 units at the inventory valuation generated from the purchase;
- sale `Дт/Кт` is inspectable.

## Transaction 4 — customer payment

Create incoming bank payment for UAH 6,000 and allocate it to the sale.

Expected:

- customer receivable returns to 0;
- bank increases from UAH 90,000 to UAH 96,000;
- payment `Дт/Кт` is inspectable.

## Final invariants

The following must all be true at the same time:

1. Physical stock = 6 units.
2. Supplier payable = 0.
3. Customer receivable = 0.
4. Bank balance = UAH 96,000.
5. Revenue = UAH 6,000.
6. Inventory/COGS totals reconcile with the stock ledger.
7. Every submitted business document has balanced GL entries.
8. `ОСВ` totals reconcile to the underlying GL entries.
9. Account-card drilldown reproduces the same movements.
10. A 1C/BAS accountant can execute the whole scenario without entering ERPNext Desk.

## UX acceptance observations

During manual accountant review record every occurrence of:

- "де це?";
- "чому воно так називається?";
- "в 1С я це роблю швидше";
- unnecessary clicks;
- missing keyboard path;
- unfamiliar document/status semantics.

A mismatch is considered material when it forces explanation, navigation into standard ERPNext UI, manual duplicate entry, or changes the accountant's normal mental model.

## Gate

P0 is not complete until the scenario passes end-to-end on a real ERPNext/Frappe instance and the final balances are reconciled independently from both GL and stock data.
