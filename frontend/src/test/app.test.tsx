import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import App from '../App';
import { AuthProvider } from '../auth';
import { QueryState } from '../components/ui';

function mount(route = '/app') {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={[route]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
function respond(status = 200, value: unknown = {}) {
  return new Response(JSON.stringify(value), { status });
}
function mockApi() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.endsWith('/auth/login'))
        return respond(200, {
          access_token: 'test-token',
          expires_at: new Date(Date.now() + 60000).toISOString(),
          expires_in: 60,
          user: {
            id: 'operator',
            user_id: 'operator',
            role: 'operator',
            active: true,
          },
        });
      return respond(200, { items: [], total: 0, offset: 0, limit: 12, ranking_meaningful: false });
    }),
  );
}
describe('public and authenticated journeys', () => {
  it('validates matching passwords before submitting signup', async () => {
    const fetcher = vi.fn();
    vi.stubGlobal('fetch', fetcher);
    mount('/signup');
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('User ID'), 'new-user');
    await user.type(screen.getByLabelText('Password', { exact: true }), 'a-test-password-1');
    await user.type(screen.getByLabelText('Confirm password'), 'a-test-password-2');
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Passwords do not match');
    expect(fetcher).not.toHaveBeenCalled();
    expect(screen.getByRole('combobox', { name: 'Account role' })).toHaveValue('vendor');
  });
  it('sends the home route to the static landing page without requesting private records', () => {
    const fetcher = vi.fn();
    const replace = vi.fn();
    vi.stubGlobal('fetch', fetcher);
    vi.stubGlobal('location', { ...window.location, replace });
    mount('/');
    expect(replace).toHaveBeenCalledWith('/site/index.html');
    expect(screen.getByRole('link', { name: /Continue to the Harvest home page/ })).toHaveAttribute(
      'href',
      '/site/index.html',
    );
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('protects operational routes and signs in to the safe destination', async () => {
    mockApi();
    mount('/app/batches');
    const user = userEvent.setup();
    expect(screen.getByRole('heading', { name: 'Welcome back.' })).toBeInTheDocument();
    await user.type(screen.getByLabelText('User ID'), 'operator');
    await user.type(screen.getByLabelText('Password'), 'test-password');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'Batches' })).toBeInTheDocument();
    expect(await screen.findByText('No batches match')).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/auth/'))).toEqual([
      ['/api/v1/auth/login', expect.objectContaining({ method: 'POST' })],
    ]);
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(await screen.findByRole('heading', { name: 'Welcome back.' })).toBeInTheDocument();
  });
  it('shows a generic backend login failure and allows retry', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(respond(401, { error: { message: 'Invalid credentials' } })),
    );
    mount('/login');
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('User ID'), 'operator');
    await user.type(screen.getByLabelText('Password'), 'incorrect');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid credentials');
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled();
  });
  it('opens the requested page when a running backend returns the older token-only response', async () => {
    mockApi();
    const original = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation(async (input, options) => {
      if (String(input).endsWith('/auth/login'))
        return respond(200, {
          access_token: 'legacy-token',
          expires_in: 60,
          expires_at: new Date(Date.now() + 60000).toISOString(),
        });
      if (String(input).endsWith('/auth/me'))
        return respond(200, {
          id: 'operator',
          user_id: 'operator',
          role: 'operator',
          active: true,
        });
      return original(input, options);
    });
    mount('/app/batches');
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('User ID'), 'operator');
    await user.type(screen.getByLabelText('Password'), 'test-password');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'Batches' })).toBeInTheDocument();
    expect(await screen.findByText('No batches match')).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/auth/me',
      expect.objectContaining({ headers: { Authorization: 'Bearer legacy-token' } }),
    );
  });
  it('shows a failed profile lookup and lets the user retry instead of redirecting in a loop', async () => {
    mockApi();
    const original = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation(async (input, options) => {
      if (String(input).endsWith('/auth/login'))
        return respond(200, {
          access_token: 'legacy-token',
          expires_in: 60,
          expires_at: new Date(Date.now() + 60000).toISOString(),
        });
      if (String(input).endsWith('/auth/me'))
        return respond(503, { error: { message: 'Account lookup unavailable' } });
      return original(input, options);
    });
    mount('/login');
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('User ID'), 'operator');
    await user.type(screen.getByLabelText('Password'), 'test-password');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Account lookup unavailable');
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled();
    vi.mocked(fetch).mockImplementation(original);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: /clearer view/ })).toBeInTheDocument();
  });
  it('keeps vendor controls read-only', async () => {
    mockApi();
    const fetcher = vi.mocked(fetch);
    fetcher.mockImplementation(async (input) =>
      String(input).endsWith('/auth/login')
        ? respond(200, {
            access_token: 'test',
            expires_at: new Date(Date.now() + 60000).toISOString(),
            user: { id: 'vendor', user_id: 'vendor', role: 'vendor', active: true },
          })
        : respond(200, { items: [], total: 0 }),
    );
    mount('/login');
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('User ID'), 'vendor');
    await user.type(screen.getByLabelText('Password'), 'test-password');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: /clearer view/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add batch' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Pair an ESP32' })).not.toBeInTheDocument();
    expect(screen.getByText('Read-only access')).toBeInTheDocument();
  });
});

describe('server state', () => {
  it('shows loading, errors, recovery and a failed refresh with retained data', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    let finish!: (value: string) => void;
    const request = vi
      .fn<() => Promise<string>>()
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      )
      .mockRejectedValueOnce(new Error('Network unavailable'))
      .mockResolvedValue('Recovered');
    function State() {
      const query = useQuery({ queryKey: ['state'], queryFn: request });
      return (
        <QueryState query={query}>
          <p>{query.data}</p>
        </QueryState>
      );
    }
    render(
      <QueryClientProvider client={client}>
        <State />
      </QueryClientProvider>,
    );
    expect(screen.getByRole('status')).toHaveTextContent('Loading records');
    finish('Evidence loaded');
    expect(await screen.findByText('Evidence loaded')).toBeInTheDocument();
    await client.invalidateQueries();
    expect(await screen.findByRole('alert')).toHaveTextContent('Showing previously loaded records');
    expect(screen.getByText('Evidence loaded')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Recovered')).toBeInTheDocument();
  });
  it('shows initial failures with a retry action', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function State() {
      const query = useQuery({
        queryKey: ['failed'],
        queryFn: () => Promise.reject(new Error('API unavailable')),
      });
      return (
        <QueryState query={query}>
          <p>data</p>
        </QueryState>
      );
    }
    render(
      <QueryClientProvider client={client}>
        <State />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('API unavailable'));
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});
