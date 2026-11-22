import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from '../App';
import { AuthProvider } from '../auth';
import type { BatchOut, ChatResponse, DeviceOut, ReadingOut } from '../api/types';

const NOW = new Date().toISOString();
const batch = (id: string, identifier: string, extra: Partial<BatchOut> = {}): BatchOut => ({
  id,
  identifier,
  owner_id: 'operator',
  commodity: 'tomato',
  quantity: 10,
  unit: 'kg',
  storage_location: 'Cold room',
  notes: null,
  attributes: {},
  status: 'fresh',
  archived: false,
  created_at: NOW,
  updated_at: NOW,
  ...extra,
});
const device = (id: string, extra: Partial<DeviceOut> = {}): DeviceOut => ({
  id,
  identifier: `esp-${id}`,
  batch_id: null,
  active: true,
  simulated: false,
  last_seen_at: null,
  firmware_version: null,
  created_at: NOW,
  paired_at: NOW,
  connection_status: 'never_seen',
  ...extra,
});
const page = (items: unknown[]) => ({ items, total: items.length, limit: 200, offset: 0 });
const reply = (extra: Partial<ChatResponse> = {}): ChatResponse => ({
  answer: 'Temperature held near 21 C.',
  mode: 'ai',
  answerable: true,
  sources: [{ id: 'readings:b1', label: 'Sensor readings', kind: 'readings', batch_id: 'b1' }],
  follow_ups: ['Is the gas value rising?'],
  notice: null,
  ...extra,
});

type Call = { method: string; path: string; body: Record<string, unknown> | null };
type Handler = (call: Call) => unknown;

/** A fake API that records every request, so tests can assert what a click really sends. */
function fakeApi(role: 'operator' | 'vendor', routes: Record<string, Handler> = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const method = init?.method || 'GET';
      const path = String(input).replace('/api/v1', '');
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      const call = { method, path, body };
      calls.push(call);
      if (path === '/auth/login')
        return json(200, {
          access_token: 't',
          expires_at: new Date(Date.now() + 600000).toISOString(),
          expires_in: 600,
          user: { id: role, user_id: role, role, active: true, created_at: NOW },
        });
      const key = Object.keys(routes)
        .filter((k) => `${method} ${path}`.startsWith(k))
        .sort((a, b) => b.length - a.length)[0]; // most specific route wins
      if (key) {
        const result = routes[key]!(call);
        if (result instanceof Response) return result;
        return json(200, result);
      }
      // Single-record endpoints answer null; everything else is an empty list.
      return json(200, path.endsWith('/readings/latest') ? null : page([]));
    }),
  );
  return calls;
}
function json(status: number, value: unknown) {
  return new Response(JSON.stringify(value), { status });
}
function failure(status: number, message: string) {
  return json(status, { error: { code: 'x', message } });
}
async function signIn(route: string) {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('User ID'), 'someone');
  await user.type(screen.getByLabelText('Password'), 'test-password');
  await user.click(screen.getByRole('button', { name: 'Sign in' }));
  await screen.findByRole('navigation', { name: 'Application navigation' });
  if (route !== '/app') await user.click(await screen.findByRole('link', { name: route }));
  return user;
}
const posts = (calls: Call[], path: string) =>
  calls.filter((c) => c.method === 'POST' && c.path === path);

describe('Ask your data', () => {
  it('sends the question, shows the answer as plain text with sources, and follows up', async () => {
    const calls = fakeApi('operator', {
      'POST /chat': (call) =>
        call.body?.message === 'Is the gas value rising?'
          ? reply({ answer: 'Gas is flat.', follow_ups: [], sources: [] })
          : reply({
              answer: 'Temperature held near 21 C. <img src=x onerror=alert(1)>',
            }),
    });
    const user = await signIn('/app');
    await user.click(screen.getByRole('button', { name: 'Ask your data' }));
    const panel = screen.getByRole('complementary', { name: 'Ask your data' });
    await user.type(within(panel).getByLabelText('Your question'), 'How is it?{Enter}');

    expect(await within(panel).findByText(/Temperature held near 21 C/)).toBeInTheDocument();
    // Model output is text, never markup.
    expect(panel.querySelector('img')).toBeNull();
    expect(within(panel).getByText(/<img src=x/)).toBeInTheDocument();
    expect(within(panel).getByText('AI answer from your records')).toBeInTheDocument();
    expect(within(panel).getByRole('link', { name: 'Sensor readings' })).toHaveAttribute(
      'href',
      '/app/batches/b1',
    );
    expect(posts(calls, '/chat')[0]!.body).toEqual({ message: 'How is it?', history: [] });
    // Follow-ups belong to the newest answer only.
    expect(within(panel).getAllByRole('button', { name: 'Is the gas value rising?' })).toHaveLength(
      1,
    );

    await user.click(within(panel).getByRole('button', { name: 'Is the gas value rising?' }));
    expect(await within(panel).findByText('Gas is flat.')).toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: 'Is the gas value rising?' })).toBeNull();
    const second = posts(calls, '/chat')[1]!.body!;
    expect(second.history).toEqual([
      { role: 'user', content: 'How is it?' },
      { role: 'assistant', content: expect.stringContaining('Temperature held') },
    ]);
  });

  it('is scoped to the batch being viewed, and can be widened', async () => {
    const calls = fakeApi('operator', {
      'GET /batches?': () => page([batch('b1', 'tomato-1')]),
      // Sub-resources (observations, assessments...) fall through to this route as well.
      'GET /batches/b1': (call) =>
        call.path === '/batches/b1' ? batch('b1', 'tomato-1') : page([]),
      'GET /batches/b1/readings/latest': () => null,
      'POST /chat': () => reply({ follow_ups: [] }),
    });
    const user = await signIn('Batches');
    await user.click(await screen.findByRole('link', { name: /Inspect/ }));
    await screen.findByRole('heading', { name: 'tomato-1' });
    await user.click(screen.getByRole('button', { name: 'Ask your data' }));
    const panel = screen.getByRole('complementary', { name: 'Ask your data' });
    expect(within(panel).getByText('Answering about this batch')).toBeInTheDocument();
    await user.type(within(panel).getByLabelText('Your question'), 'Anything odd?{Enter}');
    await within(panel).findByText(/Temperature held/);
    expect(posts(calls, '/chat')[0]!.body).toMatchObject({ batch_id: 'b1' });

    await user.click(within(panel).getByLabelText(/Ask about all batches instead/));
    expect(within(panel).queryByText(/Temperature held/)).not.toBeInTheDocument(); // new scope
    await user.type(within(panel).getByLabelText('Your question'), 'And overall?{Enter}');
    await waitFor(() => expect(posts(calls, '/chat')).toHaveLength(2));
    expect(posts(calls, '/chat')[1]!.body).not.toHaveProperty('batch_id');
  });

  it('says plainly when the tool declines or the service fails', async () => {
    let n = 0;
    fakeApi('vendor', {
      'POST /chat': () =>
        ++n === 1
          ? reply({
              mode: 'policy',
              answerable: false,
              answer: 'I can\u2019t certify that produce is safe.',
              notice: null,
              sources: [],
              follow_ups: [],
            })
          : failure(429, 'Too many chat requests; try again later'),
    });
    const user = await signIn('/app'); // a vendor may ask too: the answers are scoped server-side
    await user.click(screen.getByRole('button', { name: 'Ask your data' }));
    const panel = screen.getByRole('complementary', { name: 'Ask your data' });
    await user.type(within(panel).getByLabelText('Your question'), 'Is it safe?{Enter}');
    expect(await within(panel).findByText('This tool does not decide that')).toBeInTheDocument();
    await user.type(within(panel).getByLabelText('Your question'), 'again{Enter}');
    expect(await within(panel).findByRole('alert')).toHaveTextContent('Too many chat requests');
    expect(within(panel).getByText(/does not certify safety or shelf life/)).toBeInTheDocument();
  });

  it('does not send blank questions', async () => {
    const calls = fakeApi('operator');
    const user = await signIn('/app');
    await user.click(screen.getByRole('button', { name: 'Ask your data' }));
    const send = screen.getByRole('button', { name: 'Send question' });
    expect(send).toBeDisabled();
    await user.type(screen.getByLabelText('Your question'), '   {Enter}');
    expect(posts(calls, '/chat')).toHaveLength(0);
  });
});

describe('Add a batch', () => {
  async function fillDetails(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByRole('button', { name: 'Add batch' }));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByLabelText('Batch identifier'), 'tomatoes-9');
    await user.type(within(dialog).getByLabelText('Quantity'), '12');
    await user.type(within(dialog).getByLabelText('Storage location'), 'Room 2');
    await user.selectOptions(within(dialog).getByLabelText('Share with'), 'v1');
    await user.click(within(dialog).getByRole('button', { name: 'Continue' }));
    return dialog;
  }
  const routes = (extra: Record<string, Handler> = {}): Record<string, Handler> => ({
    'GET /vendors': () => page([{ id: 'v1', user_id: 'farmer-asha' }]),
    'GET /devices?unassigned': () => page([device('free1', { identifier: 'spare-esp' })]),
    'POST /batches': () => batch('b9', 'tomatoes-9'),
    ...extra,
  });

  it('creates the batch, pairs a new ESP32 and shows the code and live check', async () => {
    const calls = fakeApi(
      'operator',
      routes({
        'POST /devices/pairing': () => ({
          ...device('d9', {
            identifier: 'cold-room-1',
            paired_at: null,
            connection_status: 'unpaired',
            batch_id: 'b9',
          }),
          pairing_code: 'K7F2-9QXM',
          pairing_expires_at: new Date(Date.now() + 600000).toISOString(),
        }),
        'GET /devices/d9/readings/latest': () => null,
        'GET /devices/d9': () => device('d9', { paired_at: null, connection_status: 'unpaired' }),
      }),
    );
    const user = await signIn('Batches');
    const dialog = await fillDetails(user);
    await user.click(within(dialog).getByLabelText('Pair a new ESP32 with a code'));
    await user.type(within(dialog).getByLabelText('Device name'), 'cold-room-1');
    await user.click(within(dialog).getByRole('button', { name: 'Create batch' }));

    expect(await within(dialog).findByLabelText('Pairing code')).toHaveTextContent('K7F2-9QXM');
    expect(within(dialog).getByText('Waiting for the device to pair.')).toBeInTheDocument();
    expect(posts(calls, '/batches')[0]!.body).toMatchObject({
      identifier: 'tomatoes-9',
      quantity: 12,
      owner_id: 'v1',
      attributes: {},
    });
    expect(posts(calls, '/devices/pairing')[0]!.body).toEqual({
      identifier: 'cold-room-1',
      simulated: false,
      batch_id: 'b9',
    });
    expect(within(dialog).getByRole('link', { name: 'Open batch' })).toHaveAttribute(
      'href',
      '/app/batches/b9',
    );
  });

  it('assigns a free device to the new batch', async () => {
    const calls = fakeApi(
      'operator',
      routes({
        'POST /devices/free1/assignment': () => ({ id: 'a1' }),
        'GET /devices/free1/readings/latest': () => null,
        'GET /devices/free1': () => device('free1', { batch_id: 'b9' }),
      }),
    );
    const user = await signIn('Batches');
    const dialog = await fillDetails(user);
    await user.click(within(dialog).getByLabelText(/Use a free device/));
    await user.click(within(dialog).getByRole('button', { name: 'Create batch' }));
    expect(await within(dialog).findByText('The first reading has arrived')).toBeInTheDocument();
    expect(posts(calls, '/devices/free1/assignment')[0]!.body).toEqual({ batch_id: 'b9' });
  });

  it('never creates the batch twice when the sensor step fails and is retried', async () => {
    let attempts = 0;
    const calls = fakeApi(
      'operator',
      routes({
        'POST /devices/pairing': () =>
          ++attempts === 1
            ? failure(409, 'Record conflicts with existing data')
            : {
                ...device('d9', { paired_at: null }),
                pairing_code: 'AAAA-BBBB',
                pairing_expires_at: new Date(Date.now() + 600000).toISOString(),
              },
        'GET /devices/d9': () => device('d9', { paired_at: null }),
      }),
    );
    const user = await signIn('Batches');
    const dialog = await fillDetails(user);
    await user.click(within(dialog).getByLabelText('Pair a new ESP32 with a code'));
    await user.type(within(dialog).getByLabelText('Device name'), 'dup');
    await user.click(within(dialog).getByRole('button', { name: 'Create batch' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'The batch “tomatoes-9” was created, but the sensor step failed',
    );
    expect(within(dialog).getByRole('button', { name: 'Back' })).toBeDisabled();
    await user.click(within(dialog).getByRole('button', { name: 'Retry sensor step' }));
    expect(await within(dialog).findByLabelText('Pairing code')).toHaveTextContent('AAAA-BBBB');
    expect(posts(calls, '/batches')).toHaveLength(1);
  });

  it('lets the person go back without creating anything', async () => {
    const calls = fakeApi('operator', routes());
    const user = await signIn('Batches');
    const dialog = await fillDetails(user);
    await user.click(within(dialog).getByRole('button', { name: 'Back' }));
    expect(within(dialog).getByLabelText('Batch identifier')).toHaveValue('tomatoes-9');
    expect(posts(calls, '/batches')).toHaveLength(0);
  });

  it('is not offered to vendors', async () => {
    fakeApi('vendor');
    await signIn('Batches');
    expect(screen.queryByRole('button', { name: 'Add batch' })).not.toBeInTheDocument();
  });
});

describe('Devices', () => {
  const free = device('d1', { identifier: 'esp-free' });
  const busy = device('d2', {
    identifier: 'esp-busy',
    batch_id: 'b1',
    connection_status: 'online',
  });
  const devices = () => page([free, busy]);
  const batches = () => page([batch('b1', 'tomato-1'), batch('b2', 'tomato-2')]);

  it('moves a device only after the person confirms, and says readings stay put', async () => {
    const calls = fakeApi('operator', {
      'GET /devices?': devices,
      'GET /batches?': batches,
      'POST /devices/d2/assignment': () => ({ id: 'a' }),
    });
    const user = await signIn('Devices');
    const card = (await screen.findByRole('heading', { name: 'esp-busy' })).closest('article')!;
    await user.click(within(card).getByRole('button', { name: 'Move to another batch' }));
    const dialog = await screen.findByRole('dialog');
    await user.selectOptions(within(dialog).getByLabelText('Batch'), 'b2');
    const move = within(dialog).getByRole('button', { name: 'Move device' });
    expect(move).toBeDisabled();
    expect(
      within(dialog).getByText(/Readings already recorded stay where they are/),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole('checkbox'));
    await user.click(move);
    await waitFor(() => expect(posts(calls, '/devices/d2/assignment')).toHaveLength(1));
    expect(posts(calls, '/devices/d2/assignment')[0]!.body).toEqual({
      batch_id: 'b2',
      replace: true,
    });
  });

  it('assigns a free device without any confirmation step', async () => {
    const calls = fakeApi('operator', {
      'GET /devices?': devices,
      'GET /batches?': batches,
      'POST /devices/d1/assignment': () => ({ id: 'a' }),
    });
    const user = await signIn('Devices');
    const card = (await screen.findByRole('heading', { name: 'esp-free' })).closest('article')!;
    expect(within(card).getByText('Not assigned to a batch')).toBeInTheDocument();
    await user.click(within(card).getByRole('button', { name: 'Assign to a batch' }));
    const dialog = await screen.findByRole('dialog');
    await user.selectOptions(within(dialog).getByLabelText('Batch'), 'b1');
    await user.click(within(dialog).getByRole('button', { name: 'Assign device' }));
    await waitFor(() => expect(posts(calls, '/devices/d1/assignment')).toHaveLength(1));
    expect(posts(calls, '/devices/d1/assignment')[0]!.body).toEqual({
      batch_id: 'b1',
      replace: false,
    });
  });

  it('releases a device with an explicit DELETE', async () => {
    const calls = fakeApi('operator', {
      'GET /devices?': devices,
      'DELETE /devices/d2/assignment': () => free,
    });
    const user = await signIn('Devices');
    const card = (await screen.findByRole('heading', { name: 'esp-busy' })).closest('article')!;
    await user.click(within(card).getByRole('button', { name: 'Release' }));
    await user.click(await screen.findByRole('button', { name: 'Release device' }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.path === '/devices/d2/assignment')).toBe(
        true,
      ),
    );
  });

  it('shows a waiting state for an unpaired device and can issue a new code', async () => {
    const waiting = device('d3', {
      identifier: 'esp-new',
      paired_at: null,
      connection_status: 'unpaired',
    });
    const calls = fakeApi('operator', {
      'GET /devices?': () => page([waiting]),
      'POST /devices/d3/pairing': () => ({
        device_id: 'd3',
        pairing_code: 'ZZZZ-3333',
        expires_at: new Date(Date.now() + 600000).toISOString(),
      }),
      'GET /devices/d3': () => waiting,
    });
    const user = await signIn('Devices');
    const card = (await screen.findByRole('heading', { name: 'esp-new' })).closest('article')!;
    expect(within(card).getByText(/Waiting to be paired/)).toBeInTheDocument();
    await user.click(within(card).getByRole('button', { name: 'Show pairing code' }));
    await user.click(await screen.findByRole('button', { name: 'Create a new code' }));
    expect(await screen.findByLabelText('Pairing code')).toHaveTextContent('ZZZZ-3333');
    expect(posts(calls, '/devices/d3/pairing')).toHaveLength(1);
  });

  it('keeps vendors read-only', async () => {
    fakeApi('vendor', { 'GET /devices?': devices });
    await signIn('Devices');
    const card = (await screen.findByRole('heading', { name: 'esp-busy' })).closest('article')!;
    for (const name of [/Move to another/, /Release/, /Pair/, /Assign/, /Rotate/, /Disable/]) {
      expect(within(card).queryByRole('button', { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole('button', { name: 'Pair an ESP32' })).not.toBeInTheDocument();
  });
});

describe('Sensor history follows new readings', () => {
  const reading = (n: number): ReadingOut => ({
    id: `r${n}`,
    device_id: 'd1234567-aaaa',
    batch_id: 'b1',
    event_id: `e${n}`,
    temperature_c: 20 + n / 10,
    humidity_pct: 50,
    gas_adc: 600,
    gas_voltage_v: 0.6,
    warming_up: true,
    simulated: false,
    firmware_version: 'fw',
    source_timestamp: NOW,
    ingested_at: NOW,
  });

  it('asks for the newest page, with no fixed end time, so later readings are not hidden', async () => {
    const calls = fakeApi('operator', {
      'GET /batches?': () => page([batch('b1', 'tomato-1')]),
      'GET /batches/b1': (call) =>
        call.path === '/batches/b1' ? batch('b1', 'tomato-1') : page([]),
      'GET /batches/b1/readings/latest': () => null,
      'GET /batches/b1/readings': (call) => {
        const offset = Number(new URL(call.path, 'http://x').searchParams.get('offset'));
        // 450 readings exist; the newest page starts at offset 250.
        return {
          items: offset === 250 ? [reading(449)] : [reading(0)],
          total: 450,
          limit: 200,
          offset,
        };
      },
    });
    const user = await signIn('Batches');
    await user.click(await screen.findByRole('link', { name: /Inspect/ }));
    await screen.findByRole('heading', { name: 'tomato-1' });
    // The newest reading (24.9 C comes from reading 449 -> 20 + 44.9 = 64.9) is on screen.
    expect(await screen.findByText('64.9')).toBeInTheDocument();
    expect(screen.getByText(/Showing the latest 200 of 450 readings/)).toBeInTheDocument();
    const asked = calls
      .filter((c) => c.path.startsWith('/batches/b1/readings?'))
      .map((c) => new URL(c.path, 'http://x').searchParams);
    expect(asked.some((q) => q.get('offset') === '250' && q.get('limit') === '200')).toBe(true);
    expect(asked.every((q) => !q.has('end'))).toBe(true);
  });

  it('draws a chosen range from the whole-range summary, not just the first page', async () => {
    const calls = fakeApi('operator', {
      'GET /batches?': () => page([batch('b1', 'tomato-1')]),
      'GET /batches/b1': (call) =>
        call.path === '/batches/b1' ? batch('b1', 'tomato-1') : page([]),
      'GET /batches/b1/readings/latest': () => null,
      'GET /batches/b1/readings/series': () => ({
        points: [
          {
            device_id: 'd1234567-aaaa',
            source_timestamp: '2026-11-15T08:20:00Z',
            temperature_c: 12.5,
            humidity_pct: 90,
            gas_adc: 600,
            samples: 4,
          },
          {
            device_id: 'd1234567-aaaa',
            source_timestamp: '2026-11-21T08:20:00Z',
            temperature_c: 27.5,
            humidity_pct: 45,
            gas_adc: 640,
            samples: 4,
          },
        ],
        total: 1728,
        bucket_seconds: 1500,
      }),
      'GET /batches/b1/readings': () => ({
        items: [reading(0)],
        total: 1728,
        limit: 200,
        offset: 0,
      }),
    });
    const user = await signIn('Batches');
    await user.click(await screen.findByRole('link', { name: /Inspect/ }));
    await screen.findByRole('heading', { name: 'tomato-1' });
    await user.click(await screen.findByRole('button', { name: 'Apply range' }));
    expect(
      await screen.findByText(/1728 readings averaged into 25-minute buckets/),
    ).toBeInTheDocument();
    const asked = calls.filter((c) => c.path.startsWith('/batches/b1/readings/series'));
    expect(asked.length).toBeGreaterThan(0);
    const q = new URL(asked.at(-1)!.path, 'http://x').searchParams;
    expect(q.get('max_points')).toBe('500');
    expect(q.has('start') && q.has('end')).toBe(true);
    expect(screen.getByRole('button', { name: 'Show latest' })).toBeInTheDocument();
  });
});
