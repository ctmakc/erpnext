# UA Accounting UI prototype

Standalone accountant-facing compatibility frontend for the UA Accounting MVP.

## Run

```bash
npm install
npm run dev
```

It starts in mock mode, so ERPNext is not required to review the workflow.

To connect the UI to the compatibility adapter, copy `.env.example` to `.env`, set `VITE_API_BASE`, and set `VITE_MOCK=false`.

## First implemented slice

- dense desktop-oriented shell;
- familiar accounting sections;
- company and period context;
- purchase journal (`Надходження товарів/послуг`);
- posted/unposted state;
- `Дт/Кт` posting viewer;
- mock-first API boundary designed for the future Frappe adapter.

This folder is intentionally isolated so it can be extracted into its own repository later.
