import type { Recommendation } from "../types/planning.generated";

export const quantity = (value: number): string =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value);

export const urgencyLabels: Record<Recommendation["urgency"], string> = {
  critical: "Критично",
  high: "Высокая",
  medium: "Средняя",
  low: "Низкая",
};

export const flagLabels: Record<Recommendation["flags"][number], string> = {
  one_off_sale: "Крупный документ",
  stockout_adjustment: "Поправка на дефицит",
  suspected_stockout: "Возможный дефицит",
  seasonality: "Сезонность",
  growth: "Рост",
  short_history: "Короткая история",
  missing_data: "Проверить данные",
};

export const productName = (row: Recommendation): string => row.name;
export const productUnit = (row: Recommendation): string =>
  row.diagnostics?.unit === "базовая единица"
    ? "ед."
    : (row.diagnostics?.unit ?? "ед.");
export const supplierName = (row: Recommendation): string => row.supplier_name;
