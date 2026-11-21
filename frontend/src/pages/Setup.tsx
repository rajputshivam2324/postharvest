import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Plus, Copy, Check, Radio } from 'lucide-react';
import { useAuth } from '../auth';
import { useList, useResource, useWrite } from '../api/hooks';
import { type Page } from '../api/client';
import type {
  BaselineOut,
  BatchOut,
  CredentialOut,
  DecisionOut,
  DeviceOut,
  DeviceRegistered,
  UserOut,
} from '../api/types';
import {
  date,
  human,
  Modal,
  Notice,
  PageHeader,
  Pagination,
  QueryState,
  Refresh,
  Source,
} from '../components/ui';
import { localNow, ResourceForm } from '../components/ResourceForm';
import {
  AssignToBatchModal,
  PairAgainModal,
  PairDeviceModal,
  ReleaseDeviceModal,
} from '../components/DeviceSetup';

function Credential({ value, close }: { value: string; close: () => void }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');
  return (
    <Modal title="Save the device credential" close={close}>
      <Notice>
        This credential is shown once. Store it securely before closing; it cannot be retrieved
        later.
      </Notice>
      <pre className="credential">{value}</pre>
      <div className="actions">
        <button
          className="button secondary"
          onClick={() => {
            navigator.clipboard
              .writeText(value)
              .then(() => setCopied(true))
              .catch(() =>
                setError('Clipboard unavailable. Select and copy the credential manually.'),
              );
          }}
        >
          {copied ? <Check size={17} /> : <Copy size={17} />}
          {copied ? 'Copied' : 'Copy credential'}
        </button>
        <button className="button primary" onClick={close}>
          I have saved it
        </button>
      </div>
      {error && <Notice danger>{error}</Notice>}
    </Modal>
  );
}
function DeviceCard({
  device,
  credential,
}: {
  device: DeviceOut;
  credential: (value: string) => void;
}) {
  const { user } = useAuth();
  const [modal, setModal] = useState('');
  const [history, setHistory] = useState(false);
  const [offset, setOffset] = useState(0);
  const baselines = useResource<Page<BaselineOut>>(
    `/devices/${device.id}/baselines?limit=12&offset=${offset}`,
    history,
  );
  const assigned = useResource<BatchOut>(`/batches/${device.batch_id}`, Boolean(device.batch_id));
  const update = useWrite(`/devices/${device.id}`, 'PATCH');
  const rotate = useWrite<CredentialOut>(`/devices/${device.id}/rotate-credential`);
  return (
    <article className="device-card">
      <div className="device-card-heading">
        <div>
          <h2>{device.identifier}</h2>
          <p className="muted">Device ID: {device.id}</p>
        </div>
        <span
          className={`badge ${device.connection_status === 'online' ? 'fresh' : 'insufficient_data'}`}
        >
          {human(device.connection_status)}
        </span>
      </div>
      <div className="device-data">
        <Source simulated={device.simulated} />
        <span>Last seen: {date(device.last_seen_at)}</span>
        <span>Firmware: {device.firmware_version || 'Not reported'}</span>
      </div>
      <p className="muted">
        {device.batch_id ? (
          <>
            On batch{' '}
            <Link to={`/app/batches/${device.batch_id}`}>
              {assigned.data?.identifier ?? 'open batch'}
            </Link>
          </>
        ) : (
          'Not assigned to a batch'
        )}
        {!device.paired_at && ' · Waiting to be paired'}
      </p>
      <div className="actions">
        <button
          className="button secondary"
          onClick={() => setHistory(!history)}
          aria-expanded={history}
        >
          Baseline history
        </button>
        {user?.role !== 'vendor' && (
          <button className="button secondary" onClick={() => setModal('baseline')}>
            Record baseline
          </button>
        )}
        {user?.role !== 'vendor' && device.active && (
          <>
            <button className="button secondary" onClick={() => setModal('assign')}>
              {device.batch_id ? 'Move to another batch' : 'Assign to a batch'}
            </button>
            {device.batch_id && (
              <button className="button secondary" onClick={() => setModal('release')}>
                Release
              </button>
            )}
            <button className="button secondary" onClick={() => setModal('pair')}>
              {device.paired_at ? 'Pair again' : 'Show pairing code'}
            </button>
          </>
        )}
        {user?.role !== 'vendor' && (
          <>
            <button
              className="button secondary"
              disabled={update.isPending}
              onClick={() => update.mutate({ active: !device.active })}
            >
              {device.active ? 'Disable device' : 'Enable device'}
            </button>
            <button className="text-button" onClick={() => setModal('rotate')}>
              Rotate credential
            </button>
          </>
        )}
      </div>
      {update.error && <Notice danger>{update.error.message}</Notice>}
      {history && (
        <QueryState query={baselines} empty={!baselines.data?.items.length}>
          <div className="baseline-history">
            {baselines.data?.items.map((b) => (
              <p key={b.id}>
                <strong>{b.gas_adc} ADC</strong> · {date(b.recorded_at)}
                <small>{b.notes}</small>
              </p>
            ))}
          </div>
          <Pagination total={baselines.data?.total || 0} offset={offset} onChange={setOffset} />
        </QueryState>
      )}
      {modal === 'assign' && <AssignToBatchModal device={device} close={() => setModal('')} />}
      {modal === 'release' && <ReleaseDeviceModal device={device} close={() => setModal('')} />}
      {modal === 'pair' && <PairAgainModal device={device} close={() => setModal('')} />}
      {modal === 'baseline' && (
        <Modal title="Record clean-air baseline" close={() => setModal('')}>
          <p className="muted">
            Record a clean-air reference before the monitoring window. Baseline history is retained.
          </p>
          <ResourceForm
            path={`/devices/${device.id}/baseline`}
            fields={[
              {
                name: 'gas_adc',
                label: 'Gas response (raw ADC)',
                type: 'number',
                required: true,
                min: 1,
                max: 4095,
                step: '1',
              },
              {
                name: 'recorded_at',
                label: 'Recorded at (local time)',
                type: 'datetime-local',
                required: true,
                value: localNow(),
              },
              { name: 'notes', label: 'Notes', type: 'textarea', maxLength: 2000 },
            ]}
            onSuccess={() => setModal('')}
            submit="Record baseline"
          />
        </Modal>
      )}
      {modal === 'rotate' && (
        <Modal title="Rotate device credential?" close={() => setModal('')}>
          <p>
            The current credential will stop working. Update your device or simulator with the new
            one.
          </p>
          {rotate.error && <Notice danger>{rotate.error.message}</Notice>}
          <button
            className="button primary"
            disabled={rotate.isPending}
            onClick={() =>
              rotate.mutate(undefined, {
                onSuccess: (result) => {
                  setModal('');
                  credential(result.credential);
                },
              })
            }
          >
            Rotate & show new credential
          </button>
        </Modal>
      )}
    </article>
  );
}

export function Devices() {
  const { user } = useAuth();
  const [offset, setOffset] = useState(0);
  const [register, setRegister] = useState(false);
  const [pair, setPair] = useState(false);
  const [credential, setCredential] = useState('');
  const [batchId, setBatchId] = useState('');
  const query = useList<DeviceOut>('/devices', offset, { batch_id: batchId });
  return (
    <>
      <PageHeader
        title="Devices"
        description="Connect a sensor, check its freshness, and retain a clean-air reference."
        action={
          <>
            <Refresh refresh={() => void query.refetch()} fetching={query.isFetching} />
            {user?.role !== 'vendor' && (
              <>
                <button className="button secondary" onClick={() => setRegister(true)}>
                  <Plus size={17} />
                  Register with credential
                </button>
                <button className="button primary" onClick={() => setPair(true)}>
                  <Radio size={17} />
                  Pair an ESP32
                </button>
              </>
            )}
          </>
        }
      />
      <div className="filters">
        <label>
          Filter by batch ID
          <input
            value={batchId}
            onChange={(event) => {
              setBatchId(event.target.value);
              setOffset(0);
            }}
            placeholder="All accessible batches"
          />
        </label>
      </div>
      <QueryState query={query} empty={!query.data?.items.length}>
        {query.data?.items.map((device) => (
          <DeviceCard key={device.id} device={device} credential={setCredential} />
        ))}
      </QueryState>
      <Pagination total={query.data?.total || 0} offset={offset} onChange={setOffset} />
      {pair && <PairDeviceModal close={() => setPair(false)} />}
      {register && (
        <Modal title="Register a device" close={() => setRegister(false)}>
          <p className="muted">
            Use this for a simulator or a device you will configure by hand. For an ESP32, use Pair
            an ESP32 instead: there is no credential to copy. You can leave the batch empty and
            assign the device later.
          </p>
          <ResourceForm
            path="/devices"
            fields={[
              { name: 'identifier', label: 'Device identifier', required: true, maxLength: 100 },
              { name: 'batch_id', label: 'Batch ID (optional)', maxLength: 36 },
              {
                name: 'simulated',
                label: 'Data source',
                required: true,
                options: [
                  { value: 'false', label: 'Real hardware' },
                  { value: 'true', label: 'Simulator' },
                ],
              },
              { name: 'firmware_version', label: 'Firmware version', maxLength: 80 },
            ]}
            transform={(v) => ({ ...v, simulated: v.simulated === 'true' })}
            onSuccess={(result) => {
              setRegister(false);
              setCredential((result as DeviceRegistered).credential);
            }}
            submit="Register & show credential"
          />
        </Modal>
      )}
      {credential && <Credential value={credential} close={() => setCredential('')} />}
    </>
  );
}

function Users() {
  const [offset, setOffset] = useState(0);
  const [create, setCreate] = useState(false);
  const query = useList<UserOut>('/users', offset);
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>User management</h2>
        <button className="button primary" onClick={() => setCreate(true)}>
          <Plus size={16} />
          Create user
        </button>
      </div>
      <QueryState query={query} empty={!query.data?.items.length}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>User ID</th>
                <th>Role</th>
                <th>Access</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {query.data?.items.map((user) => (
                <UserRow key={user.id} user={user} />
              ))}
            </tbody>
          </table>
        </div>
      </QueryState>
      <Pagination total={query.data?.total || 0} offset={offset} onChange={setOffset} />
      {create && (
        <Modal title="Create a user" close={() => setCreate(false)}>
          <ResourceForm
            path="/users"
            fields={[
              { name: 'user_id', label: 'User ID', required: true, maxLength: 80 },
              {
                name: 'password',
                label: 'Initial password (12–128 characters)',
                type: 'password',
                required: true,
                min: 12,
                maxLength: 128,
              },
              {
                name: 'role',
                label: 'Role',
                required: true,
                options: ['operator', 'vendor', 'admin'].map((value) => ({
                  value,
                  label: human(value),
                })),
              },
            ]}
            transform={(values) => {
              if (String(values.password).length < 12)
                throw new Error('Password must contain at least 12 characters.');
              return values;
            }}
            onSuccess={() => setCreate(false)}
            submit="Create user"
          />
        </Modal>
      )}
    </section>
  );
}
function UserRow({ user }: { user: UserOut }) {
  const auth = useAuth();
  const update = useWrite(`/users/${user.id}`, 'PATCH');
  return (
    <tr>
      <td>
        {user.user_id}
        <small>Account ID: {user.id}</small>
      </td>
      <td>{user.role}</td>
      <td>{user.active ? 'Active' : 'Disabled'}</td>
      <td>
        <button
          className="button secondary small"
          disabled={user.id === auth.user?.id || update.isPending}
          onClick={() => update.mutate({ active: !user.active })}
        >
          {user.active ? 'Disable' : 'Enable'}
        </button>
        {update.error && <span role="alert">{update.error.message}</span>}
      </td>
    </tr>
  );
}
function Audit() {
  const [offset, setOffset] = useState(0);
  const query = useList<DecisionOut>('/audit', offset);
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>Audit trail</h2>
      </div>
      <QueryState query={query} empty={!query.data?.items.length}>
        {query.data?.items.map((record) => (
          <details className="history-detail" key={record.id}>
            <summary>
              {human(record.decision_type)} · {date(record.created_at)}
            </summary>
            <p>{record.rationale}</p>
            <p className="muted">
              Actor: {record.actor_id} · Batch: {record.batch_id || 'Not applicable'} · Policy:{' '}
              {record.policy_version}
            </p>
            <pre>{JSON.stringify(record.input_references, null, 2)}</pre>
          </details>
        ))}
      </QueryState>
      <Pagination total={query.data?.total || 0} offset={offset} onChange={setOffset} />
    </section>
  );
}
export function SettingsPage() {
  const { user, logout } = useAuth();
  return (
    <>
      <PageHeader
        title="Settings & access"
        description="Your session, role, and the operating boundaries of this workspace."
      />
      <section className="panel metadata-panel">
        <h2>Current session</h2>
        <dl className="metadata">
          <div>
            <dt>User ID</dt>
            <dd>{user?.user_id}</dd>
          </div>
          <div>
            <dt>Role</dt>
            <dd>{user?.role}</dd>
          </div>
          <div>
            <dt>Token storage</dt>
            <dd>In memory only. Reloading requires sign-in.</dd>
          </div>
        </dl>
        <p className="muted">
          Signing out clears the token and cached records from this browser. Stateless tokens remain
          valid on the server until expiry. Administrators can disable an account to block its
          existing tokens.
        </p>
        <button className="button secondary" onClick={logout}>
          Sign out
        </button>
      </section>
      <Notice>
        Risk rules are illustrative and configured on the backend. Raw MQ-135 response is
        uncalibrated. The interface does not estimate days remaining or certify produce condition.
      </Notice>
      {user?.role === 'admin' && (
        <>
          <Users />
          <Audit />
        </>
      )}
    </>
  );
}
