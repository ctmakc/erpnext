# UA Accounting MVP — Architecture Decisions

## ADR-001: ERPNext is backend engine, not accountant UI

**Decision:** Use ERPNext/Frappe for accounting/inventory/business objects, but do not expose standard ERPNext Desk as the primary accountant interface.

**Reason:** The product goal is near-zero retraining for 1C/BAS accountants. ERPNext terminology and navigation are too different even where backend functionality already exists.

## ADR-002: Build a separate compatibility frontend over Frappe APIs

**Decision:** Preferred production architecture is a separate desktop-oriented web frontend talking to ERPNext/Frappe through its REST/RPC APIs.

**Reason:**
- keeps upstream ERPNext core easier to update;
- allows exact workflow/UI compatibility without fighting Desk conventions;
- gives us independent release velocity for the accountant interface;
- makes it possible to replace ERPNext backend components later without rewriting the UI contract.

The Frappe API layer becomes an anti-corruption boundary between our Ukrainian compatibility domain and ERPNext internals.

## ADR-003: Do not build the product directly on the current customized ERPNext fork

The existing `ctmakc/erpnext` fork contains unrelated custom Remolda changes. Treat it as a useful development/reference fork, not as the clean production baseline.

For production, use a clean, pinned ERPNext/Frappe version plus our adapter/custom app and separate compatibility frontend.

## ADR-004: Keep a thin backend adapter/custom app

Use a small Frappe custom app for operations that cannot be expressed safely through generic DocType CRUD alone, including:

- unified Counterparty adapter;
- posting inspection normalization;
- Ukrainian chart-of-accounts mapping;
- opening-balance imports;
- compatibility report endpoints;
- transaction orchestration where several ERPNext documents must be created atomically;
- future Ukrainian regulatory logic.

Do not duplicate ERPNext ledger and stock engines in this adapter.

## ADR-005: Frontend contract uses compatibility concepts, not ERPNext concepts

Frontend API/domain names should reflect accountant language:

- `counterparties`
- `purchases`
- `sales`
- `bank-statements`
- `postings`
- `turnover-balance`
- `account-card`

The adapter translates these concepts to ERPNext DocTypes and methods.

This prevents ERPNext-specific structures from leaking throughout the UI.

## ADR-006: Start with workflow fidelity, not pixel copying

We intentionally reproduce the familiar information architecture, density, command placement and workflow semantics of 1C/BAS without copying proprietary source code, proprietary assets or implementation details.

Initial target actions:

- `Записати`
- `Провести`
- `Провести і закрити`
- `Дт/Кт`
- familiar journals/tables
- filters by period/counterparty/document state
- keyboard-first repeated operations

## ADR-007: Golden cycle before Ukrainian regulatory breadth

The first hard gate is:

`purchase → stock → supplier payment → sale → customer payment → postings → ОСВ`

Only after that reconciles and passes accountant usability review do we invest in full VAT, tax invoices, statutory reporting, payroll or PRRO integrations.

## ADR-008: Deployment must be self-hostable

The complete MVP must be deployable on our own Linux server. No mandatory Supabase, Vercel or other metered SaaS dependency is allowed in the critical accounting path.

Preferred deployment shape:

- reverse proxy;
- compatibility frontend;
- compatibility adapter/custom Frappe app;
- Frappe/ERPNext;
- database/cache/services required by the pinned ERPNext version;
- backups and object/file storage under our control.

## Immediate implementation sequence

1. Create clean compatibility frontend project.
2. Create thin Frappe adapter app against a pinned clean ERPNext version.
3. Implement authentication/session bridge.
4. Implement read-only lists: company, counterparties, items, warehouses.
5. Implement unified Counterparty creation/sync.
6. Implement read-only normalized `Дт/Кт` endpoint.
7. Build sales/purchase compatibility forms.
8. Build bank/payment workflow.
9. Build ОСВ and account-card compatibility views.
10. Run golden accounting scenario and reconcile all totals.
