"""One-time, reviewable migration to the additive Excel input contract."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    path = ROOT / 'contracts/planning-input.schema.json'
    schema = json.loads(path.read_text(encoding='utf-8'))
    string = {'type': 'string', 'minLength': 1}
    day = {'type': 'string', 'format': 'date'}
    nonnegative = {'type': 'number', 'minimum': 0}
    schema['properties'].update({
        'schema_version': {'const': '0.2.0'},
        'data_source': {'enum': ['synthetic', 'partner_excel']},
        'safety_stock_days': {'type': 'integer', 'minimum': 0},
        'history_start_date': day,
        'history_end_date': day,
        'source_files': {'type': 'array', 'items': string},
        'assumptions': {'type': 'array', 'items': string},
        'monthly_history': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['sku', 'month', 'quantity', 'opening_stock'],
            'properties': {'sku': string, 'month': day,
                'quantity': {'type': ['number', 'null'], 'minimum': 0},
                'opening_stock': {'type': ['number', 'null'], 'minimum': 0}}}},
    })
    product = schema['$defs']['product']['properties']
    product.update({'unit': string, 'stock_as_of_date': day, 'stock_source': string,
        'stock_scope': string, 'order_multiple': {'type': 'integer', 'minimum': 1},
        'minimum_order_quantity': {'type': 'integer', 'minimum': 0},
        'quality_warnings': {'type': 'array', 'items': string},
        'shipments': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['quantity', 'expected_date'],
            'properties': {'quantity': {'type': 'integer', 'minimum': 0},
                           'expected_date': day}}}})
    sale = schema['$defs']['sale']
    sale['required'] = ['date', 'sku', 'quantity']
    sale['anyOf'] = [{'required': ['document_id']}, {'required': ['customer_id']}]
    sale['properties'].update({'document_id': string, 'warehouse_id': string, 'unit': string})
    schema['$defs']['stockout']['properties']['certainty'] = {
        'enum': ['confirmed', 'suspected']}
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    path = ROOT / 'contracts/planning-result.schema.json'
    schema = json.loads(path.read_text(encoding='utf-8'))
    for key in ('source_files', 'assumptions'):
        schema['properties'][key] = {'type': 'array', 'items': string}
    schema['$defs']['recommendation']['properties']['diagnostics'] = {
        'type': 'object', 'additionalProperties': False,
        'required': ['model', 'validation_mae', 'validation_points', 'quality_warnings'],
        'properties': {'model': string,
            'validation_mae': {'type': ['number', 'null'], 'minimum': 0},
            'validation_points': {'type': 'integer', 'minimum': 0},
            'quality_warnings': {'type': 'array', 'items': string},
            'unit': string,
            'candidate_mae': {'type': 'object', 'additionalProperties': nonnegative}}}
    schema['$defs']['factors']['properties'].update({
        'lead_time_days': {'type': 'integer', 'minimum': 0},
        'excluded_late_transit': {'type': 'integer', 'minimum': 0},
        'anomaly_excess_quantity': nonnegative,
    })
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
