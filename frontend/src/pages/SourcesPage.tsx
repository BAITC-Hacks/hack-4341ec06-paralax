import { Database, FileSpreadsheet, Layers3, Truck } from "lucide-react";
import type { ReactNode } from "react";
import type { PlanningResult } from "../types/planning.generated";

export function SourcesPage({ result }: { result: PlanningResult }) {
  const partner = result.data_source === "partner_excel";
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">ДАННЫЕ / ОБЗОР</p>
          <h1>Источники данных</h1>
          <p>Происхождение и допущения текущего расчёта.</p>
        </div>
        <span className="subtle-badge">
          {partner ? "IEK · Excel" : "Синтетический набор"}
        </span>
      </div>

      <section className="surface source-intro">
        <span className="source-intro-icon">
          <Database size={22} />
        </span>
        <div>
          <h2>{partner ? "Расчёт по книгам IEK" : "Синтетический расчёт"}</h2>
          <p>
            Результат <code>{result.run_id}</code> от {result.as_of_date}.
            Склад: {result.warehouse_id}. Исходные Excel не передаются в
            браузер.
          </p>
        </div>
      </section>

      <div className="source-grid">
        <SourceCard
          icon={<FileSpreadsheet size={21} />}
          title="Продажи"
          text="Месячная история и документы по коду 1С. Крупные документы отмечаются отдельно."
        />
        <SourceCard
          icon={<Layers3 size={21} />}
          title="Остатки"
          text="Дата среза остатка указана в деталях артикула. Месячный снимок не равен текущему остатку."
        />
        <SourceCard
          icon={<Truck size={21} />}
          title="Товар в пути"
          text="Поступления после горизонта не уменьшают заказ; проверьте ETA."
        />
        <SourceCard
          icon={<Database size={21} />}
          title="Допущения"
          text="Срок поставки, период пересмотра и страховой запас могут быть сценарными."
        />
      </div>

      {result.source_files && result.source_files.length > 0 && (
        <section className="surface source-list">
          <h2>Файлы источников</h2>
          <ul>
            {result.source_files.map((file) => (
              <li key={file}>{file}</li>
            ))}
          </ul>
        </section>
      )}
      {result.assumptions && result.assumptions.length > 0 && (
        <section className="surface source-list">
          <h2>Допущения</h2>
          <ul>
            {result.assumptions.map((assumption) => (
              <li key={assumption}>{assumption}</li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function SourceCard({
  icon,
  title,
  text,
}: {
  icon: ReactNode;
  title: string;
  text: string;
}) {
  return (
    <section className="surface source-card">
      <span className="source-card-icon" aria-hidden="true">
        {icon}
      </span>
      <h2>{title}</h2>
      <p>{text}</p>
    </section>
  );
}
