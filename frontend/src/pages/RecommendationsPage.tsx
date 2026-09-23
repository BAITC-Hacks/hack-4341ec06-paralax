import { Search } from 'lucide-react';
import { useState } from 'react';
import { RecommendationDetail } from '../components/RecommendationDetail';
import { productName, productUnit, quantity, urgencyLabels } from '../lib/presentation';
import type { PlanningResult } from '../types';

type Props = {
  result: PlanningResult;
  selectedSku: string | null;
  onSelectSku: (sku: string | null) => void;
};

export function RecommendationsPage({ result, selectedSku, onSelectSku }: Props) {
  const [query, setQuery] = useState('');
  const normalized = query.trim().toLocaleLowerCase('ru');
  const rows = result.recommendations.filter(row =>
    `${row.sku} ${productName(row)}`.toLocaleLowerCase('ru').includes(normalized));
  const selected = result.recommendations.find(row => row.sku === selectedSku) ?? null;

  return <>
    <div className="page-heading">
      <div><p className="eyebrow">ПЛАНИРОВАНИЕ / РЕКОМЕНДАЦИИ</p><h1>Рекомендации</h1>
        <p>Проверьте количество и откройте позицию, чтобы увидеть основание.</p></div>
      <span className="subtle-badge">Демо · {result.recommendations.length} позиции</span>
    </div>

    <div className="recommendations-layout">
      <section className="surface table-surface" aria-label="Список рекомендаций">
        <div className="table-toolbar">
          <div><h2>Список позиций</h2><p>Синтетические рекомендации по IEK</p></div>
          <label className="search-field">
            <Search size={17} aria-hidden="true" />
            <span className="sr-only">Найти товар или SKU</span>
            <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Поиск по товару или SKU" />
          </label>
        </div>
        <div className="table-scroll">
          <table className="recommendations-table">
            <thead><tr><th>Товар</th><th>Остаток</th><th>В пути</th><th>Заказать</th><th>Приоритет</th></tr></thead>
            <tbody>
              {rows.map(row => (
                <tr key={row.sku} className={selectedSku === row.sku ? 'selected-row' : ''}>
                  <td><button type="button" className="product-button" onClick={() => onSelectSku(row.sku)}>
                    <strong>{productName(row)}</strong><small>{row.sku}</small>
                  </button></td>
                  <td>{quantity(row.factors.current_stock)} <span className="table-unit">{productUnit(row)}</span></td>
                  <td>{quantity(row.factors.goods_in_transit)}</td>
                  <td><strong>{quantity(row.recommended_quantity)} {productUnit(row)}</strong></td>
                  <td><span className={`priority priority-${row.urgency}`}>{urgencyLabels[row.urgency]}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <div className="empty-search">По запросу ничего не найдено.</div>}
        </div>
        <p className="table-caption">Количество и приоритет взяты из мокового PlanningResult. Интерфейс их не рассчитывает.</p>
      </section>
      <RecommendationDetail row={selected} onClose={() => onSelectSku(null)} />
    </div>
  </>;
}
