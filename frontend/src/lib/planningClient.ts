import sampleInput from '../../../fixtures/planning-input.sample.json';
import { catalog, demoResult } from '../demo/result';
import { csvContent } from './planning.mjs';
import type { PlanningResult } from '../types';

const baseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') || '';
export const isDemo = !baseUrl;
let mockRun: PlanningResult | null = null;
const STORAGE_KEY = 'paralax.demo-run.v1';

function clone<T>(value: T): T { return structuredClone(value); }
function validate(value: unknown): PlanningResult {
  if (!value || typeof value !== 'object') throw new Error('Сервер вернул пустой результат.');
  const run = value as PlanningResult;
  if (typeof run.run_id !== 'string' || !Array.isArray(run.recommendations) || !['draft', 'approved'].includes(run.status) || run.recommendations.some(row => !row.sku || !Number.isSafeInteger(row.recommended_quantity) || !Number.isSafeInteger(row.selected_quantity) || !row.factors || typeof row.reason !== 'string')) throw new Error('Результат расчёта не соответствует контракту PlanningResult.');
  return run;
}
function saveDemo(run: PlanningResult) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(run)); } catch { /* In-memory demo still works when storage is unavailable. */ }
}
async function request(path: string, init?: RequestInit) {
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } });
  if (!response.ok) throw new Error(`Сервис расчёта недоступен или отклонил запрос (${response.status}). Проверьте данные и повторите.`);
  return response;
}
export const planningClient = {
  restore(): PlanningResult | null {
    if (!isDemo) return null;
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (!saved) return null;
      mockRun = validate(JSON.parse(saved));
      return clone(mockRun);
    } catch { return null; }
  },
  async create(): Promise<PlanningResult> {
    if (isDemo) { await new Promise(resolve => setTimeout(resolve, 420)); mockRun = clone(demoResult); saveDemo(mockRun); return clone(mockRun); }
    return validate(await (await request('/api/planning-runs', { method: 'POST', body: JSON.stringify(sampleInput) })).json());
  },
  async updateQuantity(run: PlanningResult, sku: string, selected_quantity: number): Promise<PlanningResult> {
    if (!Number.isSafeInteger(selected_quantity) || selected_quantity < 0) throw new Error('Введите целое неотрицательное количество.');
    if (run.status !== 'draft') throw new Error('Утверждённый заказ нельзя редактировать.');
    if (isDemo) {
      if (!mockRun || mockRun.run_id !== run.run_id) throw new Error('Сессия демо не найдена. Запустите расчёт снова.');
      mockRun = { ...mockRun, recommendations: mockRun.recommendations.map(row => row.sku === sku ? { ...row, selected_quantity } : row) };
      saveDemo(mockRun);
      return clone(mockRun);
    }
    await request(`/api/planning-runs/${encodeURIComponent(run.run_id)}/recommendations/${encodeURIComponent(sku)}`, { method: 'PATCH', body: JSON.stringify({ selected_quantity }) });
    return { ...run, recommendations: run.recommendations.map(row => row.sku === sku ? { ...row, selected_quantity } : row) };
  },
  async approve(run: PlanningResult): Promise<PlanningResult> {
    if (run.status === 'approved') return run;
    if (isDemo) { mockRun = { ...run, status: 'approved' }; saveDemo(mockRun); return clone(mockRun); }
    return validate(await (await request(`/api/planning-runs/${encodeURIComponent(run.run_id)}/approve`, { method: 'POST' })).json());
  },
  async export(run: PlanningResult): Promise<Blob> {
    if (isDemo) {
      return new Blob([csvContent(run, Object.fromEntries(Object.entries(catalog).map(([sku, item]) => [sku, item.name])))], { type: 'text/csv;charset=utf-8' });
    }
    return (await request(`/api/planning-runs/${encodeURIComponent(run.run_id)}/export`)).blob();
  },
};
