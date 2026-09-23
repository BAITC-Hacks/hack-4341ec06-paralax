import { catalog, suppliers } from '../demo/result';
import type { Recommendation, Urgency } from '../types';

export const quantity = (value: number) => new Intl.NumberFormat('ru-RU').format(value);

export const urgencyLabels: Record<Urgency, string> = {
  critical: 'Критично',
  high: 'Высокая',
  medium: 'Средняя',
  low: 'Низкая',
};

export function productName(row: Recommendation): string {
  return catalog[row.sku]?.name ?? row.sku;
}

export function productUnit(row: Recommendation): string {
  return catalog[row.sku]?.unit ?? 'ед.';
}

export function supplierName(row: Recommendation): string {
  return suppliers[row.supplier_id] ?? row.supplier_id;
}
