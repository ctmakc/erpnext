export type DocumentStatus = 'draft' | 'posted';

export interface SupplierRef {
  id: string;
  name: string;
  taxId?: string | null;
}

export interface ItemRef {
  id: string;
  name: string;
  isStockItem: boolean;
  uom: string;
}

export interface WarehouseRef {
  id: string;
  name: string;
}

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
  suppliers: SupplierRef[];
  items: ItemRef[];
  warehouses: WarehouseRef[];
}

export interface PurchaseDraftLine {
  key: string;
  item_code: string;
  qty: number;
  rate: number;
}

export interface PurchaseDraftPayload {
  document_id?: string;
  company: string;
  supplier: string;
  posting_date: string;
  number?: string;
  warehouse?: string;
  items: Array<{
    item_code: string;
    qty: number;
    rate: number;
  }>;
}

export interface SavePurchaseResult {
  id: string;
  status: DocumentStatus;
  docstatus: number;
  grandTotal: number;
  currency: string;
  voucherType: 'Purchase Invoice';
}
