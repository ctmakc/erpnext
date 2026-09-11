import { useEffect, useMemo, useState } from 'react';
import { getBootstrap, getPostings, runtimeMode } from './api';
import PurchaseEditor from './PurchaseEditor';
import type { BootstrapData, PostingRow, PurchaseRow, SavePurchaseResult } from './types';

const sections = [
  ['Головне', 'Огляд'],
  ['Довідники', 'Контрагенти', 'Номенклатура', 'Склади', 'План рахунків'],
  ['Купівлі', 'Надходження товарів/послуг', 'Розрахунки з постачальниками'],
  ['Продажі', 'Реалізація товарів/послуг', 'Рахунки покупцям'],
  ['Банк і каса', 'Банківська виписка', 'Вхідні платежі', 'Вихідні платежі'],
  ['Склад', 'Залишки', 'Рух товарів'],
  ['Облік', 'ОСВ', 'Картка рахунку', 'Операції'],
];

function money(value: number) {
  return new Intl.NumberFormat('uk-UA', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

export default function App() {
  const [data, setData] = useState<BootstrapData | null>(null);
  const [active, setActive] = useState('Надходження товарів/послуг');
  const [selected, setSelected] = useState<PurchaseRow | null>(null);
  const [postings, setPostings] = useState<PostingRow[] | null>(null);
  const [showPurchaseEditor, setShowPurchaseEditor] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      setData(await getBootstrap());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => { void refresh(); }, []);

  const total = useMemo(
    () => data?.purchases.reduce((sum, row) => sum + row.amount, 0) ?? 0,
    [data],
  );

  async function openPostings(row: PurchaseRow) {
    setSelected(row);
    try {
      setPostings(await getPostings(row));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function afterPurchaseSaved(_result: SavePurchaseResult) {
    await refresh();
  }

  const canCreatePurchase = active === 'Надходження товарів/послуг';

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">Облік UA</div>
        <div className="context">
          <label>Організація <strong>{data?.company ?? '—'}</strong></label>
          <label>Період <strong>{data?.period ?? '—'}</strong></label>
        </div>
        <div className="mode">{runtimeMode}</div>
      </header>

      <div className="workspace">
        <aside className="sidebar">
          {sections.map(([title, ...items]) => (
            <section key={title}>
              <h3>{title}</h3>
              {items.map((item) => (
                <button key={item} className={active === item ? 'nav-item active' : 'nav-item'} onClick={() => setActive(item)}>{item}</button>
              ))}
            </section>
          ))}
        </aside>

        <main className="content">
          <div className="title-row">
            <h1>{active}</h1>
            <div className="toolbar">
              <button className="primary" disabled={!canCreatePurchase || !data} onClick={() => setShowPurchaseEditor(true)}>Створити</button>
              <button onClick={() => void refresh()}>Оновити</button>
              <button>Знайти</button>
              <button>Ще ▾</button>
            </div>
          </div>

          {error && <div className="error">{error}</div>}

          <div className="filterbar">
            <label>Період <input value={data?.period ?? ''} readOnly /></label>
            <label>Контрагент <input placeholder="Усі" /></label>
            <label>Стан <select defaultValue="all"><option value="all">Усі</option><option>Проведені</option><option>Не проведені</option></select></label>
            <button onClick={() => void refresh()}>Сформувати</button>
          </div>

          <div className="table-wrap">
            <table>
              <thead><tr><th className="status-col"></th><th>Дата</th><th>Номер</th><th>Контрагент</th><th>Склад</th><th className="num">Сума</th><th>Стан</th><th></th></tr></thead>
              <tbody>
                {data?.purchases.map((row) => (
                  <tr key={row.id} className={selected?.id === row.id ? 'selected' : ''} onClick={() => setSelected(row)}>
                    <td className="status-col"><span className={row.status === 'posted' ? 'posted-dot' : 'draft-dot'} /></td>
                    <td>{row.date}</td>
                    <td><button className="link">{row.number}</button></td>
                    <td>{row.counterparty}</td>
                    <td>{row.warehouse}</td>
                    <td className="num">{money(row.amount)} {row.currency ?? ''}</td>
                    <td>{row.status === 'posted' ? 'Проведено' : 'Не проведено'}</td>
                    <td><button disabled={row.status !== 'posted'} onClick={(e) => { e.stopPropagation(); void openPostings(row); }}>Дт/Кт</button></td>
                  </tr>
                ))}
              </tbody>
              <tfoot><tr><td colSpan={5}>Разом</td><td className="num">{money(total)}</td><td colSpan={2}></td></tr></tfoot>
            </table>
          </div>

          <div className="statusbar"><span>{data?.purchases.length ?? 0} документ(и)</span><span>Подвійний клік — відкрити · Ctrl+N — створити · Enter — вибрати</span></div>
        </main>
      </div>

      {showPurchaseEditor && data && <PurchaseEditor data={data} onClose={() => setShowPurchaseEditor(false)} onSaved={afterPurchaseSaved} />}

      {postings && selected && (
        <div className="overlay" onClick={() => setPostings(null)}>
          <section className="posting-panel" onClick={(e) => e.stopPropagation()}>
            <div className="panel-title"><div><strong>Проводки Дт/Кт</strong><small>Надходження № {selected.number} від {selected.date}</small></div><button onClick={() => setPostings(null)}>✕</button></div>
            <table>
              <thead><tr><th>Дата</th><th>Дебет</th><th>Кредит</th><th className="num">Сума</th><th>Контрагент</th><th>Номенклатура / склад</th></tr></thead>
              <tbody>
                {postings.map((p) => <tr key={p.id}><td>{p.date}</td><td>{p.debit}</td><td>{p.credit}</td><td className="num">{money(p.amount)} {p.currency}</td><td>{p.counterparty ?? '—'}</td><td>{[p.item, p.warehouse].filter(Boolean).join(' · ') || '—'}</td></tr>)}
                {!postings.length && <tr><td colSpan={6}>Проводок немає</td></tr>}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </div>
  );
}
