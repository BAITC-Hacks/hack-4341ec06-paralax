import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Activity, ArrowRight, Boxes, Check, ChevronLeft, ChevronRight, CircleAlert, Clock3, ExternalLink, Layers3, PackageCheck, RefreshCw, Search, SlidersHorizontal, Truck, X } from 'lucide-react';
import './stage8.css';

type Row = {
  brand: string; sku: string; name: string; unit: string;
  current_stock: number | null; goods_in_transit: number | null;
  forecast: number | null; target_stock: number | null;
  recommended_order: number | null; purchase_needed: boolean | null;
  urgency: string | null; status: string;
  stock_quality: string | null; transit_quality: string | null;
  rule_kind: string | null; rule_quantity: number | null;
};
type DashboardData = { planning_date: string; scenario_kind?: string; source_kind?: string; rows: Row[] };
type Filter = 'all' | 'order' | 'high' | 'needs_data';
const PAGE_SIZE = 35;
const EMPTY_ROWS: Row[] = [];
const number = (value: number | null, digits = 1) => value === null ? '—' : new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(value);
const statusLabel: Record<string, string> = { calculated: 'Рассчитано', provisional: 'Условно', unavailable: 'Нет данных' };
const urgencyLabel: Record<string, string> = { HIGH: 'Высокий', MEDIUM: 'Средний', LOW: 'Низкий' };
const keyOf = (row: Row) => `${row.brand}\u0000${row.sku}`;
const traceUrl = (row: Row) => `/api/trace?brand=${encodeURIComponent(row.brand)}&sku=${encodeURIComponent(row.sku)}`;

function plainError(error: unknown) { return error instanceof Error ? error.message : 'Не удалось загрузить данные.'; }
async function loadDashboard(): Promise<DashboardData> {
  const response = await fetch('/api/dashboard');
  if (!response.ok) throw new Error(`Сервис расчёта ответил ${response.status}.`);
  const payload: unknown = await response.json();
  if (!payload || typeof payload !== 'object' || !Array.isArray((payload as DashboardData).rows)) throw new Error('Ответ сервиса имеет неверный формат.');
  return payload as DashboardData;
}

export default function Stage8Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [brand, setBrand] = useState('all');
  const [filter, setFilter] = useState<Filter>('all');
  const [page, setPage] = useState(1);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [stock, setStock] = useState('');
  const [transit, setTransit] = useState('');
  const [asOfDate, setAsOfDate] = useState('');
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  const [formNotice, setFormNotice] = useState('');
  const rows = data?.rows ?? EMPTY_ROWS;
  const selected = rows.find(row => keyOf(row) === selectedKey) ?? null;
  const isIllustrative = (data?.scenario_kind ?? data?.source_kind ?? '').includes('illustrative');

  useEffect(() => {
    let active = true;
    loadDashboard().then(result => { if (active) { setData(result); setError(''); } })
      .catch(cause => { if (active) setError(plainError(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!selectedKey) return;
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setSelectedKey(null); };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [selectedKey]);

  const counts = useMemo(() => ({
    total: rows.length,
    order: rows.filter(row => row.purchase_needed === true && (row.recommended_order ?? 0) > 0).length,
    high: rows.filter(row => row.urgency === 'HIGH').length,
    needsData: rows.filter(row => row.status === 'unavailable').length,
    iek: rows.filter(row => row.brand === 'IEK').length,
    systeme: rows.filter(row => row.brand === 'Systeme Electric').length,
  }), [rows]);
  const filtered = useMemo(() => rows.filter(row => {
    if (brand !== 'all' && row.brand !== brand) return false;
    if (filter === 'order' && !(row.purchase_needed === true && (row.recommended_order ?? 0) > 0)) return false;
    if (filter === 'high' && row.urgency !== 'HIGH') return false;
    if (filter === 'needs_data' && row.status !== 'unavailable') return false;
    const search = query.trim().toLocaleLowerCase('ru-RU');
    return !search || `${row.sku} ${row.name} ${row.brand}`.toLocaleLowerCase('ru-RU').includes(search);
  }).sort((a, b) => {
    const score = (row: Row) => (row.purchase_needed ? 4 : 0) + (row.urgency === 'HIGH' ? 2 : 0) + (row.status === 'calculated' ? 1 : 0);
    return score(b) - score(a) || a.brand.localeCompare(b.brand) || a.sku.localeCompare(b.sku);
  }), [rows, brand, filter, query]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const visible = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  function openRow(row: Row) {
    setSelectedKey(keyOf(row));
    setStock(row.current_stock === null ? '' : String(row.current_stock));
    setTransit(row.goods_in_transit === null ? '' : String(row.goods_in_transit));
    setAsOfDate(data?.planning_date ?? '');
    setFormError(''); setFormNotice('');
  }
  async function saveStock() {
    if (!selected) return;
    const current = Number(stock), inTransit = Number(transit);
    if (!stock.trim() || !transit.trim() || !Number.isFinite(current) || !Number.isFinite(inTransit) || current < 0 || inTransit < 0 || !/^\d{4}-\d{2}-\d{2}$/.test(asOfDate)) {
      setFormError('Укажите дату и два неотрицательных количества. Ноль вводите явно.'); return;
    }
    setSaving(true); setFormError(''); setFormNotice('');
    try {
      const response = await fetch('/api/stock', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ brand: selected.brand, sku: selected.sku, current_stock: current, goods_in_transit: inTransit, as_of_date: asOfDate }) });
      const payload = await response.json();
      if (!response.ok || !payload?.row) throw new Error(payload?.error ?? `Сервис ответил ${response.status}.`);
      const next = payload.row as Row;
      setData(previous => previous ? { ...previous, rows: previous.rows.map(row => keyOf(row) === keyOf(next) ? next : row) } : previous);
      setFormNotice('Пересчитано на сервере. Теперь можно открыть полную цепочку расчёта.');
    } catch (cause) { setFormError(plainError(cause)); }
    finally { setSaving(false); }
  }
  async function refresh() {
    setLoading(true); setError('');
    try { setData(await loadDashboard()); }
    catch (cause) { setError(plainError(cause)); }
    finally { setLoading(false); }
  }

  return <div className="s8">
    <aside className="s8-sidebar">
      <a className="s8-logo" href="/" aria-label="Paralax — обзор"><span className="s8-logo-mark"><Layers3 size={23}/></span><span>paralax<small>SUPPLY INTELLIGENCE</small></span></a>
      <div className="s8-side-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <a className="s8-nav-active" href="#overview"><Activity size={18}/> Обзор закупок</a>
      <a className="s8-nav-link" href="#catalog"><Boxes size={18}/> Каталог SKU</a>
      <div className="s8-side-bottom"><div className="s8-side-card"><span className="s8-side-card-icon"><PackageCheck size={20}/></span><strong>Решение за менеджером</strong><p>Система рассчитывает черновик. Отправка заказа поставщику не выполняется.</p></div><div className="s8-side-foot">HACKALEM AI · MVP</div></div>
    </aside>
    <main className="s8-main" id="overview">
      <div className="s8-topline"><span>Рабочее пространство <ChevronRight size={14}/> <strong>Обзор закупок</strong></span><div><span className="s8-live-dot"/> {isIllustrative ? 'Учебный сценарий' : 'Исходный снимок'} <span className="s8-topline-separator"/> {data?.planning_date ?? '—'}</div></div>
      <div className="s8-content">
        <header className="s8-hero"><div className="s8-hero-copy"><span className="s8-kicker">ПЛАНИРОВАНИЕ ПОСТАВОК <i/> ЭЛЕКТРОКОМПЛЕКТ</span><h1>Заказы под контролем<span>.</span></h1><p>От прогноза спроса до конкретного заказа. Каждую цифру можно проверить по исходным данным.</p><div className="s8-hero-actions"><a href="#catalog" className="s8-hero-primary">Смотреть рекомендации <ArrowRight size={17}/></a><button onClick={refresh} disabled={loading}><RefreshCw size={16}/> Обновить данные</button></div></div><div className="s8-hero-art" aria-hidden="true"><span className="s8-art-orbit s8-art-one"/><span className="s8-art-orbit s8-art-two"/><span className="s8-art-core"><Truck size={49}/></span><span className="s8-art-chip s8-art-chip-one">ПРОГНОЗ</span><span className="s8-art-chip s8-art-chip-two">ПОСТАВКА</span></div></header>
        {error && <div className="s8-error" role="alert"><CircleAlert size={19}/><div><strong>Данные не загружены</strong><p>{error} Запустите локальный сервис: <code>python backend/dashboard_server.py --scenario demo-user-input</code></p></div></div>}
        <div className="s8-section-heading"><div><span className="s8-eyebrow">ОБЩАЯ КАРТИНА</span><h2>Состояние расчёта</h2></div><span>По данным выбранного сценария</span></div>
        <div className="s8-metrics"><Metric icon={<Boxes size={21}/>} label="Всего артикулов" value={number(counts.total, 0)} note={`${number(counts.iek, 0)} IEK · ${number(counts.systeme, 0)} Systeme`}/><Metric icon={<PackageCheck size={21}/>} label="К заказу" value={number(counts.order, 0)} note="положительная рекомендация" tone="teal"/><Metric icon={<Clock3 size={21}/>} label="Высокий риск" value={number(counts.high, 0)} note="срочность HIGH" tone="orange"/><Metric icon={<CircleAlert size={21}/>} label="Нужны данные" value={number(counts.needsData, 0)} note="заказ не рассчитан" tone="slate"/></div>
        <div className="s8-context"><span><SlidersHorizontal size={19}/></span><div><strong>{isIllustrative ? 'Показан учебный ввод остатков' : 'Для расчёта нужны актуальные остатки'}</strong><p>{isIllustrative ? 'Только часть SKU имеет введённые вручную остатки. Они не сверены автоматически со складом; остальные позиции сохраняют статус «Нет данных» или «Условно».' : 'Исторические остатки не подставляются как текущие. Откройте SKU и укажите остаток и товар в пути, чтобы получить рекомендацию.'}</p></div></div>
        <section className="s8-catalog" id="catalog"><div className="s8-catalog-head"><div><span className="s8-eyebrow">КАТАЛОГ РЕКОМЕНДАЦИЙ</span><h2>Что закупать <em>{number(filtered.length, 0)}</em></h2><p>Выберите артикул, чтобы обновить остатки или проследить расчёт.</p></div><span className="s8-readonly"><Check size={15}/> Проверяемые расчёты</span></div>
          <div className="s8-brand-tabs" role="group" aria-label="Бренд"><button className={brand === 'all' ? 'active' : ''} onClick={() => { setPage(1); setBrand('all'); }}>Все бренды <span>{counts.total}</span></button><button className={brand === 'IEK' ? 'active' : ''} onClick={() => { setPage(1); setBrand('IEK'); }}>IEK <span>{counts.iek}</span></button><button className={brand === 'Systeme Electric' ? 'active' : ''} onClick={() => { setPage(1); setBrand('Systeme Electric'); }}>Systeme Electric <span>{counts.systeme}</span></button></div>
          <div className="s8-toolbar"><label className="s8-search"><Search size={18}/><input value={query} onChange={event => { setPage(1); setQuery(event.target.value); }} placeholder="Поиск по коду или названию" aria-label="Поиск по коду или названию"/></label><label className="s8-filter-select"><SlidersHorizontal size={17}/><select value={filter} onChange={event => { setPage(1); setFilter(event.target.value as Filter); }} aria-label="Фильтр рекомендаций"><option value="all">Все позиции</option><option value="order">К заказу</option><option value="high">Высокий риск</option><option value="needs_data">Нужны данные</option></select></label></div>
          <div className="s8-table-scroll"><table><thead><tr><th>SKU / ТОВАР</th><th>ОСТАТОК</th><th>В ПУТИ</th><th>ПРОГНОЗ</th><th>ЗАКАЗАТЬ</th><th>СРОЧНОСТЬ</th><th>СТАТУС</th><th aria-label="Открыть"/></tr></thead><tbody>{visible.map(row => <tr key={keyOf(row)} onClick={() => openRow(row)}><td><strong>{row.name || row.sku}</strong><small>{row.brand} · {row.sku}</small></td><td>{number(row.current_stock)}<small>{row.current_stock === null ? 'нужен ввод' : row.unit}</small></td><td>{number(row.goods_in_transit)}<small>{row.goods_in_transit === null ? 'нужен ввод' : row.unit}</small></td><td>{number(row.forecast)}<small>{row.unit} / срок поставки</small></td><td className="s8-order-cell">{row.recommended_order === null ? <span className="s8-dash">—</span> : <strong>{number(row.recommended_order, 0)}</strong>}<small>{row.recommended_order === null ? 'не рассчитано' : row.unit}</small></td><td>{row.urgency ? <span className={`s8-urgency s8-urgency-${row.urgency.toLowerCase()}`}>{urgencyLabel[row.urgency] ?? row.urgency}</span> : <span className="s8-dash">—</span>}</td><td><span className={`s8-status s8-status-${row.status}`}>{statusLabel[row.status] ?? row.status}</span></td><td><button className="s8-row-arrow" aria-label={`Открыть ${row.sku}`} onClick={event => { event.stopPropagation(); openRow(row); }}><ArrowRight size={17}/></button></td></tr>)}</tbody></table>{!loading && visible.length === 0 && <div className="s8-empty"><Search size={30}/><strong>Позиции не найдены</strong><p>Измените запрос или фильтр.</p></div>}{loading && <div className="s8-empty">Загружаем результаты расчёта…</div>}</div>
          <div className="s8-table-foot"><span>Показано {visible.length ? (page - 1) * PAGE_SIZE + 1 : 0}–{Math.min(page * PAGE_SIZE, filtered.length)} из {filtered.length}</span><div><button disabled={page <= 1} onClick={() => setPage(value => value - 1)} aria-label="Предыдущая страница"><ChevronLeft size={18}/></button><span>{page} / {pageCount}</span><button disabled={page >= pageCount} onClick={() => setPage(value => value + 1)} aria-label="Следующая страница"><ChevronRight size={18}/></button></div></div>
        </section><footer className="s8-footer"><span>paralax</span><span>Черновые рекомендации · решение остаётся за человеком</span></footer>
      </div>
    </main>
    {selected && <div className="s8-overlay" onMouseDown={event => { if (event.target === event.currentTarget) setSelectedKey(null); }}><aside className="s8-drawer" role="dialog" aria-modal="true" aria-label={`Расчёт ${selected.sku}`}><button className="s8-close" onClick={() => setSelectedKey(null)} aria-label="Закрыть"><X size={20}/></button><span className="s8-eyebrow">КАРТОЧКА АРТИКУЛА</span><h2>{selected.name || selected.sku}</h2><p className="s8-drawer-sub">{selected.brand} · код 1С {selected.sku}</p><div className="s8-drawer-result"><div><small>РЕКОМЕНДОВАНО</small><strong>{selected.recommended_order === null ? '—' : number(selected.recommended_order, 0)} <span>{selected.recommended_order === null ? '' : selected.unit}</span></strong></div><span className={`s8-status s8-status-${selected.status}`}>{statusLabel[selected.status] ?? selected.status}</span></div><div className="s8-drawer-section"><h3>Основа решения</h3><div className="s8-factor"><span>Прогноз за срок поставки</span><strong>{number(selected.forecast)} {selected.unit}</strong></div><div className="s8-factor"><span>Необходимый запас</span><strong>{number(selected.target_stock)} {selected.unit}</strong></div><div className="s8-factor"><span>Текущий остаток</span><strong>{number(selected.current_stock)} {selected.unit}</strong></div><div className="s8-factor"><span>Товар в пути</span><strong>{number(selected.goods_in_transit)} {selected.unit}</strong></div><div className="s8-factor"><span>Правило поставщика</span><strong>{selected.rule_kind === 'multiple' ? 'Кратность' : selected.rule_kind === 'minimum_dispatch' ? 'Минимум отгрузки' : 'Не указано'} {number(selected.rule_quantity, 0)}</strong></div><a className="s8-trace-link" href={traceUrl(selected)} target="_blank" rel="noopener noreferrer">Как получен результат <ExternalLink size={16}/></a></div><div className="s8-drawer-section"><h3>Уточнить данные склада</h3><p>Введите актуальные значения на дату расчёта. Ноль нужно указать явно; данные считаются подтверждёнными вами, без автоматической сверки со складом.</p><div className="s8-fields"><label>Остаток, {selected.unit}<input type="number" min="0" step="any" value={stock} onChange={event => setStock(event.target.value)} placeholder="Например, 9"/></label><label>В пути, {selected.unit}<input type="number" min="0" step="any" value={transit} onChange={event => setTransit(event.target.value)} placeholder="Например, 0"/></label></div><label className="s8-date-label">Дата значений<input type="date" value={asOfDate} onChange={event => setAsOfDate(event.target.value)}/></label>{formError && <p className="s8-form-error" role="alert">{formError}</p>}{formNotice && <p className="s8-form-success" role="status">{formNotice}</p>}<button className="s8-save" onClick={saveStock} disabled={saving}>{saving ? 'Пересчитываем…' : 'Пересчитать рекомендацию'} <ArrowRight size={17}/></button><p className="s8-session-note">Изменение действует в текущем запуске локального сервиса.</p></div></aside></div>}
  </div>;
}

function Metric({ icon, label, value, note, tone = 'normal' }: { icon: ReactNode; label: string; value: string; note: string; tone?: string }) {
  return <div className={`s8-metric s8-metric-${tone}`}><div className="s8-metric-top"><span>{label}</span><i>{icon}</i></div><strong>{value}</strong><small>{note}</small></div>;
}
