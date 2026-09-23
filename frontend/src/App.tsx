import { useEffect, useState } from "react";
import {
  BarChart3,
  ClipboardList,
  Database,
  LayoutDashboard,
} from "lucide-react";
import {
  approveRun,
  createRun,
  explainRun,
  exportRun,
  readRun,
  updateQuantity,
  type Dataset,
  type Explanation,
} from "./lib/planningClient";
import { OrdersPage } from "./pages/OrdersPage";
import { OverviewPage } from "./pages/OverviewPage";
import { RecommendationsPage } from "./pages/RecommendationsPage";
import { SourcesPage } from "./pages/SourcesPage";
import type { PlanningResult } from "./types/planning.generated";

type Page = "overview" | "recommendations" | "orders" | "sources";
const STORAGE_KEY = "paralax.run-id";

const navigation = [
  { id: "overview", label: "Обзор", icon: LayoutDashboard },
  { id: "recommendations", label: "Рекомендации", icon: BarChart3 },
  { id: "orders", label: "Черновик заказа", icon: ClipboardList },
  { id: "sources", label: "Источники", icon: Database },
] as const;

const pageTitles: Record<Page, string> = {
  overview: "Обзор",
  recommendations: "Рекомендации",
  orders: "Черновик заказа",
  sources: "Источники данных",
};

function message(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Неизвестная ошибка. Повторите действие.";
}

export default function App() {
  const [page, setPage] = useState<Page>("overview");
  const [dataset, setDataset] = useState<Dataset>("synthetic");
  const [run, setRun] = useState<PlanningResult | null>(null);
  const [selectedSku, setSelectedSku] = useState<string | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const runId = sessionStorage.getItem(STORAGE_KEY);
    if (!runId) return;
    let active = true;
    readRun(runId)
      .then((restored) => {
        if (active) {
          setRun(restored);
          setDataset(
            restored.data_source === "partner_excel" ? "iek" : "synthetic",
          );
        }
      })
      .catch(() => sessionStorage.removeItem(STORAGE_KEY));
    return () => {
      active = false;
    };
  }, []);

  async function act(
    label: string,
    action: () => Promise<void>,
  ): Promise<void> {
    setBusy(label);
    setError("");
    try {
      await action();
    } catch (failure) {
      setError(message(failure));
    } finally {
      setBusy("");
    }
  }

  async function calculate(): Promise<void> {
    await act("Расчёт", async () => {
      const created = await createRun(dataset);
      setRun(created);
      setSelectedSku(null);
      setExplanation(null);
      setPage("overview");
      sessionStorage.setItem(STORAGE_KEY, created.run_id);
    });
  }

  async function saveQuantity(sku: string, quantity: number): Promise<void> {
    if (!run) return;
    await act("Сохранение", async () => {
      setRun(await updateQuantity(run.run_id, sku, quantity));
    });
  }

  async function approve(): Promise<void> {
    if (!run) return;
    await act("Утверждение", async () => {
      setRun(await approveRun(run.run_id));
    });
  }

  async function download(): Promise<void> {
    if (!run) return;
    await act("Экспорт", async () => {
      const blob = await exportRun(run.run_id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `planning-${run.run_id}.csv`;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }

  async function explain(sku: string): Promise<void> {
    if (!run) return;
    setExplanation(null);
    await act("Объяснение", async () => {
      setExplanation(await explainRun(run.run_id, sku));
    });
  }

  function openRecommendation(sku: string): void {
    setSelectedSku(sku);
    setExplanation(null);
    setPage("recommendations");
  }

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="brand-block">
          <span className="brand-symbol" aria-hidden="true">
            p.
          </span>
          <div>
            <strong>paralax</strong>
            <small>ПЛАНИРОВАНИЕ ЗАКУПОК</small>
          </div>
        </div>
        <p className="nav-caption">РАБОЧЕЕ ПРОСТРАНСТВО</p>
        <nav className="primary-nav" aria-label="Основная навигация">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button
              type="button"
              key={id}
              className={page === id ? "nav-link active" : "nav-link"}
              aria-current={page === id ? "page" : undefined}
              onClick={() => setPage(id)}
            >
              <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="demo-dot" aria-hidden="true" />
          <div>
            <strong>
              {run?.data_source === "partner_excel"
                ? "IEK"
                : "Синтетический набор"}
            </strong>
            <small>
              {run ? `${run.recommendations.length} SKU` : "Расчёт не запущен"}
            </small>
          </div>
        </div>
      </aside>

      <div className="content-shell">
        <header className="topbar">
          <span className="breadcrumb">
            Рабочее пространство <span>/</span>{" "}
            <strong>{pageTitles[page]}</strong>
          </span>
          <div className="topbar-controls">
            <label className="dataset-control">
              Набор
              <select
                value={dataset}
                disabled={Boolean(busy)}
                onChange={(event) => setDataset(event.target.value as Dataset)}
              >
                <option value="synthetic">Синтетический</option>
                <option value="iek">IEK · Excel</option>
              </select>
            </label>
            <button
              className="button button-primary"
              type="button"
              disabled={Boolean(busy)}
              onClick={() => void calculate()}
            >
              {busy === "Расчёт" ? "Считаем…" : "Рассчитать"}
            </button>
          </div>
        </header>

        <main className="page-content">
          {error && (
            <div className="error-banner" role="alert">
              {error}
            </div>
          )}
          {busy && (
            <p className="loading-message" role="status">
              {busy}…{" "}
              {busy === "Расчёт" && dataset === "iek"
                ? "Чтение Excel может занять около минуты."
                : ""}
            </p>
          )}
          {!run ? (
            <section className="surface start-panel">
              <p className="eyebrow">ПЛАН ЗАКУПОК</p>
              <h1>Подготовьте черновик заказа</h1>
              <p>
                Выберите синтетический набор для быстрой проверки или IEK для
                расчёта по локальным книгам Excel. Заказ поставщику не
                отправляется.
              </p>
              <button
                className="button button-primary"
                type="button"
                disabled={Boolean(busy)}
                onClick={() => void calculate()}
              >
                Рассчитать
              </button>
            </section>
          ) : (
            <>
              {page === "overview" && (
                <OverviewPage
                  result={run}
                  onOpenRecommendations={() => setPage("recommendations")}
                  onOpenRecommendation={openRecommendation}
                />
              )}
              {page === "recommendations" && (
                <RecommendationsPage
                  result={run}
                  selectedSku={selectedSku}
                  onSelectSku={(sku) => {
                    setSelectedSku(sku);
                    setExplanation(null);
                  }}
                  onSaveQuantity={saveQuantity}
                  onExplain={explain}
                  explanation={explanation}
                  busy={Boolean(busy)}
                />
              )}
              {page === "orders" && (
                <OrdersPage
                  result={run}
                  onApprove={approve}
                  onExport={download}
                  busy={Boolean(busy)}
                />
              )}
              {page === "sources" && <SourcesPage result={run} />}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
