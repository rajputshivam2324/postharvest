import { useState, type FormEvent } from 'react';
import { useWrite } from '../api/hooks';
import { Notice } from './ui';

export interface Field {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
  value?: string | number;
  maxLength?: number;
  min?: number;
  max?: number;
  step?: string;
  options?: { value: string; label: string }[];
  hint?: string;
}
export function ResourceForm({
  path,
  fields,
  method = 'POST',
  extra = {},
  transform,
  onSuccess,
  submit = 'Save record',
}: {
  path: string;
  fields: Field[];
  method?: string;
  extra?: Record<string, unknown>;
  transform?: (values: Record<string, unknown>) => Record<string, unknown>;
  onSuccess: (data: unknown) => void;
  submit?: string;
}) {
  const mutation = useWrite(path, method);
  const [localError, setLocalError] = useState('');
  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.reset();
    setLocalError('');
    const data = new FormData(event.currentTarget);
    const values: Record<string, unknown> = { ...extra };
    try {
      for (const field of fields) {
        const raw = String(data.get(field.name) || '');
        if (!raw && !field.required) continue;
        values[field.name] =
          field.type === 'number'
            ? Number(raw)
            : field.type === 'datetime-local'
              ? new Date(raw).toISOString()
              : raw;
      }
      const result = await mutation.mutateAsync(transform ? transform(values) : values);
      onSuccess(result);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : 'Unable to save record.');
    }
  }
  return (
    <form className="resource-form" onSubmit={send}>
      {fields.map((field) => (
        <label key={field.name}>
          {field.label}
          {field.options ? (
            <select
              aria-label={field.label}
              name={field.name}
              required={field.required}
              defaultValue={field.value ?? ''}
            >
              {!field.required && <option value="">Not recorded</option>}
              {field.options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          ) : field.type === 'textarea' ? (
            <textarea
              aria-label={field.label}
              name={field.name}
              required={field.required}
              defaultValue={field.value}
              maxLength={field.maxLength}
              rows={3}
            />
          ) : (
            <input
              aria-label={field.label}
              name={field.name}
              type={field.type || 'text'}
              required={field.required}
              defaultValue={field.value}
              min={field.min}
              max={field.max}
              step={field.step}
              maxLength={field.maxLength}
              autoComplete={field.type === 'password' ? 'new-password' : 'off'}
            />
          )}
          {field.hint && <span className="field-hint">{field.hint}</span>}
        </label>
      ))}
      {(mutation.error || localError) && (
        <Notice danger>{localError || mutation.error?.message}</Notice>
      )}
      <button className="button primary" disabled={mutation.isPending}>
        {mutation.isPending ? 'Saving…' : submit}
      </button>
    </form>
  );
}
export const localNow = () => {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
