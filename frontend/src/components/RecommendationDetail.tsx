import { ArrowUpRight, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { Explanation } from "../lib/planningClient";
import {
  flagLabels,
  productName,
  productUnit,
  quantity,
  supplierName,
  urgencyLabels,
} from "../lib/presentation";
import type { Recommendation } from "../types/planning.generated";

type Props = {
  row: Recommendation | null;
  onClose: () => void;
  onSaveQuantity: (sku: string, quantity: number) => Promise<void>;
  onExplain: (sku: string) => Promise<void>;
  explanation: Explanation | null;
  approved: boolean;
  busy: boolean;
};

export function RecommendationDetail({
  row,
  onClose,
  onSaveQuantity,
  onExplain,
  explanation,
  approved,
  busy,
}: Props) {
  const [selectedQuantity, setSelectedQuantity] = useState("");
  useEffect(() => {
    setSelectedQuantity(row ? String(row.selected_quantity) : "");
  }, [row]);

  if (!row) {
    return (
      <aside className="detail-panel detail-empty">
        <span className="detail-empty-icon">
          <ArrowUpRight size={24} />
        </span>
        <h3>Выберите позицию</h3>
        <p>Здесь появятся факторы и обоснование рекомендации.</p>
      </aside>
    );
  }

  const validQuantity =
    /^\d+$/.test(selectedQuantity) &&
    Number.isSafeInteger(Number(selectedQuantity));

  return (
    <aside className="detail-panel" aria-label={`Детали позиции ${row.sku}`}>
      <div className="detail-heading">
        <p className="eyebrow">ДЕТАЛИ ПОЗИЦИИ</p>
        <button
          type="button"
          className="icon-button"
          aria-label="Закрыть детали"
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </div>
      <h2>{productName(row)}</h2>
      <p className="detail-subtitle">
        {row.sku} · {supplierName(row)} · {row.category}
      </p>

      <div className="detail-recommendation">
        <span>Рекомендовано заказать</span>
        <strong>
          {quantity(row.recommended_quantity)} <small>{productUnit(row)}</small>
        </strong>
        <span className={`priority priority-${row.urgency}`}>
          {urgencyLabels[row.urgency]}
        </span>
      </div>

      <h3>Почему столько</h3>
      <p className="detail-reason">{row.reason}</p>
      <div className="factor-grid">
        <Factor
          label="Прогноз на горизонт"
          value={`${quantity(row.factors.forecast_during_coverage)} ${productUnit(row)}`}
        />
        <Factor label="Горизонт" value={`${row.factors.coverage_days} дн.`} />
        <Factor
          label="Страховой запас"
          value={`${quantity(row.factors.safety_stock)} ${productUnit(row)}`}
        />
        <Factor
          label="Остаток"
          value={`${quantity(row.factors.current_stock)} ${productUnit(row)}`}
        />
        <Factor
          label="В пути внутри горизонта"
          value={`${quantity(row.factors.goods_in_transit)} ${productUnit(row)}`}
        />
        <Factor
          label="После горизонта"
          value={`${quantity(row.factors.excluded_late_transit ?? 0)} ${productUnit(row)}`}
        />
        <Factor
          label="Упущенный спрос, оценка"
          value={`${quantity(row.factors.estimated_lost_demand)} ${productUnit(row)}`}
        />
        <Factor
          label="Срок поставки"
          value={
            row.factors.lead_time_days === undefined
              ? "Не указан"
              : `${row.factors.lead_time_days} дн.`
          }
        />
      </div>

      {row.flags.length > 0 && (
        <div className="flag-list" aria-label="Флаги расчёта">
          {row.flags.map((flag) => (
            <span className="subtle-badge" key={flag}>
              {flagLabels[flag]}
            </span>
          ))}
        </div>
      )}
      {row.diagnostics?.quality_warnings.map((warning) => (
        <p className="quality-warning" key={warning}>
          {warning}
        </p>
      ))}

      <div className="detail-note">
        <strong>Источник остатка</strong>
        <span>
          {row.factors.stock_source ?? "Не указан"} ·{" "}
          {row.factors.stock_as_of_date ?? "дата не указана"}
        </span>
        <p>Решение о заказе принимает менеджер.</p>
      </div>

      <div className="detail-actions">
        <label>
          Выбранное количество
          <input
            type="number"
            min="0"
            step="1"
            value={selectedQuantity}
            disabled={approved || busy}
            onChange={(event) => setSelectedQuantity(event.target.value)}
          />
        </label>
        <button
          type="button"
          className="button button-primary"
          disabled={approved || busy || !validQuantity}
          onClick={() => void onSaveQuantity(row.sku, Number(selectedQuantity))}
        >
          Сохранить количество
        </button>
        <button
          type="button"
          className="button button-secondary"
          disabled={busy}
          onClick={() => void onExplain(row.sku)}
        >
          Показать объяснение
        </button>
      </div>
      {explanation && (
        <div className="explanation-panel">
          <strong>
            {explanation.source === "fallback"
              ? "Расчётное объяснение"
              : "AI-объяснение"}
          </strong>
          <p>{explanation.summary}</p>
          <ul>
            {explanation.drivers.map((driver) => (
              <li key={driver}>{driver}</li>
            ))}
          </ul>
          <p>{explanation.risk}</p>
          <p>{explanation.review_question}</p>
        </div>
      )}
    </aside>
  );
}

function Factor({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
