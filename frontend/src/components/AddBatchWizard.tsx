import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api, type Page } from '../api/client';
import { useResource } from '../api/hooks';
import { useAuth } from '../auth';
import type { AssignmentOut, BatchOut, DeviceOut, DevicePairingOut, VendorOut } from '../api/types';
import { human, Modal, Notice } from './ui';
import { PairingPanel, ReadingCheck } from './DeviceSetup';

type Details = {
  identifier: string;
  commodity: string;
  quantity: number;
  unit: string;
  storage_location: string;
  notes: string;
  variety: string;
  starting_ripeness: string;
  owner_id: string;
};
type Sensor =
  { kind: 'later' } | { kind: 'free'; deviceId: string } | { kind: 'new'; name: string };
type Done =
  | { kind: 'later' }
  | { kind: 'free'; deviceId: string }
  | { kind: 'new'; pairing: DevicePairingOut };

const TITLES = ['Batch details', 'Sensor', 'Connect'];

function text(data: FormData, name: string) {
  return String(data.get(name) ?? '').trim();
}

export function AddBatchWizard({ close }: { close: () => void }) {
  const { user } = useAuth();
  const client = useQueryClient();
  const canShare = user?.role !== 'vendor';
  const vendors = useResource<Page<VendorOut>>('/vendors?limit=200', canShare);
  const free = useResource<Page<DeviceOut>>('/devices?unassigned=true&limit=200');
  const [step, setStep] = useState(0);
  const [details, setDetails] = useState<Details | null>(null);
  const [sensor, setSensor] = useState<Sensor>({ kind: 'later' });
  const [batch, setBatch] = useState<BatchOut | null>(null);
  const [done, setDone] = useState<Done | null>(null);
  const pickable = free.data?.items.filter((d) => d.active && d.paired_at) ?? [];

  const create = useMutation({
    mutationFn: async () => {
      if (!details) throw new Error('Enter the batch details first.');
      // The batch is created once. If the sensor step fails, a retry reuses it.
      let created = batch;
      if (!created) {
        const { variety, starting_ripeness, owner_id, ...rest } = details;
        created = await api<BatchOut>('/batches', {
          method: 'POST',
          body: {
            ...rest,
            notes: rest.notes || undefined,
            ...(owner_id ? { owner_id } : {}),
            attributes: {
              ...(variety ? { variety } : {}),
              ...(starting_ripeness ? { starting_ripeness } : {}),
            },
          },
        });
        setBatch(created);
      }
      if (sensor.kind === 'free') {
        await api<AssignmentOut>(`/devices/${sensor.deviceId}/assignment`, {
          method: 'POST',
          body: { batch_id: created.id },
        });
        return { kind: 'free', deviceId: sensor.deviceId } as Done;
      }
      if (sensor.kind === 'new') {
        const pairing = await api<DevicePairingOut>('/devices/pairing', {
          method: 'POST',
          body: { identifier: sensor.name, simulated: false, batch_id: created.id },
        });
        return { kind: 'new', pairing } as Done;
      }
      return { kind: 'later' } as Done;
    },
    onSuccess: (result) => {
      setDone(result);
      setStep(2);
      void client.invalidateQueries();
    },
  });

  function saveDetails(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setDetails({
      identifier: text(data, 'identifier'),
      commodity: text(data, 'commodity'),
      quantity: Number(text(data, 'quantity')),
      unit: text(data, 'unit'),
      storage_location: text(data, 'storage_location'),
      notes: text(data, 'notes'),
      variety: text(data, 'variety'),
      starting_ripeness: text(data, 'starting_ripeness'),
      owner_id: text(data, 'owner_id'),
    });
    setStep(1);
  }
  function chooseSensor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const kind = text(data, 'kind');
    if (kind === 'free') setSensor({ kind, deviceId: text(data, 'deviceId') });
    else if (kind === 'new') setSensor({ kind, name: text(data, 'name') });
    else setSensor({ kind: 'later' });
    create.mutate();
  }
  const d = details;
  return (
    <Modal title="Add a batch" close={close} wide>
      <ol className="wizard-steps" aria-label="Progress">
        {TITLES.map((title, index) => (
          <li key={title} aria-current={index === step ? 'step' : undefined}>
            <span>{index + 1}</span> {title}
          </li>
        ))}
      </ol>

      {step === 0 && (
        <form className="resource-form wizard-grid" onSubmit={saveDetails}>
          <label>
            Batch identifier
            <input name="identifier" required maxLength={100} defaultValue={d?.identifier} />
          </label>
          <label>
            Commodity
            <input
              name="commodity"
              required
              maxLength={80}
              defaultValue={d?.commodity ?? 'tomato'}
            />
          </label>
          <label>
            Quantity
            <input
              name="quantity"
              type="number"
              min={0.001}
              step="any"
              required
              defaultValue={d?.quantity}
            />
          </label>
          <label>
            Unit
            <input name="unit" required maxLength={20} defaultValue={d?.unit ?? 'kg'} />
          </label>
          <label className="span-2">
            Storage location
            <input
              name="storage_location"
              required
              maxLength={200}
              defaultValue={d?.storage_location}
            />
          </label>
          <label>
            Variety (optional)
            <input name="variety" maxLength={100} defaultValue={d?.variety} />
          </label>
          <label>
            Starting ripeness (optional)
            <input name="starting_ripeness" maxLength={100} defaultValue={d?.starting_ripeness} />
          </label>
          {canShare && (
            <label className="span-2">
              Share with a vendor (optional)
              <select name="owner_id" defaultValue={d?.owner_id ?? ''} aria-label="Share with">
                <option value="">Keep it to our team</option>
                {vendors.data?.items.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.user_id}
                  </option>
                ))}
              </select>
              <span className="field-hint">
                A vendor sees this batch read-only, with its devices and readings.
              </span>
            </label>
          )}
          <label className="span-2">
            Notes
            <textarea name="notes" rows={3} maxLength={2000} defaultValue={d?.notes} />
          </label>
          <button className="button primary span-2">Continue</button>
        </form>
      )}

      {step === 1 && (
        <form className="resource-form" onSubmit={chooseSensor}>
          <p className="muted">
            One device monitors one batch at a time. You can move it to the next batch later.
          </p>
          <fieldset>
            <legend>Which sensor will watch this batch?</legend>
            <label className="check-row">
              <input
                type="radio"
                name="kind"
                value="new"
                checked={sensor.kind === 'new'}
                onChange={() => setSensor({ kind: 'new', name: '' })}
              />
              <span>Pair a new ESP32 with a code</span>
            </label>
            {sensor.kind === 'new' && (
              <label>
                Device name
                <input name="name" required maxLength={100} placeholder="e.g. cold-room-1" />
              </label>
            )}
            <label className="check-row">
              <input
                type="radio"
                name="kind"
                value="free"
                disabled={pickable.length === 0}
                checked={sensor.kind === 'free'}
                onChange={() => setSensor({ kind: 'free', deviceId: pickable[0]?.id ?? '' })}
              />
              <span>
                Use a free device{' '}
                {pickable.length === 0 ? '(none available)' : `(${pickable.length} available)`}
              </span>
            </label>
            {sensor.kind === 'free' && (
              <label>
                Free device
                <select name="deviceId" defaultValue={sensor.deviceId} aria-label="Free device">
                  {pickable.map((device) => (
                    <option key={device.id} value={device.id}>
                      {device.identifier} ({human(device.connection_status)}
                      {device.simulated ? ', simulator' : ''})
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="check-row">
              <input
                type="radio"
                name="kind"
                value="later"
                checked={sensor.kind === 'later'}
                onChange={() => setSensor({ kind: 'later' })}
              />
              <span>Decide later</span>
            </label>
          </fieldset>
          {create.error && (
            <Notice danger>
              {batch
                ? `The batch “${batch.identifier}” was created, but the sensor step failed: `
                : ''}
              {create.error.message}
            </Notice>
          )}
          <div className="actions">
            <button
              type="button"
              className="button secondary"
              disabled={Boolean(batch) || create.isPending}
              onClick={() => setStep(0)}
            >
              Back
            </button>
            <button className="button primary" disabled={create.isPending}>
              {create.isPending ? 'Creating…' : batch ? 'Retry sensor step' : 'Create batch'}
            </button>
          </div>
        </form>
      )}

      {step === 2 && batch && done && (
        <div className="wizard-done">
          <Notice>
            Batch <strong>{batch.identifier}</strong> is registered.
          </Notice>
          {done.kind === 'new' && (
            <PairingPanel
              deviceId={done.pairing.id}
              code={done.pairing.pairing_code}
              expiresAt={done.pairing.pairing_expires_at}
            />
          )}
          {done.kind === 'free' && <ReadingCheck deviceId={done.deviceId} />}
          {done.kind === 'later' && (
            <p className="muted">
              No sensor yet. Add one from the batch page or the Devices page when it is ready.
            </p>
          )}
          <div className="actions">
            <Link className="button primary" to={`/app/batches/${batch.id}`} onClick={close}>
              Open batch
            </Link>
            <button className="button secondary" onClick={close}>
              Close
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
