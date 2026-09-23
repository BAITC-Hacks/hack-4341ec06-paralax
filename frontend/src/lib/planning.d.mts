import type { PlanningResult, Recommendation } from '../types';
export function previewTransit(base: Recommendation, transit: number): number;
export function csvContent(run: PlanningResult, names?: Record<string, string>): string;
