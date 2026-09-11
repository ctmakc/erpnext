import type { BootstrapData, PostingRow } from './types';

const API_BASE = import.meta.env.VITE_API_BASE?.replace(/\/$/, '') ?? '';
const USE_MOCK = !API_BASE || import.meta.env.VITE_MOCK === 'true';

const mockBootstrap: BootstrapData = {
  company: 'ТОВ «Пілот Компані»',
  period: '01.09.2026 — 30.09.2026',
  purchases: [
    {
      id: 'PINV-2026-0001',
      number: '000000001',
      date: '11.09.2026',
      counterparty: 'ТОВ «Постачальник»',
      warehouse: 'Основний склад',
      amount: 10000,
      status: 'posted',
    },
    {
      id: 'PINV-2026-0002',
      number: '000000002',
      date: '11.09.2026',
      counterparty: 'ТОВ «Тест Сервіс»',
      warehouse: 'Основний склад',
      amount: 2400,
      status: 'draft',
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
  const response = await fetch(`${API_BASE}/api/method/${method}`, {
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
  if (USE_MOCK) return Promise.resolve(mockBootstrap);
  return rpc<BootstrapData>('ua_accounting_adapter.api.bootstrap');
}

export async function getPostings(documentId: string): Promise<PostingRow[]> {
  if (USE_MOCK) return Promise.resolve(mockPostings[documentId] ?? []);
  return rpc<PostingRow[]>('ua_accounting_adapter.api.postings', { document_id: documentId });
}

export const runtimeMode = USE_MOCK ? 'MOCK' : 'ERPNext';
