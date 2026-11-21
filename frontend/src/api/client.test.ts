import { api, ApiError, params, safeDestination, setSession } from './client';
describe('API and session boundaries', () => {
  afterEach(() => setSession(null));
  it('attaches an in-memory bearer token and serializes requests', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'batch' })));
    vi.stubGlobal('fetch', fetcher);
    setSession('test-token');
    await api('/batches', { method: 'POST', body: { identifier: 'tomatoes' } });
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/batches',
      expect.objectContaining({
        headers: { Authorization: 'Bearer test-token', 'Content-Type': 'application/json' },
        credentials: 'omit',
        body: '{"identifier":"tomatoes"}',
      }),
    );
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
  it('clears the session on 401 but not forbidden access', async () => {
    const expired = vi.fn();
    setSession('token', expired);
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('{"error":{"message":"Denied"}}', { status: 403 })),
    );
    await expect(api('/users')).rejects.toThrow('Denied');
    expect(expired).not.toHaveBeenCalled();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })));
    await expect(api('/batches')).rejects.toBeInstanceOf(ApiError);
    expect(expired).toHaveBeenCalledOnce();
  });
  it('ignores a late unauthorized response from an earlier session', async () => {
    const expired = vi.fn();
    let finish!: (response: Response) => void;
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      ),
    );
    setSession('old', expired);
    const pending = api('/batches');
    setSession('new', expired);
    finish(new Response('{}', { status: 401 }));
    await expect(pending).rejects.toThrow();
    expect(expired).not.toHaveBeenCalled();
  });
  it.each([
    'https://example.com',
    '//example.com',
    '/app\\evil',
    '/login',
    '/app/\nmalicious',
    '/application',
  ])('rejects unsafe redirect %s', (value) => {
    expect(safeDestination(value)).toBe('/app');
  });
  it('preserves only an internal operational destination', () => {
    expect(safeDestination('/app/batches/123?tab=readings')).toBe('/app/batches/123?tab=readings');
  });
  it('includes false and zero in filters while encoding input', () => {
    expect(params({ archived: false, offset: 0, commodity: 'a&b', empty: '' })).toBe(
      '?archived=false&offset=0&commodity=a%26b',
    );
  });
});
