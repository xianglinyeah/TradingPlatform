import type { StrategyParamSchema } from '../types';

interface Props {
  schema: StrategyParamSchema[];
  values: Record<string, number | string | boolean>;
  onChange: (next: Record<string, number | string | boolean>) => void;
  disabled?: boolean;
}

// Schema-driven parameter form. Each entry in params_schema from the
// strategy class becomes one input. Integers use type=number with step=1,
// floats use a finer step. Booleans become checkboxes. Strings fall back
// to text input.
//
// This is intentionally a hand-written renderer rather than
// react-jsonschema-form - our schema is tiny and we don't want the RJSF
// bundle (and its opinions about validation/errors) for what is
// effectively a flat list of typed inputs.
export default function ParamForm({ schema, values, onChange, disabled }: Props) {
  if (schema.length === 0) {
    return <p className="text-sm text-text-muted">This strategy has no tunable parameters.</p>;
  }

  const update = (key: string, v: number | string | boolean) =>
    onChange({ ...values, [key]: v });

  return (
    <div className="flex flex-col gap-3">
      {schema.map(p => {
        const v = values[p.key] ?? p.default ?? '';
        const common = {
          id: `param-${p.key}`,
          disabled,
          className: 'w-full',
        };

        if (p.type === 'bool') {
          return (
            <label key={p.key} className="flex items-center justify-between gap-2">
              <span className="text-sm text-text-muted">{p.label}</span>
              <input
                type="checkbox"
                {...common}
                checked={Boolean(v)}
                onChange={e => update(p.key, e.target.checked)}
              />
            </label>
          );
        }

        if (p.type === 'int' || p.type === 'float') {
          const step = p.step ?? (p.type === 'int' ? 1 : 0.001);
          return (
            <label key={p.key} className="flex items-center justify-between gap-2">
              <span className="text-sm text-text-muted">{p.label}</span>
              <input
                type="number"
                {...common}
                value={v as number}
                step={step}
                min={p.min}
                max={p.max}
                onChange={e => {
                  const n = Number(e.target.value);
                  update(p.key, Number.isFinite(n) ? n : e.target.value);
                }}
                style={{ maxWidth: '8rem' }}
              />
            </label>
          );
        }

        // string fallback
        return (
          <label key={p.key} className="flex items-center justify-between gap-2">
            <span className="text-sm text-text-muted">{p.label}</span>
            <input
              type="text"
              {...common}
              value={String(v)}
              onChange={e => update(p.key, e.target.value)}
              style={{ maxWidth: '12rem' }}
            />
          </label>
        );
      })}
    </div>
  );
}
