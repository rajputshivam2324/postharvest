import { useEffect, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, CircleDashed, LoaderCircle } from 'lucide-react';
import { api, type Page } from '../api/client';
import { useResource } from '../api/hooks';
import type {
  AssignmentOut,
  BatchOut,
  DeviceOut,
  DevicePairingOut,
  PairingOut,
  ReadingOut,
} from '../api/types';
import { date, human, Modal, Notice, Source } from './ui';

const POLL_MS = 4000;

function useSetupDevice(deviceId: string) {
  return useQuery({
    queryKey: ['setup-device', deviceId],
    queryFn: ({ signal }) => api<DeviceOut>(`/devices/${deviceId}`, { signal }),
    refetchInterval: (query) => (query.state.data?.paired_at ? false : POLL_MS),
  });
}

function Step({ done, children }: { done: boolean; children: string }) {
  return (
    <li data-state={done ? 'done' : 'waiting'}>
      {done ? <Check size={18} /> : <CircleDashed size={18} />}
      <span>{children}</span>
      <small>{done ? 'Done' : 'Waiting'}</small>
    </li>
  );
}

/** Shows, in plain words, whether a device has paired and sent its first reading. */
export function ReadingCheck({ deviceId }: { deviceId: string }) {
  const device = useSetupDevice(deviceId);
  const paired = Boolean(device.data?.paired_at);
  const reading = useQuery({
    queryKey: ['setup-reading', deviceId],
    queryFn: ({ signal }) =>
      api<ReadingOut | null>(`/devices/${deviceId}/readings/latest`, { signal }),
    enabled: paired,
    refetchInterval: (query) => (query.state.data ? false : POLL_MS),
  });
  const latest = reading.data ?? null;
  return (
    <div className="reading-check">
      <ol className="setup-steps">
        <Step done={paired}>The device has its credential</Step>
        <Step done={Boolean(latest)}>The first reading has arrived</Step>
      </ol>
      {latest ? (
        <div className="notice" role="status">
          <Check size={18} />
          <div>
            Received {date(latest.source_timestamp)}: {latest.temperature_c.toFixed(1)} °C,{' '}
            {latest.humidity_pct.toFixed(0)} % humidity, gas {latest.gas_adc} ADC.{' '}
            <Source simulated={latest.simulated} />
            {latest.batch_id === null && (
              <> The device is not assigned to a batch yet, so this reading is kept on its own.</>
            )}
          </div>
        </div>
      ) : (
        <p className="muted" role="status">
          <LoaderCircle size={15} className="spin" />{' '}
          {paired
            ? 'Waiting for the first reading. Devices report every few minutes.'
            : 'Waiting for the device to pair.'}
        </p>
      )}
      {device.isError && <Notice danger>Unable to check the device: {device.error.message}</Notice>}
    </div>
  );
}

/** The one-time code an operator reads out or types into the device, with a live check. */
export function PairingPanel({
  deviceId,
  code,
  expiresAt,
}: {
  deviceId: string;
  code: string;
  expiresAt: string;
}) {
  const [current, setCurrent] = useState({ code, expiresAt });
  const [now, setNow] = useState(() => Date.now());
  const device = useSetupDevice(deviceId);
  const client = useQueryClient();
  const again = useMutation({
    mutationFn: () => api<PairingOut>(`/devices/${deviceId}/pairing`, { method: 'POST' }),
    onSuccess: (result) => {
      setCurrent({ code: result.pairing_code, expiresAt: result.expires_at });
      void client.invalidateQueries({ queryKey: ['setup-device', deviceId] });
    },
  });
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(timer);
  }, []);
  const paired = Boolean(device.data?.paired_at);
  const remaining = new Date(current.expiresAt).getTime() - now;
  return (
    <div className="pairing-panel">
      {!paired && (
        <>
          <p className="muted">
            Enter this code when the device asks for it. It works once
            {remaining > 0
              ? ` and expires in about ${Math.max(1, Math.ceil(remaining / 60000))} minutes.`
              : ', but it has expired.'}
          </p>
          <output className="pairing-code" aria-label="Pairing code">
            {current.code}
          </output>
          {remaining <= 0 && (
            <button
              type="button"
              className="button secondary"
              disabled={again.isPending}
              onClick={() => again.mutate()}
            >
              Get a new code
            </button>
          )}
          {again.error && <Notice danger>{again.error.message}</Notice>}
        </>
      )}
      <ReadingCheck deviceId={deviceId} />
    </div>
  );
}

function useFreeBatches() {
  return useResource<Page<BatchOut>>('/batches?limit=200');
}

/** Create a pairing code for a new ESP32, optionally assigning it to a batch at once. */
export function PairDeviceModal({ close, batchId }: { close: () => void; batchId?: string }) {
  const batches = useFreeBatches();
  const client = useQueryClient();
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<DevicePairingOut>('/devices/pairing', { method: 'POST', body }),
    onSuccess: () => void client.invalidateQueries(),
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const batch = String(data.get('batch_id') || '');
    create.mutate({
      identifier: String(data.get('identifier') || ''),
      simulated: data.get('simulated') === 'true',
      ...(batch ? { batch_id: batch } : {}),
    });
  }
  return (
    <Modal title="Pair a new ESP32" close={close}>
      {create.data ? (
        <PairingPanel
          deviceId={create.data.id}
          code={create.data.pairing_code}
          expiresAt={create.data.pairing_expires_at}
        />
      ) : (
        <form className="resource-form" onSubmit={submit}>
          <p className="muted">
            You get a short code instead of a long credential. Nothing is copied into the firmware.
          </p>
          <label>
            Device name
            <input name="identifier" required maxLength={100} autoComplete="off" />
          </label>
          <label>
            Data source
            <select name="simulated" defaultValue="false" aria-label="Data source">
              <option value="false">Real hardware</option>
              <option value="true">Simulator</option>
            </select>
          </label>
          <label>
            Batch (optional)
            <select name="batch_id" defaultValue={batchId ?? ''} aria-label="Batch">
              <option value="">Assign later</option>
              {batches.data?.items
                .filter((b) => !b.archived)
                .map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.identifier}
                  </option>
                ))}
            </select>
          </label>
          {create.error && <Notice danger>{create.error.message}</Notice>}
          <button className="button primary" disabled={create.isPending}>
            {create.isPending ? 'Creating…' : 'Create pairing code'}
          </button>
        </form>
      )}
    </Modal>
  );
}

/** Issue a fresh code for a device that is unpaired or needs to be paired again. */
export function PairAgainModal({ device, close }: { device: DeviceOut; close: () => void }) {
  const client = useQueryClient();
  const issue = useMutation({
    mutationFn: () => api<PairingOut>(`/devices/${device.id}/pairing`, { method: 'POST' }),
    onSuccess: () => void client.invalidateQueries(),
  });
  return (
    <Modal title={`Pair ${device.identifier}`} close={close}>
      {issue.data ? (
        <PairingPanel
          deviceId={device.id}
          code={issue.data.pairing_code}
          expiresAt={issue.data.expires_at}
        />
      ) : (
        <>
          <p>
            {device.paired_at
              ? 'The device keeps working with its current credential until the new code is used.'
              : 'This device has not received its credential yet.'}
          </p>
          {issue.error && <Notice danger>{issue.error.message}</Notice>}
          <button
            className="button primary"
            disabled={issue.isPending}
            onClick={() => issue.mutate()}
          >
            {issue.isPending ? 'Creating…' : 'Create a new code'}
          </button>
        </>
      )}
    </Modal>
  );
}

/** Point an existing device at a batch, moving it only when the operator says so. */
export function AssignToBatchModal({ device, close }: { device: DeviceOut; close: () => void }) {
  const batches = useFreeBatches();
  const client = useQueryClient();
  const [batchId, setBatchId] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const moving = device.batch_id !== null && batchId !== '' && batchId !== device.batch_id;
  const current = batches.data?.items.find((b) => b.id === device.batch_id);
  const assign = useMutation({
    mutationFn: () =>
      api<AssignmentOut>(`/devices/${device.id}/assignment`, {
        method: 'POST',
        body: { batch_id: batchId, replace: moving },
      }),
    onSuccess: () => {
      void client.invalidateQueries();
      close();
    },
  });
  return (
    <Modal title={`Assign ${device.identifier}`} close={close}>
      <label className="stacked-field">
        Batch
        <select
          value={batchId}
          aria-label="Batch"
          onChange={(event) => {
            setBatchId(event.target.value);
            setConfirmed(false);
          }}
        >
          <option value="">Choose a batch</option>
          {batches.data?.items
            .filter((b) => !b.archived)
            .map((b) => (
              <option key={b.id} value={b.id}>
                {b.identifier}
              </option>
            ))}
        </select>
      </label>
      {moving && (
        <label className="check-row">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>
            Move it from {current?.identifier ?? 'its current batch'}. It will stop reporting there.
            Readings already recorded stay where they are.
          </span>
        </label>
      )}
      {assign.error && <Notice danger>{assign.error.message}</Notice>}
      <button
        className="button primary"
        disabled={!batchId || (moving && !confirmed) || assign.isPending}
        onClick={() => assign.mutate()}
      >
        {moving ? 'Move device' : 'Assign device'}
      </button>
    </Modal>
  );
}

/** Choose a free, paired device for a batch that has none. */
export function AssignDeviceModal({ batch, close }: { batch: BatchOut; close: () => void }) {
  const free = useResource<Page<DeviceOut>>('/devices?unassigned=true&limit=200');
  const client = useQueryClient();
  const [deviceId, setDeviceId] = useState('');
  const options = free.data?.items.filter((d) => d.active && d.paired_at) ?? [];
  const assign = useMutation({
    mutationFn: () =>
      api<AssignmentOut>(`/devices/${deviceId}/assignment`, {
        method: 'POST',
        body: { batch_id: batch.id },
      }),
    onSuccess: () => {
      void client.invalidateQueries();
      close();
    },
  });
  return (
    <Modal title={`Add a device to ${batch.identifier}`} close={close}>
      {options.length === 0 && !free.isPending ? (
        <Notice>
          No free device. Pair a new ESP32 from the Devices page, or release one from another batch.
        </Notice>
      ) : (
        <label className="stacked-field">
          Free device
          <select
            value={deviceId}
            aria-label="Free device"
            onChange={(event) => setDeviceId(event.target.value)}
          >
            <option value="">Choose a device</option>
            {options.map((d) => (
              <option key={d.id} value={d.id}>
                {d.identifier} ({human(d.connection_status)}
                {d.simulated ? ', simulator' : ''})
              </option>
            ))}
          </select>
        </label>
      )}
      {assign.error && <Notice danger>{assign.error.message}</Notice>}
      <button
        className="button primary"
        disabled={!deviceId || assign.isPending}
        onClick={() => assign.mutate()}
      >
        Assign device
      </button>
    </Modal>
  );
}

export function ReleaseDeviceModal({ device, close }: { device: DeviceOut; close: () => void }) {
  const client = useQueryClient();
  const release = useMutation({
    mutationFn: () => api<DeviceOut>(`/devices/${device.id}/assignment`, { method: 'DELETE' }),
    onSuccess: () => {
      void client.invalidateQueries();
      close();
    },
  });
  return (
    <Modal title={`Release ${device.identifier}?`} close={close}>
      <p>
        It stops reporting to its batch and can be used for another one. Readings already recorded
        stay in that batch.
      </p>
      {release.error && <Notice danger>{release.error.message}</Notice>}
      <button
        className="button primary"
        disabled={release.isPending}
        onClick={() => release.mutate()}
      >
        Release device
      </button>
    </Modal>
  );
}
