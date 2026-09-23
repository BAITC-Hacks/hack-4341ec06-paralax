import { ArrowUpRight, X } from 'lucide-react';
import { catalog } from '../demo/result';
import { productName, productUnit, quantity, supplierName, urgencyLabels } from '../lib/presentation';
import type { Recommendation } from '../types';

type Props = { row: Recommendation | null; onClose: () => void };

export function RecommendationDetail({ row, onClose }: Props) {
  if (!row) {
    return <aside className="detail-panel detail-empty">
      <span className="detail-empty-icon"><ArrowUpRight size={24} /></span>
      <h3>Выберите позицию</h3>
      <p>Здесь появятся факторы и краткое обоснование рекомендации.</p>
    </aside>;
  }

  const item = catalog[row.sku];
  return <aside className="detail-panel" aria-label={`Детали позиции ${row.sku}`}>
    <div className="detail-heading">
      <p className="eyebrow">ДЕТАЛИ ПОЗИЦИИ</p>
      <button type="button" className="icon-button" aria-label="Закрыть детали" onClick={onClose}><X size={18} /></button>
    </div>
    <h2>{productName(row)}</h2>
    <p className="detail-subtitle">{row.sku} · {supplierName(row)}</p>

    <div className="detail-recommendation">
      <span>Рекомендовано заказать</span>
      <strong>{quantity(row.recommended_quantity)} <small>{productUnit(row)}</small></strong>
      <span className={`priority priority-${row.urgency}`}>{urgencyLabels[row.urgency]}</span>
    </div>

    <h3>Почему столько</h3>
    <p className="detail-reason">{row.reason}</p>
    <div className="factor-grid">
      <Factor label="Прогноз на горизонт" value={`${quantity(row.factors.forecast_during_coverage)} ${productUnit(row)}`} />
      <Factor label="Горизонт" value={`${row.factors.coverage_days} дней`} />
      <Factor label="Остаток" value={`${quantity(row.factors.current_stock)} ${productUnit(row)}`} />
      <Factor label="В пути" value={`${quantity(row.factors.goods_in_transit)} ${productUnit(row)}`} />
    </div>
    <div className="detail-note">
      <strong>Источник</strong>
      <span>{item?.stockSource ?? 'Источник не указан'} · {item?.stockDate ?? 'дата не указана'}</span>
      <p>Демонстрационные значения. Решение о заказе принимает менеджер.</p>
    </div>
  </aside>;
}

function Factor({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}
