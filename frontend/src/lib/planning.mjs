export function previewTransit(base, transit) {
  if (!Number.isSafeInteger(transit) || transit < 0) throw new Error('Количество в пути должно быть целым неотрицательным числом');
  const baseline = Math.ceil(base.factors.forecast_during_coverage + base.factors.safety_stock - base.factors.current_stock - base.factors.goods_in_transit);
  if (Math.max(0, baseline) !== base.recommended_quantity) throw new Error('Демо-результат не согласован с числовыми факторами');
  return Math.max(0, Math.ceil(base.factors.forecast_during_coverage + base.factors.safety_stock - base.factors.current_stock - transit));
}
export function csvContent(run, names = {}) {
  const columns = ['supplier_id', 'sku', 'name', 'recommended_quantity', 'selected_quantity', 'status', 'as_of_date'];
  const quote = value => `"${String(value).replaceAll('"', '""')}"`;
  return '\uFEFF' + [columns.join(';'), ...run.recommendations.map(row => [row.supplier_id, row.sku, names[row.sku] ?? row.sku, row.recommended_quantity, row.selected_quantity, run.status, run.as_of_date].map(quote).join(';'))].join('\r\n');
}
