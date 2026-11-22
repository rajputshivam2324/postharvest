import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, params, type Page } from './client';
export function useResource<T>(path: string, enabled = true) {
  return useQuery({ queryKey: [path], queryFn: ({ signal }) => api<T>(path, { signal }), enabled });
}
export function useWrite<T = unknown>(path: string, method = 'POST') {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: unknown) => api<T>(path, { method, body }),
    onSuccess: () => {
      void client.invalidateQueries();
    },
  });
}
export function useList<T>(
  path: string,
  offset = 0,
  filters: Record<string, string | boolean | undefined> = {},
  limit = 12,
  enabled = true,
) {
  return useResource<Page<T>>(`${path}${params({ ...filters, limit, offset })}`, enabled);
}
