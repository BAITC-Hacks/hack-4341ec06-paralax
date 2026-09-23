import type { CatalogItem, PlanningResult } from '../types';

// Synthetic PlanningResult matching contracts/planning-result.schema.json v0.1.0.
// No partner data or customer identifiers are included.
export const demoResult: PlanningResult = {
  run_id: 'demo-iek-2026-09-23',
  as_of_date: '2026-09-23',
  warehouse_id: 'demo-almaty',
  status: 'draft',
  recommendations: [
    { sku: 'IEK-CAB-001', supplier_id: 'iek-demo', recommended_quantity: 35, selected_quantity: 35, urgency: 'critical', flags: ['one_off_sale', 'seasonality'], reason: 'Регулярный спрос и сезонность повышают целевой запас. Разовая крупная отгрузка отмечена и не включена в регулярный прогноз.', factors: { regular_daily_demand: 1.7, seasonality_multiplier: 1.15, trend_multiplier: 1, external_growth_multiplier: 1, estimated_lost_demand: 0, coverage_days: 28, forecast_during_coverage: 52, safety_stock: 5, current_stock: 20, goods_in_transit: 2 } },
    { sku: 'IEK-LED-036', supplier_id: 'iek-demo', recommended_quantity: 40, selected_quantity: 40, urgency: 'critical', flags: ['stockout_adjustment', 'short_history'], reason: 'Подтверждённый демонстрационный интервал отсутствия товара увеличивает оценку спроса. Короткая история требует проверки менеджером.', factors: { regular_daily_demand: 1.2, seasonality_multiplier: 1, trend_multiplier: 1, external_growth_multiplier: 1.05, estimated_lost_demand: 6, coverage_days: 28, forecast_during_coverage: 41, safety_stock: 4, current_stock: 0, goods_in_transit: 5 } },
    { sku: 'IEK-SW-016', supplier_id: 'iek-demo', recommended_quantity: 15, selected_quantity: 15, urgency: 'high', flags: ['growth'], reason: 'Последовательный рост регулярных продаж учтён в прогнозе. Товар в пути вычтен из потребности.', factors: { regular_daily_demand: 0.85, seasonality_multiplier: 1, trend_multiplier: 1.12, external_growth_multiplier: 1, estimated_lost_demand: 0, coverage_days: 28, forecast_during_coverage: 27, safety_stock: 3, current_stock: 9, goods_in_transit: 6 } },
    { sku: 'IEK-SOC-010', supplier_id: 'iek-demo', recommended_quantity: 0, selected_quantity: 0, urgency: 'low', flags: [], reason: 'Текущий остаток покрывает прогноз и страховой запас на расчётный горизонт.', factors: { regular_daily_demand: 0.5, seasonality_multiplier: 1, trend_multiplier: 1, external_growth_multiplier: 1, estimated_lost_demand: 0, coverage_days: 28, forecast_during_coverage: 14, safety_stock: 2, current_stock: 30, goods_in_transit: 0 } },
  ],
};

// UI display metadata is separate because product names and source dates are
// not present in PlanningResult v0.1.0. These are demo labels, not contract fields.
export const catalog: Record<string, CatalogItem> = {
  'IEK-CAB-001': { name: 'Кабель силовой ВВГнг-LS', category: 'Кабель и провод', unit: 'м', stockSource: 'Синтетический срез остатков', stockDate: '2026-09-23', note: 'Крупный документ; связь нескольких документов с одним клиентом не установлена.' },
  'IEK-LED-036': { name: 'Панель светодиодная 36 Вт', category: 'Освещение', unit: 'шт.', stockSource: 'Синтетический срез остатков', stockDate: '2026-09-23', note: 'Интервал stockout подтверждён только в синтетическом сценарии.' },
  'IEK-SW-016': { name: 'Выключатель автоматический 16 А', category: 'Автоматика', unit: 'шт.', stockSource: 'Синтетический срез остатков', stockDate: '2026-09-23' },
  'IEK-SOC-010': { name: 'Розетка с заземлением', category: 'Электроустановка', unit: 'шт.', stockSource: 'Синтетический срез остатков', stockDate: '2026-09-23' },
};
export const suppliers: Record<string, string> = { 'iek-demo': 'IEK · демонстрационный поставщик' };
