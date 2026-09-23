import { ClipboardList, Info } from "lucide-react";
import {
  productName,
  productUnit,
  quantity,
  supplierName,
} from "../lib/presentation";
import type { PlanningResult } from "../types/planning.generated";

type Props = {
  result: PlanningResult;
  onApprove: () => Promise<void>;
  onExport: () => Promise<void>;
  busy: boolean;
};

export function OrdersPage({ result, onApprove, onExport, busy }: Props) {
  const rows = result.recommendations.filter(
    (row) => row.selected_quantity > 0,
  );
  const supplierIds = [...new Set(rows.map((row) => row.supplier_id))];

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">ЗАКУПКИ / ЧЕРНОВИК</p>
          <h1>Черновик заказа</h1>
          <p>Проверьте выбранные количества перед утверждением.</p>
        </div>
        <span className="subtle-badge">
          {result.status === "draft" ? "Черновик" : "Утверждён"}
        </span>
      </div>

      <div className="order-layout">
        <div className="order-stack">
          {supplierIds.length === 0 && (
            <section className="surface empty-search">
              Нет позиций с выбранным количеством больше нуля.
            </section>
          )}
          {supplierIds.map((supplierId) => {
            const supplierRows = rows.filter(
              (row) => row.supplier_id === supplierId,
            );
            return (
              <section className="surface order-card" key={supplierId}>
                <div className="order-card-heading">
                  <span className="order-icon">
                    <ClipboardList size={21} />
                  </span>
                  <div>
                    <span>ПОСТАВЩИК</span>
                    <h2>{supplierName(supplierRows[0])}</h2>
                    <p>{result.run_id}</p>
                  </div>
                  <span className="status-pill">
                    {result.status === "draft" ? "Черновик" : "Утверждён"}
                  </span>
                </div>
                <div className="order-lines">
                  {supplierRows.map((row) => (
                    <div className="order-line" key={row.sku}>
                      <div>
                        <strong>{productName(row)}</strong>
                        <small>
                          {row.sku} · рекомендовано{" "}
                          {quantity(row.recommended_quantity)}
                        </small>
                      </div>
                      <strong>
                        {quantity(row.selected_quantity)} {productUnit(row)}
                      </strong>
                    </div>
                  ))}
                </div>
                <div className="order-total">
                  <span>Позиций в черновике</span>
                  <strong>{quantity(supplierRows.length)}</strong>
                </div>
              </section>
            );
          })}
        </div>

        <aside className="surface placeholder-card">
          <span className="placeholder-icon">
            <Info size={20} />
          </span>
          <h2>Решение менеджера</h2>
          <p>
            Утверждение фиксирует выбранные количества. CSV скачивается
            локально; заказ поставщику не отправляется.
          </p>
          <div className="order-actions">
            <button
              className="button button-primary"
              type="button"
              disabled={busy || result.status === "approved"}
              onClick={() => void onApprove()}
            >
              {result.status === "approved"
                ? "Утверждено"
                : "Утвердить черновик"}
            </button>
            <button
              className="button button-secondary"
              type="button"
              disabled={busy}
              onClick={() => void onExport()}
            >
              Скачать CSV
            </button>
          </div>
        </aside>
      </div>
    </>
  );
}
