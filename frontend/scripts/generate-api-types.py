"""Regenerate TypeScript DTOs from the checked-in backend OpenAPI contract."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
schemas = json.loads((root / 'docs/openapi.json').read_text())['components']['schemas']

def ts(value):
    if '$ref' in value:
        return value['$ref'].split('/')[-1]
    if 'enum' in value:
        return ' | '.join(json.dumps(item) for item in value['enum'])
    if 'anyOf' in value:
        return ' | '.join(ts(item) for item in value['anyOf'])
    kind = value.get('type')
    if kind == 'array':
        return f'Array<{ts(value["items"])}>'
    if kind == 'object':
        extra = value.get('additionalProperties', {})
        return f'Record<string, {ts(extra) if isinstance(extra, dict) else "unknown"}>'
    return {'string': 'string', 'integer': 'number', 'number': 'number', 'boolean': 'boolean', 'null': 'null'}.get(kind, 'unknown')

lines = ['// Generated from docs/openapi.json. Run: python3 scripts/generate-api-types.py']
for name, schema in schemas.items():
    required = schema.get('required', [])
    lines.append(f'export interface {name} {{')
    for key, value in schema.get('properties', {}).items():
        lines.append(f'  {key}{"" if key in required else "?"}: {ts(value)};')
    lines.append('}')
(root / 'frontend/src/api/types.ts').parent.mkdir(parents=True, exist_ok=True)
(root / 'frontend/src/api/types.ts').write_text('\n'.join(lines) + '\n')
