import type {
  BootstrapData,
  PostingRow,
  PurchaseDraftPayload,
  PurchaseRow,
  SavePurchaseResult,
} from './types';

const API_BASE = import.meta.env.VITE_API_BASE?.replace(/\/$/, '') ?? '';
const RPC_PREFIX = import.meta.env.VITE_RPC_PREFIX ?? 'erpnext.ua_accounting.api';
const USE_MOCK = !API_BASE || import.meta.env.VITE_MOCK === 'true';

const mockBootstrap: BootstrapData = {
  company: 'ТОВ «Пілот Компані»',
  period: '01.09.2026 — 30.09.2026',
  suppliers: [
    { id: 'SUP-001', name: 'ТОВ «Постачальник»', taxId: '12345678' },
    { id: 'SUP-002', name: 'ТОВ «Тест Сервіс»', taxId: '87654321' },
  ],
  items: [
    { id: 'ITEM-A', name: 'Товар A', isStockItem: true, uom: 'шт' },
    { id: 'SERVICE-A', name: 'Послуга A', isStockItem: false, uom: 'посл.' },
  ],
  warehouses: [
    { id: 'WH-MAIN', name: 'Основний склад' },
  ],
  purchases: [
    {
      id: 'PINV-2026-0001',
      number: '000000001',
      date: '11.09.2026',
      counterparty: 'ТОВ «Постачальник»',
      warehouse: 'Основний склад',
      amount: 10000,
      currency: 'UAH',
      status: 'posted',
      voucherType: 'Purchase Invoice',
    },
    {
      id: 'PINV-2026-0002',
      number: '000000002',
      date: '11.09.2026',
      counterparty: 'ТОВ «Тест Сервіс»',
      warehouse: 'Основний склад',
      amount: 2400,
      currency: 'UAH',
      status: 'draft',
      voucherType: 'Purchase Invoice',
    },
  ],
};

const mockPostings: Record<string, PostingRow[]> = {
  'PINV-2026-0001': [
    {
      id: '1',
      date: '11.09.2026',
      debit: '281 Товари на складі',
      credit: '631 Розрахунки з постачальниками',
      amount: 10000,
      currency: 'UAH',
      counterparty: 'ТОВ «Постачальник»',
      item: 'Товар A',
      warehouse: 'Основний склад',
      source: 'Надходження 000000001',
    },
  ],
};

async function rpc<T>(method: string, args: Record<string, unknown> = {}): Promise<T> {
  const response = await fetch(`${API_BASE}/api/method/${RPC_PREFIX}.${method}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args),
  });
  if (!response.ok) throw new Error(`API ${response.status}: ${response.statusText}`);
  const payload = await response.json();
  return payload.message as T;
}

export async function getBootstrap(): Promise<BootstrapData> {
  if (USE_MOCK) return Promise.resolve(structuredClone(mockBootstrap));
  return rpc<BootstrapData>('bootstrap');
}

export async function getPostings(row: PurchaseRow): Promise<PostingRow[]> {
  if (USE_MOCK) return Promise.resolve(mockPostings[row.id] ?? []);
  return rpc<PostingRow[]>('postings', { document_id: row.id, voucher_type: row.voucherType });
}

export async function savePurchase(
  payload: PurchaseDraftPayload,
  submit: boolean,
): Promise<SavePurchaseResult> {
  if (!USE_MOCK) return rpc<SavePurchaseResult>('save_purchase', { payload, submit });

  const supplier = mockBootstrap.suppliers.find((s) => s.id === payload.supplier);
  const warehouse = mockBootstrap.warehouses.find((w) => w.id === payload.warehouse);
  const grandTotal = payload.items.reduce((sum, row) => sum + row.qty * row.rate, 0);
  const id = payload.document_id ?? `PINV-MOCK-${String(Date.now()).slice(-6)}`;
  const existing = mockBootstrap.purchases.findIndex((row) => row.id === id);
  const row: PurchaseRow = {
    id,
    number: payload.number || id,
    date: payload.posting_date.split('-').reverse().join('.'),
    counterparty: supplier?.name ?? payload.supplier,
    warehouse: warehouse?.name ?? '',
    amount: grandTotal,
    currency: 'UAH',
    status: submit ? 'posted' : 'draft',
    voucherType: 'Purchase Invoice',
  };

  if (existing >= 0) mockBootstrap.purchases[existing] = row;
  else mockBootstrap.purchases.unshift(row);

  if (submit) {
    mockPostings[id] = [
      {
        id: `${id}:1`,
        date: row.date,
        debit: '281 Товари на складі',
        credit: '631 Розрахунки з постачальниками',
        amount: grandTotal,
        currency: 'UAH',
        counterparty: row.counterparty,
        warehouse: row.warehouse,
        source: `Надходження ${row.number}`,
      },
    ];
  }

  return {
    id,
    status: row.status,
    docstatus: submit ? 1 : 0,
    grandTotal,
    currency: 'UAH',
    voucherType: 'Purchase Invoice',
  };
}

export const runtimeMode = USE_MOCK ? 'MOCK' : 'ERPNext';
