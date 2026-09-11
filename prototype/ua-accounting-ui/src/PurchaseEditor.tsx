import { useMemo, useState } from 'react';
import { savePurchase } from './api';
import type {
  BootstrapData,
  PurchaseDraftLine,
  PurchaseDraftPayload,
  SavePurchaseResult,
} from './types';

interface Props {
  data: BootstrapData;
  onClose: () => void;
  onSaved: (result: SavePurchaseResult) => Promise<void> | void;
}

function newLine(): PurchaseDraftLine {
  return { key: crypto.randomUUID(), item_code: '', qty: 1, rate: 0 };
}

export default function PurchaseEditor({ data, onClose, onSaved }: Props) {
  const [documentId, setDocumentId] = useState<string | undefined>();
  const [supplier, setSupplier] = useState(data.suppliers[0]?.id ?? '');
  const [warehouse, setWarehouse] = useState(data.warehouses[0]?.id ?? '');
  const [postingDate, setPostingDate] = useState(new Date().toISOString().slice(0, 10));
  const [number, setNumber] = useState('');
  const [lines, setLines] = useState<PurchaseDraftLine[]>([newLine()]);
  const [busy, setBusy] = useState(false);
  const [posted, setPosted] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const total = useMemo(
    () => lines.reduce((sum, line) => sum + Number(line.qty || 0) * Number(line.rate || 0), 0),
    [lines],
  );

  function updateLine(key: string, patch: Partial<PurchaseDraftLine>) {
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...patch } : line)));
  }

  function buildPayload(): PurchaseDraftPayload {
    return {
      document_id: documentId,
      company: data.company,
      supplier,
      posting_date: postingDate,
      number: number || undefined,
      warehouse: warehouse || undefined,
      items: lines
        .filter((line) => line.item_code)
        .map((line) => ({ item_code: line.item_code, qty: Number(line.qty), rate: Number(line.rate) })),
    };
  }

  async function persist(submit: boolean, closeAfter: boolean) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await savePurchase(buildPayload(), submit);
      setDocumentId(result.id);
      setPosted(result.status === 'posted');
      setMessage(result.status === 'posted' ? `Документ ${result.id} проведено` : `Документ ${result.id} записано`);
      await onSaved(result);
      if (closeAfter) onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="overlay editor-overlay" onClick={onClose}>
      <section className="document-editor" onClick={(e) => e.stopPropagation()}>
        <div className="document-header">
          <div>
            <strong>Надходження товарів і послуг</strong>
            <small>{documentId ? `Документ ${documentId}` : 'Новий документ'}</small>
          </div>
          <button onClick={onClose}>✕</button>
        </div>

        <div className="document-toolbar">
          <button disabled={busy || posted} onClick={() => void persist(false, false)}>Записати</button>
          <button className="primary" disabled={busy || posted} onClick={() => void persist(true, false)}>Провести</button>
          <button className="primary" disabled={busy || posted} onClick={() => void persist(true, true)}>Провести і закрити</button>
          <button disabled={!posted}>Дт/Кт</button>
        </div>

        {error && <div className="error">{error}</div>}
        {message && <div className="success">{message}</div>}

        <div className="document-fields">
          <label>
            Контрагент
            <select value={supplier} disabled={posted} onChange={(e) => setSupplier(e.target.value)}>
              <option value="">— оберіть —</option>
              {data.suppliers.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </select>
          </label>
          <label>
            Дата
            <input type="date" value={postingDate} disabled={posted} onChange={(e) => setPostingDate(e.target.value)} />
          </label>
          <label>
            Номер постачальника
            <input value={number} disabled={posted} onChange={(e) => setNumber(e.target.value)} />
          </label>
          <label>
            Склад
            <select value={warehouse} disabled={posted} onChange={(e) => setWarehouse(e.target.value)}>
              <option value="">— без складу —</option>
              {data.warehouses.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </select>
          </label>
        </div>

        <div className="lines-toolbar">
          <strong>Товари та послуги</strong>
          <button disabled={posted} onClick={() => setLines((current) => [...current, newLine()])}>Додати рядок</button>
        </div>

        <div className="table-wrap editor-lines">
          <table>
            <thead><tr><th>#</th><th>Номенклатура</th><th>Од.</th><th className="num">Кількість</th><th className="num">Ціна</th><th className="num">Сума</th><th></th></tr></thead>
            <tbody>
              {lines.map((line, index) => {
                const item = data.items.find((row) => row.id === line.item_code);
                const amount = Number(line.qty || 0) * Number(line.rate || 0);
                return (
                  <tr key={line.key}>
                    <td>{index + 1}</td>
                    <td>
                      <select value={line.item_code} disabled={posted} onChange={(e) => updateLine(line.key, { item_code: e.target.value })}>
                        <option value="">— оберіть —</option>
                        {data.items.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
                      </select>
                    </td>
                    <td>{item?.uom ?? '—'}</td>
                    <td><input className="num-input" type="number" min="0.0001" step="0.0001" value={line.qty} disabled={posted} onChange={(e) => updateLine(line.key, { qty: Number(e.target.value) })} /></td>
                    <td><input className="num-input" type="number" min="0" step="0.01" value={line.rate} disabled={posted} onChange={(e) => updateLine(line.key, { rate: Number(e.target.value) })} /></td>
                    <td className="num">{amount.toLocaleString('uk-UA', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    <td><button disabled={posted || lines.length === 1} onClick={() => setLines((current) => current.filter((row) => row.key !== line.key))}>×</button></td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot><tr><td colSpan={5}>Разом</td><td className="num">{total.toLocaleString('uk-UA', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td><td></td></tr></tfoot>
          </table>
        </div>
      </section>
    </div>
  );
}
