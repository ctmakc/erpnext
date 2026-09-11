export type DocumentStatus = 'draft' | 'posted';

export interface PurchaseRow {
  id: string;
  number: string;
  date: string;
  counterparty: string;
  warehouse: string;
  amount: number;
  currency?: string;
  status: DocumentStatus;
  backendStatus?: string;
  voucherType: 'Purchase Invoice';
}

export interface PostingRow {
  id: string;
  date: string;
  debit: string;
  credit: string;
  amount: number;
  currency: string;
  counterparty?: string;
  item?: string;
  warehouse?: string;
  source: string;
}

export interface BootstrapData {
  company: string;
  period: string;
  purchases: PurchaseRow[];
}
