// Generated from contracts/*.schema.json. Do not edit by hand.
export interface PlanningInput {
  as_of_date: string;
  warehouse_id: string;
  review_period_days: number;
  /**
   * @minItems 1
   */
  suppliers: [Supplier, ...Supplier[]];
  /**
   * @minItems 1
   */
  products: [Product, ...Product[]];
  sales: Sale[];
  stockouts: Stockout[];
}
export interface Supplier {
  supplier_id: string;
  name: string;
  lead_time_days: number;
}
export interface Product {
  sku: string;
  name: string;
  category: string;
  supplier_id: string;
  current_stock: number;
  goods_in_transit: number;
  growth_forecast_pct: number;
}
export interface Sale {
  date: string;
  sku: string;
  quantity: number;
  customer_id: string;
  unit_price_kzt: number;
}
export interface Stockout {
  sku: string;
  start_date: string;
  end_date: string;
}

export interface PlanningResult {
  run_id: string;
  as_of_date: string;
  warehouse_id: string;
  data_source: "synthetic" | "partner_excel";
  status: "draft" | "approved";
  recommendations: Recommendation[];
}
export interface Recommendation {
  sku: string;
  name: string;
  category: string;
  supplier_id: string;
  supplier_name: string;
  recommended_quantity: number;
  selected_quantity: number;
  urgency: "critical" | "high" | "medium" | "low";
  factors: Factors;
  reason: string;
  flags: (
    | "one_off_sale"
    | "stockout_adjustment"
    | "suspected_stockout"
    | "seasonality"
    | "growth"
    | "short_history"
    | "missing_data"
  )[];
}
export interface Factors {
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
  stock_as_of_date?: string;
  stock_source?: string;
}
