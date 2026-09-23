import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Activity, ArrowDownToLine, ArrowRight, BarChart3, Boxes, Check, ChevronDown, ChevronRight, CircleAlert, Clock3, FileCheck2, FileSpreadsheet, Info, Layers3, Menu, Package, Search, ShieldCheck, SlidersHorizontal, Sparkles, Truck, X } from 'lucide-react';
import { Button } from './components/Button';
import { catalog, suppliers } from './demo/result';
import { previewTransit } from './lib/planning.mjs';
import { isDemo, planningClient } from './lib/planningClient';
import type { Flag, PlanningResult, Recommendation, Urgency } from './types';

type Screen = 'planning' | 'orders' | 'sources';
const urgencyLabels: Record<Urgency, string> = { critical: 'Критично', high: 'Высокий', medium: 'Средний', low: 'Низкий' };
const flagLabels: Record<Flag, string> = { one_off_sale: 'Крупный документ', stockout_adjustment: 'Компенсация дефицита', seasonality: 'Сезонность', growth: 'Рост спроса', short_history: 'Короткая история', missing_data: 'Неполные данные' };
const number = (value: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(value);

export default function App() {
  const [screen, setScreen] = useState<Screen>('planning');
  const [run, setRun] = useState<PlanningResult | null>(planningClient.restore);
  const [busy, setBusy] = useState<'calculate' | 'save' | 'approve' | 'export' | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('Все категории');
  const [urgency, setUrgency] = useState('Все приоритеты');
  const [selectedSku, setSelectedSku] = useState<string | null>(null);
  const [draftQuantity, setDraftQuantity] = useState('');
  const [transitDraft, setTransitDraft] = useState('');
  const [mobileNav, setMobileNav] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const selected = run?.recommendations.find(row => row.sku === selectedSku) ?? null;
  const categories = [...new Set(Object.values(catalog).map(item => item.category))];
  const filtered = useMemo(() => (run?.recommendations ?? []).filter(row => {
    const item = catalog[row.sku];
    return (category === 'Все категории' || item?.category === category) && (urgency === 'Все приоритеты' || row.urgency === urgency) && `${row.sku} ${item?.name ?? ''}`.toLowerCase().includes(query.toLowerCase());
  }), [run, category, urgency, query]);
  const grouped = groupRows(filtered);
  const urgentCount = run?.recommendations.filter(row => row.urgency === 'critical' || row.urgency === 'high').length ?? 0;
  const totalQuantity = run?.recommendations.reduce((sum, row) => sum + row.selected_quantity, 0) ?? 0;
  const editedCount = run?.recommendations.filter(row => row.selected_quantity !== row.recommended_quantity).length ?? 0;

  useEffect(() => {
    if (!selectedSku) return;
    closeRef.current?.focus();
    function onEscape(event: KeyboardEvent) { if (event.key === 'Escape') setSelectedSku(null); }
    window.addEventListener('keydown', onEscape);
    return () => window.removeEventListener('keydown', onEscape);
  }, [selectedSku]);
  function showDetail(row: Recommendation) {
    setSelectedSku(row.sku);
    setDraftQuantity(String(row.selected_quantity));
    setTransitDraft(String(row.factors.goods_in_transit));
    setError('');
  }
  async function calculate() {
    if (run && !window.confirm('Создать новый расчёт? Текущие правки и статус демо-заказа будут заменены.')) return;
    setBusy('calculate'); setError(''); setNotice(''); setSelectedSku(null);
    try { setRun(await planningClient.create()); setScreen('planning'); setNotice('Расчёт готов. Проверьте рекомендации перед утверждением.'); }
    catch (cause) { setError(message(cause)); }
    finally { setBusy(null); }
  }
  async function saveQuantity() {
    if (!run || !selected) return;
    const value = Number(draftQuantity);
    if (draftQuantity.trim() === '' || !Number.isSafeInteger(value) || value < 0) { setError('Введите целое неотрицательное количество.'); return; }
    setBusy('save'); setError('');
    try { setRun(await planningClient.updateQuantity(run, selected.sku, value)); setNotice(`Выбранное количество для ${selected.sku} сохранено. Исходная рекомендация не изменилась.`); }
    catch (cause) { setError(message(cause)); }
    finally { setBusy(null); }
  }
  async function approve() {
    if (!run || run.status === 'approved') return;
    setBusy('approve'); setError('');
    try { setRun(await planningClient.approve(run)); setSelectedSku(null); setScreen('orders'); setNotice('Черновик утверждён. Экспортируйте CSV для дальнейшей обработки; поставщику заказ не отправлен.'); }
    catch (cause) { setError(message(cause)); }
    finally { setBusy(null); }
  }
  async function exportRun() {
    if (!run) return;
    setBusy('export'); setError('');
    try {
      const blob = await planningClient.export(run);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url; link.download = `paralax-${run.run_id}.csv`; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice('CSV подготовлен. Экспорт не отправляет заказ поставщику.');
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(null); }
  }
  const transit = Number(transitDraft);
  const validTransit = transitDraft.trim() !== '' && Number.isSafeInteger(transit) && transit >= 0;
  let transitPreview: number | null = null;
  if (selected && validTransit && isDemo) {
    try { transitPreview = previewTransit(selected, transit); } catch { transitPreview = null; }
  }
  return <div className="app-shell">
    <aside className={`sidebar ${mobileNav ? 'sidebar-open' : ''}`}>
      <a className="brand" href="#planning" onClick={event => { event.preventDefault(); setScreen('planning'); setMobileNav(false); }}><span className="brand-mark"><Layers3 size={23}/></span><span>paralax<small>SUPPLY INTELLIGENCE</small></span></a>
      <div className="sidebar-section-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <nav aria-label="Основная навигация"><NavItem icon={<BarChart3 size={18}/>} label="Планирование" active={screen === 'planning'} onClick={() => { setScreen('planning'); setMobileNav(false); }}/><NavItem icon={<FileCheck2 size={18}/>} label="Заказы" active={screen === 'orders'} onClick={() => { setScreen('orders'); setMobileNav(false); }} badge={run?.status === 'approved' ? '1' : undefined}/><NavItem icon={<Boxes size={18}/>} label="Источники данных" active={screen === 'sources'} onClick={() => { setScreen('sources'); setMobileNav(false); }}/></nav>
      <div className="sidebar-spacer"/>
      <div className="sidebar-callout"><span className="callout-icon"><Sparkles size={18}/></span><h3>Решение остаётся за вами</h3><p>Система предлагает количество и показывает расчёт. Заказ утверждает менеджер.</p></div>
      <div className="sidebar-profile"><span className="profile-avatar">МЗ</span><div><strong>Менеджер закупок</strong><small>Рабочее демо</small></div><ChevronDown size={14}/></div>
    </aside>
    <div className="main-shell"><header className="topbar"><button className="menu-button" aria-label="Открыть меню" onClick={() => setMobileNav(!mobileNav)}><Menu size={20}/></button><div className="breadcrumbs">Рабочее пространство <ChevronRight size={14}/> <strong>{screen === 'planning' ? 'Планирование' : screen === 'orders' ? 'Заказы' : 'Источники данных'}</strong></div><div className="topbar-right"><span className="demo-indicator"><span/> {isDemo ? 'Синтетический демо-набор' : 'API подключён'}</span><span className="top-avatar">МЗ</span></div></header>
      <main><div className="page-heading"><div><div className="eyebrow">HACKALEM AI <span>/</span> ЭЛЕКТРОКОМПЛЕКТ</div><h1>{screen === 'planning' ? 'Планирование закупок' : screen === 'orders' ? 'Заказы поставщикам' : 'Источники данных'}</h1><p>{screen === 'planning' ? 'Рекомендации для пополнения склада на основе проверяемых факторов.' : screen === 'orders' ? 'Черновик и решение менеджера в одном месте.' : 'Состав и ограничения данных текущего демо-сценария.'}</p></div><span className="heading-symbol"><Activity size={25}/></span></div>
      {notice && <div className="notice success" role="status"><Check size={18}/><span>{notice}</span><button onClick={() => setNotice('')} aria-label="Закрыть уведомление"><X size={16}/></button></div>}
      {error && <div className="notice error" role="alert"><CircleAlert size={18}/><span>{error}</span><button onClick={() => setError('')} aria-label="Закрыть ошибку"><X size={16}/></button></div>}
      {screen === 'planning' && <>
        <section className="run-panel"><div className="run-intro"><span className="run-icon"><FileSpreadsheet size={23}/></span><div><strong>Набор для расчёта</strong><span>{isDemo ? 'Синтетические данные IEK · склад Алматы' : 'Подключённый набор API · склад Алматы'}</span></div></div><div className="run-meta"><span>ДАТА СРЕЗА</span><strong>{run?.as_of_date ?? '23 сентября 2026'}</strong></div><div className="run-meta"><span>СТАТУС</span><strong className={run?.status === 'approved' ? 'approved-text' : ''}>{run?.status === 'approved' ? 'Утверждён' : run ? 'Черновик' : 'Ожидает расчёта'}</strong></div><Button onClick={calculate} disabled={busy !== null}>{busy === 'calculate' ? <span className="spinner"/> : <Sparkles size={17}/>} {busy === 'calculate' ? 'Расчёт…' : run ? 'Рассчитать заново' : 'Запустить расчёт'}</Button></section>
        {!run ? <section className="start-state"><div className="start-art"><Package size={42}/></div><span className="eyebrow">ГОТОВО К АНАЛИЗУ</span><h2>Начните с расчёта потребности</h2><p>Откройте синтетический набор IEK, чтобы увидеть рекомендации, факторы и черновик заказа. Вы сможете изменить количество перед утверждением.</p><Button onClick={calculate} disabled={busy !== null}>{busy === 'calculate' ? 'Расчёт…' : 'Рассчитать потребность'}<ArrowRight size={17}/></Button></section> : <>
        <div className="metrics"><Metric icon={<Package size={19}/>} label="Позиций в расчёте" value={String(run.recommendations.length)} detail="артикулов IEK"/><Metric icon={<Clock3 size={19}/>} label="Требуют внимания" value={String(urgentCount)} detail="высокий и критичный риск" tone="amber"/><Metric icon={<Truck size={19}/>} label="К заказу" value={number(totalQuantity)} detail="единиц в выбранном количестве"/><Metric icon={<SlidersHorizontal size={19}/>} label="Изменено вручную" value={String(editedCount)} detail="позиций после проверки"/></div>
        <section className="insight"><div className="insight-icon"><Sparkles size={21}/></div><div><strong>Рекомендации с понятным основанием</strong><p>Для каждой позиции видны прогноз, остаток, товары в пути и поправки. {isDemo ? 'Сейчас показан фиксированный синтетический результат по контракту.' : 'Количество получено от серверного модуля расчёта.'}</p></div><span className="insight-tag">Проверяемые факторы</span></section>
        <section className="table-card"><div className="table-header"><div><div className="eyebrow">РЕЗУЛЬТАТ РАСЧЁТА</div><h2>Рекомендации к заказу <span>{filtered.length}</span></h2><p>Проверьте детали каждой строки перед утверждением.</p></div><Button variant="secondary" onClick={exportRun} disabled={busy !== null}><ArrowDownToLine size={16}/>Экспорт CSV</Button></div><div className="table-toolbar"><label className="search"><Search size={18}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Поиск по артикулу или названию" aria-label="Поиск по артикулу или названию"/></label><label className="select-wrap"><span>Категория</span><select value={category} onChange={event => setCategory(event.target.value)}>{['Все категории', ...categories].map(value => <option key={value}>{value}</option>)}</select></label><label className="select-wrap"><span>Приоритет</span><select value={urgency} onChange={event => setUrgency(event.target.value)}><option>Все приоритеты</option>{(Object.keys(urgencyLabels) as Urgency[]).map(value => <option key={value} value={value}>{urgencyLabels[value]}</option>)}</select></label></div>
        {filtered.length === 0 ? <div className="table-empty"><Search size={30}/><h3>Позиции не найдены</h3><p>Измените поиск или фильтры, чтобы увидеть рекомендации.</p><Button variant="secondary" onClick={() => { setQuery(''); setCategory('Все категории'); setUrgency('Все приоритеты'); }}>Сбросить фильтры</Button></div> : <div className="table-scroll"><table><thead><tr><th>Товар и код 1С</th><th>Остаток</th><th>В пути</th><th>Рекомендовано</th><th>Выбрано</th><th>Приоритет</th><th>Проверка</th><th aria-label="Действие"/></tr></thead>{grouped.map(([supplierId, rows]) => <tbody key={supplierId}><tr className="supplier-row"><td colSpan={8}><Truck size={17}/><strong>{suppliers[supplierId] ?? supplierId}</strong><span>{rows?.length ?? 0} позиции</span></td></tr>{rows?.map(row => <tr key={row.sku}><td><button className="product-link" onClick={() => showDetail(row)}>{catalog[row.sku]?.name ?? row.sku}</button><small>{row.sku} · {catalog[row.sku]?.category ?? 'Категория не указана'}</small></td><td>{number(row.factors.current_stock)}<small>{catalog[row.sku]?.unit ?? 'ед.'}</small></td><td>{number(row.factors.goods_in_transit)}<small>{catalog[row.sku]?.unit ?? 'ед.'}</small></td><td className="recommended">{number(row.recommended_quantity)}<small>{catalog[row.sku]?.unit ?? 'ед.'}</small></td><td><strong className={row.selected_quantity !== row.recommended_quantity ? 'edited-quantity' : ''}>{number(row.selected_quantity)}</strong>{row.selected_quantity !== row.recommended_quantity && <small>Изменено вручную</small>}</td><td><span className={`urgency urgency-${row.urgency}`}>{urgencyLabels[row.urgency]}</span></td><td><div className="flag-cell">{row.flags.length ? <><span className="flag-dot"/> {flagLabels[row.flags[0]]}</> : <span className="muted">Без флагов</span>}</div></td><td><button className="row-action" aria-label={`Открыть детали ${row.sku}`} onClick={() => showDetail(row)}><ArrowRight size={17}/></button></td></tr>)}</tbody>)}</table></div>}
        <div className="table-footer"><div><ShieldCheck size={17}/><span>{run.status === 'approved' ? 'Заказ утверждён. Поставщику ничего не отправлено.' : 'Изменения сохраняются в черновике. Поставщику ничего не отправляется.'}</span></div><Button onClick={approve} disabled={busy !== null || run.status === 'approved'}><Check size={17}/>{run.status === 'approved' ? 'Заказ утверждён' : busy === 'approve' ? 'Утверждение…' : 'Утвердить черновик'}</Button></div></section>
        </>}
      </>}
        {screen === 'orders' && <section className="table-card orders-card"><div className="table-header"><div><div className="eyebrow">РЕШЕНИЕ МЕНЕДЖЕРА</div><h2>{run?.status === 'approved' ? 'Утверждённый заказ' : 'Черновик заказа'}</h2><p>{run ? `Расчёт ${run.run_id} · срез ${run.as_of_date}` : 'Сначала выполните расчёт потребности.'}</p></div>{run && <Button variant="secondary" onClick={exportRun} disabled={busy !== null}><ArrowDownToLine size={16}/>Экспорт CSV</Button>}</div>{!run ? <div className="table-empty"><FileCheck2 size={34}/><h3>Черновик ещё не создан</h3><p>Запустите расчёт, чтобы сформировать рекомендации.</p><Button onClick={() => setScreen('planning')}>К планированию<ArrowRight size={16}/></Button></div> : <><div className="order-status"><span className={`status-puck ${run.status}`}>{run.status === 'approved' ? <Check size={18}/> : <Clock3 size={18}/>}</span><div><strong>{run.status === 'approved' ? 'Утверждено менеджером' : 'Ожидает проверки'}</strong><p>{run.status === 'approved' ? 'Заказ готов к экспорту. Автоматическая отправка поставщику не выполняется.' : 'Просмотрите детали и измените выбранное количество, затем утвердите черновик.'}</p></div></div>{groupRows(run.recommendations).map(([supplierId, rows]) => <div className="order-group" key={supplierId}><h3><Truck size={18}/>{suppliers[supplierId] ?? supplierId}</h3>{rows.map(row => <div className="order-line" key={row.sku}><div><strong>{catalog[row.sku]?.name ?? row.sku}</strong><small>{row.sku}</small></div><div><span>Рекомендовано {number(row.recommended_quantity)}</span><strong>Выбрано {number(row.selected_quantity)} {catalog[row.sku]?.unit ?? 'ед.'}</strong></div></div>)}</div>)}<div className="order-bottom"><span>Итого выбранное количество <strong>{number(totalQuantity)} ед.</strong></span>{run.status === 'draft' && <Button onClick={approve} disabled={busy !== null}><Check size={17}/>Утвердить черновик</Button>}</div></> }</section>}
      {screen === 'sources' && <><section className="source-banner"><span><Boxes size={26}/></span><div><h2>{isDemo ? 'Синтетический набор IEK' : 'Данные расчёта через API'}</h2><p>Демо показывает структуру результата и путь решения менеджера. Партнёрские Excel и персональные данные не загружаются в браузер.</p></div></section><div className="source-grid"><SourceCard number="01" title="Продажи" text="Синтетическая история по кодам 1С. Разовая крупная отгрузка отмечена как документ; связь с клиентом не утверждается."/><SourceCard number="02" title="Остатки" text="Дата и источник среза показываются в деталях позиции. Месячные остатки не выдаются за актуальные."/><SourceCard number="03" title="Товары в пути" text="Вычитаются из целевой потребности. В демо можно проверить, как их изменение влияет на рекомендацию."/><SourceCard number="04" title="Сезонность и рост" text="Коэффициенты видны в панели факторов. Их источник и точность должны быть подтверждены на реальных данных."/><SourceCard number="05" title="Дефицит" text="Точное число упущенных продаж в демо синтетическое. Для месячных нулевых остатков нужен отдельный флаг неопределённости."/><SourceCard number="06" title="AI-объяснение" text="Серверная интеграция готовится отдельно. UI показывает резервное объяснение из проверенных факторов."/></div></>}
      <footer><span>Paralax · HackAlem AI</span><span>Демонстрационный интерфейс · заказ требует решения человека</span><span>2026</span></footer></main></div>
    {selected && <div className="drawer-overlay" onMouseDown={event => { if (event.target === event.currentTarget) setSelectedSku(null); }}><section className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title"><button ref={closeRef} className="drawer-close" aria-label="Закрыть детали" onClick={() => setSelectedSku(null)}><X size={20}/></button><div className="eyebrow">РАЗБОР ПОЗИЦИИ</div><h2 id="drawer-title">{catalog[selected.sku]?.name ?? selected.sku}</h2><p className="drawer-subtitle">Код 1С: {selected.sku} · {suppliers[selected.supplier_id] ?? selected.supplier_id}</p><div className="drawer-hero"><div><span>Рекомендовано заказать</span><strong>{number(selected.recommended_quantity)} <small>{catalog[selected.sku]?.unit ?? 'ед.'}</small></strong></div><span className={`urgency urgency-${selected.urgency}`}>{urgencyLabels[selected.urgency]}</span></div><div className="drawer-section"><h3>Почему столько</h3><p className="reason">{selected.reason}</p><div className="factor-list"><Factor label="Регулярный спрос" value={`${number(selected.factors.regular_daily_demand)} ед./день`}/><Factor label="Сезонность" value={`× ${number(selected.factors.seasonality_multiplier)}`}/><Factor label="Устойчивый тренд" value={`× ${number(selected.factors.trend_multiplier)}`}/><Factor label="Внешний прогноз роста" value={`× ${number(selected.factors.external_growth_multiplier)}`}/><Factor label="Оценка упущенного спроса" value={`${number(selected.factors.estimated_lost_demand)} ед.`}/><Factor label="Горизонт покрытия" value={`${selected.factors.coverage_days} дней`}/><Factor label="Прогноз на горизонт" value={`${number(selected.factors.forecast_during_coverage)} ед.`}/><Factor label="Страховой запас" value={`${number(selected.factors.safety_stock)} ед.`}/><Factor label="Остаток" value={`− ${number(selected.factors.current_stock)} ед.`}/><Factor label="Товар в пути" value={`− ${number(selected.factors.goods_in_transit)} ед.`}/></div><div className="formula">max(0, ⌈{number(selected.factors.forecast_during_coverage)} + {number(selected.factors.safety_stock)} − {number(selected.factors.current_stock)} − {number(selected.factors.goods_in_transit)}⌉) = <strong>{number(selected.recommended_quantity)}</strong></div></div>
      <div className="drawer-section"><h3>Источник и ограничения</h3><div className="source-note"><Info size={17}/><span>{catalog[selected.sku]?.stockSource ?? 'Источник не указан'} · {catalog[selected.sku]?.stockDate ?? run?.as_of_date}. {catalog[selected.sku]?.note ?? 'Синтетические данные для демонстрации интерфейса.'}</span></div>{selected.flags.length > 0 && <div className="flag-list">{selected.flags.map(flag => <span key={flag}>{flagLabels[flag]}</span>)}</div>}<p className="fallback-caption">Объяснение построено из проверенных факторов. Серверный AI-ответ пока не подключён.</p></div>
      {isDemo && <div className="drawer-section scenario"><h3>Проверка «товар в пути»</h3><p>Измените значение для предварительного сценария. Исходный расчёт и черновик не меняются.</p><label htmlFor="transit-input">Количество в пути, ед.</label><input id="transit-input" type="number" min="0" step="1" value={transitDraft} onChange={event => setTransitDraft(event.target.value)}/>{validTransit && transitPreview !== null ? <div className="scenario-result"><span>Рекомендация в сценарии</span><strong>{number(transitPreview)} ед.</strong></div> : <p className="field-error">Введите целое неотрицательное число.</p>}</div>}
      <div className="drawer-section quantity-section"><h3>Решение менеджера</h3><p>Изменение количества сохраняется отдельно от рекомендации системы.</p><div className="quantity-comparison"><div><small>РЕКОМЕНДОВАНО</small><strong>{number(selected.recommended_quantity)}</strong></div><div><small>ВЫБРАНО</small><strong>{number(selected.selected_quantity)}</strong></div></div><label htmlFor="quantity-input">Выбранное количество, {catalog[selected.sku]?.unit ?? 'ед.'}</label><div className="quantity-actions"><input id="quantity-input" type="number" min="0" step="1" value={draftQuantity} onChange={event => setDraftQuantity(event.target.value)} disabled={run?.status === 'approved'}/><Button onClick={saveQuantity} disabled={run?.status === 'approved' || busy !== null || draftQuantity === String(selected.selected_quantity)}>{busy === 'save' ? 'Сохранение…' : 'Сохранить правку'}</Button></div></div></section></div>}
  </div>;
}

function message(cause: unknown) { return cause instanceof Error ? cause.message : 'Не удалось выполнить действие. Повторите попытку.'; }
function NavItem({ icon, label, active, onClick, badge }: { icon: ReactNode; label: string; active: boolean; onClick: () => void; badge?: string }) { return <button className={`nav-item ${active ? 'active' : ''}`} onClick={onClick}>{icon}<span>{label}</span>{badge && <em>{badge}</em>}</button>; }
function Metric({ icon, label, value, detail, tone = 'green' }: { icon: ReactNode; label: string; value: string; detail: string; tone?: string }) { return <section className="metric"><div><span>{label}</span><span className={`metric-icon ${tone}`}>{icon}</span></div><strong>{value}</strong><small>{detail}</small></section>; }
function Factor({ label, value }: { label: string; value: string }) { return <div className="factor"><span>{label}</span><strong>{value}</strong></div>; }
function SourceCard({ number, title, text }: { number: string; title: string; text: string }) { return <section className="source-card"><span>{number}</span><h3>{title}</h3><p>{text}</p></section>; }
function groupRows(rows: Recommendation[]): [string, Recommendation[]][] {
  const groups = new Map<string, Recommendation[]>();
  for (const row of rows) groups.set(row.supplier_id, [...(groups.get(row.supplier_id) ?? []), row]);
  return [...groups.entries()];
}
