import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { previewTransit, csvContent } from './planning.mjs';

const row = { recommended_quantity: 35, factors: { forecast_during_coverage: 52, safety_stock: 5, current_stock: 20, goods_in_transit: 2 } };
test('goods already in transit lowers only the preview recommendation', () => {
  assert.equal(previewTransit(row, 12), 25);
  assert.equal(row.recommended_quantity, 35);
  assert.equal(previewTransit(row, 100), 0);
});
test('invalid scenario input is rejected', () => {
  assert.throws(() => previewTransit(row, -1));
  assert.throws(() => previewTransit(row, 2.5));
});
test('CSV keeps original and chosen quantity, status and date', () => {
  const csv = csvContent({ status: 'approved', as_of_date: '2026-09-23', recommendations: [{ supplier_id: 'IEK', sku: '001', recommended_quantity: 35, selected_quantity: 40 }] });
  assert.match(csv, /recommended_quantity;selected_quantity;status;as_of_date/);
  assert.match(csv, /"35";"40";"approved";"2026-09-23"/);
});
