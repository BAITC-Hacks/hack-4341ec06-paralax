import { ArrowRight, CircleAlert, PackageCheck, PackageOpen, Truck } from 'lucide-react';
import type { ReactNode } from 'react';
import { productName, productUnit, quantity, urgencyLabels } from '../lib/presentation';
import type { PlanningResult } from '../types';

type Props = {
  result: PlanningResult;
  onOpenRecommendations: () => void;
  onOpenRecommendation: (sku: string) => void;
};

export function OverviewPage({ result, onOpenRecommendations, onOpenRecommendation }: Props) {
  const rows = result.recommendations;
  const toOrder = rows.filter(row => row.recommended_quantity > 0);
  const highRisk = rows.filter(row => row.urgency === 'critical' || row.urgency === 'high');
  const supplierCount = new Set(toOrder.map(row => row.supplier_id)).size;

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">ОБЗОР / ДЕМО-ДАННЫЕ</p>
          <h1>Планирование закупок</h1>
          <p>Короткая сводка по позициям, которым может понадобиться пополнение.</p>
        </div>
        <button className="button button-primary" type="button" onClick={onOpenRecommendations}>
          Смотреть рекомендации <ArrowRight size={16} aria-hidden="true" />
        </button>
      </div>

      <section className="summary-strip" aria-label="Текущий набор">
        <div><span>НАБОР ДАННЫХ</span><strong>IEK · склад Алматы</strong></div>
        <div><span>ДАТА СРЕЗА</span><strong>{result.as_of_date}</strong></div>
        <div><span>СТАТУС</span><strong className="status-draft">Демо-черновик</strong></div>
        <p>Показаны синтетические значения из мокового результата. Реальный расчёт подключается отдельно.</p>
      </section>

      <section className="metric-grid" aria-label="Сводка рекомендаций">
        <Metric icon={<PackageOpen size={19} />} label="Позиций в наборе" value={quantity(rows.length)} note="все товары" />
        <Metric icon={<PackageCheck size={19} />} label="К пополнению" value={quantity(toOrder.length)} note="количество больше нуля" />
        <Metric icon={<CircleAlert size={19} />} label="Высокий приоритет" value={quantity(highRisk.length)} note="включая критичные" />
        <Metric icon={<Truck size={19} />} label="Поставщиков" value={quantity(supplierCount)} note="в черновике" />
      </section>

      <section className="surface overview-list">
        <div className="section-heading">
          <div><p className="eyebrow">ТРЕБУЮТ ВНИМАНИЯ</p><h2>Ближайшие решения</h2></div>
          <button className="text-link" type="button" onClick={onOpenRecommendations}>Все позиции <ArrowRight size={15} /></button>
        </div>
        {highRisk.map(row => (
          <button className="attention-row" type="button" key={row.sku} onClick={() => onOpenRecommendation(row.sku)}>
            <span className="attention-icon"><PackageOpen size={18} /></span>
            <span className="attention-name"><strong>{productName(row)}</strong><small>{row.sku}</small></span>
            <span className={`priority priority-${row.urgency}`}>{urgencyLabels[row.urgency]}</span>
            <strong className="attention-quantity">{quantity(row.recommended_quantity)} {productUnit(row)}</strong>
            <ArrowRight size={16} className="row-arrow" aria-hidden="true" />
          </button>
        ))}
      </section>
    </>
  );
}

function Metric({ icon, label, value, note }: { icon: ReactNode; label: string; value: string; note: string }) {
  return <div className="metric-card">
    <span className="metric-icon" aria-hidden="true">{icon}</span>
    <span className="metric-label">{label}</span>
    <strong>{value}</strong>
    <small>{note}</small>
  </div>;
}
