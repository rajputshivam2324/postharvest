let token: string | null = null;
let unauthorized: () => void = () => {};
export function setSession(value: string | null, handler?: () => void) {
  token = value;
  if (handler) unauthorized = handler;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '');
export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const requestToken = token;
  const response = await fetch(`${base}${path}`, {
    method: options.method || 'GET',
    signal: options.signal,
    headers: {
      ...(requestToken ? { Authorization: `Bearer ${requestToken}` } : {}),
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
    credentials: 'omit',
    cache: 'no-store',
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && requestToken && requestToken === token) unauthorized();
    throw new ApiError(
      response.status,
      data?.error?.message || `Request failed (${response.status}). Please try again.`,
    );
  }
  return data as T;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
export function params(values: Record<string, string | number | boolean | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values))
    if (value !== undefined && value !== '') query.set(key, String(value));
  return query.toString() ? `?${query}` : '';
}
export function safeDestination(value: unknown) {
  return typeof value === 'string' && /^\/app(?:\/|$)/.test(value) && !/[\\\s]/.test(value)
    ? value
    : '/app';
}
