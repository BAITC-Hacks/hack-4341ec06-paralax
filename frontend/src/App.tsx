import { useState } from 'react';
import { BarChart3, ClipboardList, Database, LayoutDashboard } from 'lucide-react';
import { demoResult } from './demo/result';
import { OrdersPage } from './pages/OrdersPage';
import { OverviewPage } from './pages/OverviewPage';
import { RecommendationsPage } from './pages/RecommendationsPage';
import { SourcesPage } from './pages/SourcesPage';

type Page = 'overview' | 'recommendations' | 'orders' | 'sources';

const navigation = [
  { id: 'overview', label: 'Обзор', icon: LayoutDashboard },
  { id: 'recommendations', label: 'Рекомендации', icon: BarChart3 },
  { id: 'orders', label: 'Черновик заказа', icon: ClipboardList },
  { id: 'sources', label: 'Источники', icon: Database },
] as const;

const pageTitles: Record<Page, string> = {
  overview: 'Обзор',
  recommendations: 'Рекомендации',
  orders: 'Черновик заказа',
  sources: 'Источники данных',
};

export default function App() {
  const [page, setPage] = useState<Page>('overview');
  const [selectedSku, setSelectedSku] = useState<string | null>(null);

  function openRecommendation(sku: string) {
    setSelectedSku(sku);
    setPage('recommendations');
  }

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="brand-block">
          <span className="brand-symbol" aria-hidden="true">p.</span>
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
              className={page === id ? 'nav-link active' : 'nav-link'}
              aria-current={page === id ? 'page' : undefined}
              onClick={() => setPage(id)}
            >
              <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <span className="demo-dot" aria-hidden="true" />
          <div><strong>Демо-режим</strong><small>Синтетический набор IEK</small></div>
        </div>
      </aside>

      <div className="content-shell">
        <header className="topbar">
          <span className="breadcrumb">Рабочее пространство <span>/</span> <strong>{pageTitles[page]}</strong></span>
          <span className="topbar-meta">IEK <span>·</span> Алматы</span>
        </header>

        <main className="page-content">
          {page === 'overview' && (
            <OverviewPage
              result={demoResult}
              onOpenRecommendations={() => setPage('recommendations')}
              onOpenRecommendation={openRecommendation}
            />
          )}
          {page === 'recommendations' && (
            <RecommendationsPage
              result={demoResult}
              selectedSku={selectedSku}
              onSelectSku={setSelectedSku}
            />
          )}
          {page === 'orders' && <OrdersPage result={demoResult} />}
          {page === 'sources' && <SourcesPage result={demoResult} />}
        </main>
      </div>
    </div>
  );
}
