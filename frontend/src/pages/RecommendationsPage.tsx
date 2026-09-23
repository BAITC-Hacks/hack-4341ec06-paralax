import { Search } from "lucide-react";
import { useState } from "react";
import { RecommendationDetail } from "../components/RecommendationDetail";
import type { Explanation } from "../lib/planningClient";
import {
  productName,
  productUnit,
  quantity,
  urgencyLabels,
} from "../lib/presentation";
import type { PlanningResult } from "../types/planning.generated";

type Props = {
  result: PlanningResult;
  selectedSku: string | null;
  onSelectSku: (sku: string | null) => void;
  onSaveQuantity: (sku: string, quantity: number) => Promise<void>;
  onExplain: (sku: string) => Promise<void>;
  explanation: Explanation | null;
  busy: boolean;
};

const urgencyOrder = { critical: 0, high: 1, medium: 2, low: 3 };

export function RecommendationsPage({
  result,
  selectedSku,
  onSelectSku,
  onSaveQuantity,
  onExplain,
  explanation,
  busy,
}: Props) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const normalized = query.trim().toLocaleLowerCase("ru");
  const categories = [
    ...new Set(result.recommendations.map((row) => row.category)),
  ].sort();
  const rows = result.recommendations
    .filter((row) =>
      `${row.sku} ${productName(row)}`
        .toLocaleLowerCase("ru")
        .includes(normalized),
    )
    .filter((row) => !category || row.category === category)
    .sort((a, b) => urgencyOrder[a.urgency] - urgencyOrder[b.urgency]);
  const selected =
    result.recommendations.find((row) => row.sku === selectedSku) ?? null;

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">ПЛАНИРОВАНИЕ / РЕКОМЕНДАЦИИ</p>
          <h1>Рекомендации</h1>
          <p>
            Проверьте факторы и при необходимости измените выбранное количество.
          </p>
        </div>
        <span className="subtle-badge">
          {result.recommendations.length} SKU ·{" "}
          {result.status === "draft" ? "Черновик" : "Утверждён"}
        </span>
      </div>

      <div className="recommendations-layout">
        <section
          className="surface table-surface"
          aria-label="Список рекомендаций"
        >
          <div className="table-toolbar">
            <div>
              <h2>Список позиций</h2>
              <p>Сортировка по срочности</p>
            </div>
            <div className="table-filters">
              <label className="search-field">
                <Search size={17} aria-hidden="true" />
                <span className="sr-only">Найти товар или SKU</span>
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Поиск по товару или SKU"
                />
              </label>
              <label className="category-filter">
                <span className="sr-only">Категория</span>
                <select
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                >
                  <option value="">Все категории</option>
                  {categories.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
          <div className="table-scroll">
            <table className="recommendations-table">
              <thead>
                <tr>
                  <th>Товар</th>
                  <th>Остаток</th>
                  <th>В пути</th>
                  <th>Рекомендовано</th>
                  <th>Выбрано</th>
                  <th>Приоритет</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.sku}
                    className={selectedSku === row.sku ? "selected-row" : ""}
                  >
                    <td>
                      <button
                        type="button"
                        className="product-button"
                        onClick={() => onSelectSku(row.sku)}
                      >
                        <strong>{productName(row)}</strong>
                        <small>{row.sku}</small>
                      </button>
                    </td>
                    <td>
                      {quantity(row.factors.current_stock)}{" "}
                      <span className="table-unit">{productUnit(row)}</span>
                    </td>
                    <td>{quantity(row.factors.goods_in_transit)}</td>
                    <td>{quantity(row.recommended_quantity)}</td>
                    <td>
                      <strong>
                        {quantity(row.selected_quantity)} {productUnit(row)}
                      </strong>
                    </td>
                    <td>
                      <span className={`priority priority-${row.urgency}`}>
                        {urgencyLabels[row.urgency]}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 && (
              <div className="empty-search">По запросу ничего не найдено.</div>
            )}
          </div>
          <p className="table-caption">
            Рекомендованное количество рассчитывает backend; выбранное
            количество сохраняется отдельно.
          </p>
        </section>
        <RecommendationDetail
          row={selected}
          onClose={() => onSelectSku(null)}
          onSaveQuantity={onSaveQuantity}
          onExplain={onExplain}
          explanation={explanation}
          approved={result.status === "approved"}
          busy={busy}
        />
      </div>
    </>
  );
}
