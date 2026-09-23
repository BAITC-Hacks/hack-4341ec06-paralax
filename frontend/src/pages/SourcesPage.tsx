import { Database, FileSpreadsheet, Layers3, Truck } from 'lucide-react';
import type { ReactNode } from 'react';
import type { PlanningResult } from '../types';

export function SourcesPage({ result }: { result: PlanningResult }) {
  return <>
    <div className="page-heading">
      <div><p className="eyebrow">ДАННЫЕ / ОБЗОР</p><h1>Источники данных</h1>
        <p>Простая структура будущего подключения данных к расчёту.</p></div>
      <span className="subtle-badge">Синтетический набор</span>
    </div>

    <section className="surface source-intro">
      <span className="source-intro-icon"><Database size={22} /></span>
      <div><h2>Текущий интерфейс работает на моках</h2>
        <p>Показан результат <code>{result.run_id}</code> от {result.as_of_date}. Партнёрские Excel и сведения о клиентах не загружаются в браузер.</p></div>
    </section>

    <div className="source-grid">
      <SourceCard icon={<FileSpreadsheet size={21} />} title="Продажи" text="История, выбросы и чистый спрос. В интерфейсе пока используется синтетический результат." />
      <SourceCard icon={<Layers3 size={21} />} title="Остатки" text="Остаток должен иметь дату и охват склада. Месячный снимок не равен текущему остатку." />
      <SourceCard icon={<Truck size={21} />} title="Товар в пути" text="Отдельный источник количества и ожидаемых поступлений, который позже войдёт в расчёт." />
      <SourceCard icon={<Database size={21} />} title="Параметры" text="Сезонность, срок поставки и правила отгрузки показываются вместе с происхождением данных." />
    </div>
  </>;
}

function SourceCard({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return <section className="surface source-card">
    <span className="source-card-icon" aria-hidden="true">{icon}</span>
    <h2>{title}</h2><p>{text}</p>
  </section>;
}
