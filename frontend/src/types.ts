// Mirrors contracts/planning-result.schema.json v0.1.0. Keep changes aligned with that contract.
export type Urgency = 'critical' | 'high' | 'medium' | 'low';
export type Flag = 'one_off_sale' | 'stockout_adjustment' | 'seasonality' | 'growth' | 'short_history' | 'missing_data';
export type Factors = {
  regular_daily_demand: number;
  seasonality_multiplier: number;
  trend_multiplier: number;
  external_growth_multiplier: number;
  estimated_lost_demand: number;
  coverage_days: number;
  forecast_during_coverage: number;
  safety_stock: number;
  current_stock: number;
  goods_in_transit: number;
};
export type Recommendation = {
  sku: string;
  supplier_id: string;
  recommended_quantity: number;
  selected_quantity: number;
  urgency: Urgency;
  factors: Factors;
  reason: string;
  flags: Flag[];
};
export type PlanningResult = {
  run_id: string;
  as_of_date: string;
  warehouse_id: string;
  status: 'draft' | 'approved';
  recommendations: Recommendation[];
};
export type CatalogItem = { name: string; category: string; unit: string; stockSource: string; stockDate: string; note?: string };
