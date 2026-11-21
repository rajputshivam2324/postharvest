import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, Plus, Layers, Radio, AlertTriangle, ClipboardCheck } from 'lucide-react';
import { useAuth } from '../auth';
import { useList, useResource, useWrite } from '../api/hooks';
import { params, type Page } from '../api/client';
import type {
  AlertOut,
  AttemptOut,
  BatchOut,
  DeviceOut,
  DemoBatchOut,
  PriorityOut,
  ReadingOut,
} from '../api/types';
import {
  Badge,
  date,
  Empty,
  human,
  Notice,
  PageHeader,
  Pagination,
  QueryState,
  Refresh,
  Source,
} from '../components/ui';
import { AddBatchWizard } from '../components/AddBatchWizard';

function LatestReading({ batchId }: { batchId: string }) {
  const latest = useResource<ReadingOut | null>(`/batches/${batchId}/readings/latest`);
  const reading = latest.data;
  const device = useResource<DeviceOut>(`/devices/${reading?.device_id || ''}`, !!reading);
  if (latest.isError) return <span className="error-text">Readings unavailable</span>;
  if (latest.isPending) return <span className="muted">Loading readings…</span>;
  if (!reading) return <span className="muted">No readings yet</span>;
  return (
    <div className="reading-inline">
      <strong>
        {reading.temperature_c.toFixed(1)} °C <span>·</span> {reading.humidity_pct.toFixed(1)}% RH
      </strong>
      <small>
        {date(reading.source_timestamp)} <Source simulated={reading.simulated} />
        {reading.warming_up && ' · Warming up'}
        {device.data && ` · ${human(device.data.connection_status)}`}
        {device.isError && ' · Freshness unavailable'}
      </small>
    </div>
  );
}

export function Overview() {
  const cache = useQueryClient();
  const { user } = useAuth();
  const [create, setCreate] = useState(false);
  const batches = useList<BatchOut>('/batches', 0, {}, 6);
  const priorities = useResource<PriorityOut>('/priorities?limit=5');
  const devices = useList<DeviceOut>('/devices', 0, {}, 200);
  const alerts = useList<AlertOut>('/alerts', 0, { resolved: false, acknowledged: false }, 3);
  return (
    <>
      <PageHeader
        title="A clearer view of your harvest."
        description="Inspect what needs attention. Keep every batch in view."
        action={
          <>
            <Refresh
              refresh={() => {
                void cache.invalidateQueries();
              }}
              fetching={
                batches.isFetching ||
                devices.isFetching ||
                priorities.isFetching ||
                alerts.isFetching
              }
            />
            {user?.role !== 'vendor' && (
              <button className="button primary" onClick={() => setCreate(true)}>
                <Plus size={17} />
                Add batch
              </button>
            )}
          </>
        }
      />
      <div className="summary-strip">
        {[
          [Layers, 'Active batches', batches.data?.total],
          [ClipboardCheck, 'Inspection priorities', priorities.data?.total],
          [Radio, 'Registered devices', devices.data?.total],
          [AlertTriangle, 'Unacknowledged alerts', alerts.data?.total],
        ].map(([Icon, label, value]) => {
          const I = Icon as typeof Layers;
          return (
            <div key={String(label)}>
              <I size={19} />
              <span>{String(label)}</span>
              <strong>{value === undefined ? '—' : String(value)}</strong>
            </div>
          );
        })}
      </div>
      <div className="overview-grid">
        <section className="panel attention-panel">
          <div className="panel-heading">
            <div>
              <h2>Inspection queue</h2>
              <p>Advisory priorities, grounded in evidence.</p>
            </div>
            <Link className="text-link" to="/app/priorities">
              View all <ArrowRight size={16} />
            </Link>
          </div>
          <QueryState query={priorities} empty={!priorities.data?.items.length}>
            {priorities.data?.items.map((item) => (
              <Link key={item.batch_id} className="queue-row" to={`/app/batches/${item.batch_id}`}>
                <span className="rank">{String(item.rank).padStart(2, '0')}</span>
                <div>
                  <strong>{item.identifier}</strong>
                  <span>
                    <Badge status={item.status} />
                    {item.simulated && <Source simulated />}
                  </span>
                </div>
                <ArrowRight size={18} />
              </Link>
            ))}
          </QueryState>
          {priorities.data && !priorities.data.ranking_meaningful && (
            <p className="panel-footnote">
              Compare at least two assessed batches for meaningful ranking.
            </p>
          )}
        </section>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Your next steps</h2>
              <p>From setup to daily review.</p>
            </div>
          </div>
          <div className="next-steps">
            <Link to="/app/batches">
              <Layers size={20} />
              <div>
                <strong>Register & manage batches</strong>
                <p>Keep quantity, location and notes current.</p>
              </div>
              <ArrowRight size={17} />
            </Link>
            <Link to="/app/devices">
              <Radio size={20} />
              <div>
                <strong>Connect your devices</strong>
                <p>Review freshness and record a baseline.</p>
              </div>
              <ArrowRight size={17} />
            </Link>
            <Link to="/app/alerts">
              <ClipboardCheck size={20} />
              <div>
                <strong>Review & acknowledge alerts</strong>
                <p>Record a human response to each change.</p>
              </div>
              <ArrowRight size={17} />
            </Link>
          </div>
          <QueryState query={devices}>
            <div className="device-summary">
              {devices.data?.items.filter(
                (item) =>
                  item.connection_status === 'stale' || item.connection_status === 'never_seen',
              ).length || 0}{' '}
              devices in this page need a connectivity check.
              <br />
              <small>
                {devices.data && devices.data.total > 200
                  ? `Showing 200 of ${devices.data.total} devices.`
                  : 'Freshness is reported by the backend.'}
              </small>
            </div>
          </QueryState>
        </section>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Latest batch readings</h2>
            <p>Source timestamps · refreshed every minute while this page is active.</p>
          </div>
          <Link className="text-link" to="/app/batches">
            All batches <ArrowRight size={16} />
          </Link>
        </div>
        <QueryState query={batches} empty={!batches.data?.items.length}>
          <div className="table-wrap overview-readings">
            <table>
              <thead>
                <tr>
                  <th>Batch / location</th>
                  <th>Operational indicator</th>
                  <th>Latest reading</th>
                  <th>Review</th>
                </tr>
              </thead>
              <tbody>
                {batches.data?.items.map((batch) => (
                  <tr key={batch.id}>
                    <td>
                      <strong>{batch.identifier}</strong>
                      <small>
                        {batch.commodity} · {batch.storage_location}
                      </small>
                    </td>
                    <td>
                      <Badge status={batch.status} />
                    </td>
                    <td>
                      <LatestReading batchId={batch.id} />
                    </td>
                    <td>
                      <Link className="text-link" to={`/app/batches/${batch.id}`}>
                        Inspect <ArrowRight size={15} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </QueryState>
      </section>
      <QueryState query={alerts}>
        {!!alerts.data?.items.length && (
          <section className="panel">
            <div className="panel-heading">
              <h2>Recent alerts</h2>
              <Link to="/app/alerts" className="text-link">
                Review alerts <ArrowRight size={16} />
              </Link>
            </div>
            {alerts.data.items.map((alert) => (
              <div className="alert-preview" key={alert.id}>
                <BellIcon />
                <p>
                  {alert.message}
                  <small>
                    {date(alert.created_at)} · {human(alert.delivery_status)}
                  </small>
                </p>
              </div>
            ))}
          </section>
        )}
      </QueryState>
      {create && <AddBatchWizard close={() => setCreate(false)} />}
    </>
  );
}
function BellIcon() {
  return <AlertTriangle size={19} />;
}

export function Batches() {
  const navigate = useNavigate();
  const demo = useWrite<DemoBatchOut>('/demo/batches');
  const { user } = useAuth();
  const [offset, setOffset] = useState(0);
  const [create, setCreate] = useState(false);
  const [filters, setFilters] = useState({
    commodity: '',
    storage_location: '',
    status: '',
    archived: false,
  });
  const query = useList<BatchOut>('/batches', offset, filters);
  const change = (name: string, value: string | boolean) => {
    setFilters({ ...filters, [name]: value });
    setOffset(0);
  };
  return (
    <>
      <PageHeader
        title="Batches"
        description="A record of what you store, where it is, and how it is changing."
        action={
          <>
            <Refresh refresh={() => void query.refetch()} fetching={query.isFetching} />
            {user?.role !== 'vendor' && (
              <button
                className="button secondary"
                disabled={demo.isPending}
                onClick={() =>
                  demo.mutate(undefined, {
                    onSuccess: (result) => navigate(`/app/batches/${result.batch.id}`),
                  })
                }
              >
                {demo.isPending ? 'Seeding demo…' : 'Seed demo batch'}
              </button>
            )}
            {user?.role !== 'vendor' && (
              <button className="button primary" onClick={() => setCreate(true)}>
                <Plus size={17} />
                Add batch
              </button>
            )}
          </>
        }
      />
      {demo.error && <Notice danger>{demo.error.message}</Notice>}
      {user?.role !== 'vendor' && (
        <p className="muted">
          Seed demo batch creates simulated readings, a baseline, observations and an assessment.
          Open its Assessment tab to review AI output when the explanation worker finishes.
        </p>
      )}
      <div className="filters">
        <label>
          Commodity
          <input
            value={filters.commodity}
            onChange={(event) => change('commodity', event.target.value)}
            placeholder="All commodities"
          />
        </label>
        <label>
          Storage location
          <input
            value={filters.storage_location}
            onChange={(event) => change('storage_location', event.target.value)}
            placeholder="All locations"
          />
        </label>
        <label>
          Risk indicator
          <select value={filters.status} onChange={(event) => change('status', event.target.value)}>
            <option value="">All indicators</option>
            <option value="fresh">Low risk</option>
            <option value="early_decay">Elevated risk</option>
            <option value="spoiling">High risk</option>
            <option value="insufficient_data">Insufficient evidence</option>
            <option value="unknown">Not assessed</option>
          </select>
        </label>
        <label>
          Records
          <select
            value={String(filters.archived)}
            onChange={(event) => change('archived', event.target.value === 'true')}
          >
            <option value="false">Active batches</option>
            <option value="true">Archived batches</option>
          </select>
        </label>
      </div>
      <section className="panel">
        <QueryState query={query}>
          {query.data?.items.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Batch</th>
                    <th>Quantity</th>
                    <th>Storage location</th>
                    <th>Indicator</th>
                    <th>Review</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.items.map((batch) => (
                    <tr key={batch.id}>
                      <td>
                        <strong>{batch.identifier}</strong>
                        <small>{batch.commodity}</small>
                        {batch.attributes.simulated === true && <Source simulated />}
                      </td>
                      <td>
                        {batch.quantity} {batch.unit}
                      </td>
                      <td>{batch.storage_location}</td>
                      <td>
                        <Badge status={batch.status} />
                      </td>
                      <td>
                        <Link className="text-link" to={`/app/batches/${batch.id}`}>
                          Inspect <ArrowRight size={16} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="No batches match">
              Adjust your filters or register your first batch.
            </Empty>
          )}
        </QueryState>
        <Pagination total={query.data?.total || 0} offset={offset} onChange={setOffset} />
      </section>
      {create && <AddBatchWizard close={() => setCreate(false)} />}
    </>
  );
}

export function Priorities() {
  const [offset, setOffset] = useState(0);
  const query = useResource<PriorityOut>(`/priorities${params({ offset, limit: 12 })}`);
  return (
    <>
      <PageHeader
        title="Inspection priorities"
        description="A transparent order for human review, with the factors behind each rank."
        action={<Refresh refresh={() => void query.refetch()} fetching={query.isFetching} />}
      />
      <Notice>
        Ranking is advisory. Review evidence before sale, disposal, or any consequential handling
        decision.
        {query.data &&
          !query.data.ranking_meaningful &&
          ' Ranking needs at least two assessed batches.'}
      </Notice>
      <section className="panel">
        <QueryState query={query} empty={!query.data?.items.length}>
          {query.data?.items.map((item) => (
            <div className="priority-row" key={item.batch_id}>
              <span className="rank">{String(item.rank).padStart(2, '0')}</span>
              <div>
                <Link to={`/app/batches/${item.batch_id}`} className="priority-title">
                  {item.identifier}
                  <ArrowRight size={17} />
                </Link>
                <Badge status={item.status} />
                {item.simulated && <Source simulated />}
                <p>{item.advisory}</p>
                <div className="factors">
                  {Object.entries(item.factors).map(([key, value]) => (
                    <span key={key}>
                      {human(key)} <strong>{value.toFixed(2)}</strong>
                    </span>
                  ))}
                </div>
                {item.override_record_id && (
                  <p className="muted">
                    Operator override · computed rank {item.computed_rank} · requested rank{' '}
                    {item.override_rank ?? 'cleared'}
                    <br />
                    {item.override_rationale}
                  </p>
                )}
              </div>
              <div className="priority-score">
                <strong>{item.score.toFixed(1)}</strong>
                <small>Priority score</small>
              </div>
            </div>
          ))}
        </QueryState>
        <Pagination total={query.data?.total || 0} offset={offset} onChange={setOffset} />
      </section>
    </>
  );
}

function AlertCard({ alert }: { alert: AlertOut }) {
  const { user } = useAuth();
  const ack = useWrite(`/alerts/${alert.id}/acknowledge`);
  const [showAttempts, setShowAttempts] = useState(false);
  const attempts = useResource<Page<AttemptOut>>(
    `/alerts/${alert.id}/attempts?limit=200`,
    showAttempts,
  );
  return (
    <article className="alert-card">
      <div className="alert-card-head">
        <span className={`badge ${alert.severity === 'critical' ? 'spoiling' : 'early_decay'}`}>
          {human(alert.severity)}
        </span>
        <span className="muted">{date(alert.created_at)}</span>
      </div>
      <h2>{alert.message}</h2>
      <p className="muted">
        Trigger: {human(alert.trigger_key)} · Delivery:{' '}
        <strong>{human(alert.delivery_status)}</strong>
      </p>
      <p>
        {alert.resolved_at ? `Resolved ${date(alert.resolved_at)}` : 'Unresolved'}
        {alert.acknowledged_at
          ? ` · Acknowledged ${date(alert.acknowledged_at)}`
          : ' · Awaiting acknowledgement'}
      </p>
      <div className="actions">
        <Link className="text-link" to={`/app/batches/${alert.batch_id}`}>
          Inspect batch <ArrowRight size={16} />
        </Link>
        <button
          className="button secondary"
          onClick={() => setShowAttempts(!showAttempts)}
          aria-expanded={showAttempts}
        >
          Delivery history
        </button>
        {user?.role !== 'vendor' && !alert.acknowledged_at && (
          <button
            className="button primary"
            disabled={ack.isPending}
            onClick={() => ack.mutate(undefined)}
          >
            {ack.isPending ? 'Acknowledging…' : 'Acknowledge'}
          </button>
        )}
      </div>
      {ack.error && <Notice danger>{ack.error.message}</Notice>}
      {showAttempts && (
        <QueryState query={attempts} empty={!attempts.data?.items.length}>
          {attempts.data?.items.map((attempt) => (
            <p key={attempt.id}>
              {attempt.provider} · {human(attempt.status)} · {date(attempt.created_at)}
            </p>
          ))}
        </QueryState>
      )}
    </article>
  );
}
export function Alerts() {
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState('open');
  const query = useList<AlertOut>(
    '/alerts',
    offset,
    filter === 'open'
      ? { resolved: false }
      : filter === 'unacknowledged'
        ? { acknowledged: false, resolved: false }
        : {},
  );
  return (
    <>
      <PageHeader
        title="Alerts"
        description="Review changes and record a human response. Acknowledgement does not resolve an alert."
        action={<Refresh refresh={() => void query.refetch()} fetching={query.isFetching} />}
      />
      <div className="tabs" role="group" aria-label="Alert filters">
        {[
          ['open', 'Unresolved'],
          ['unacknowledged', 'Awaiting acknowledgement'],
          ['all', 'All alerts'],
        ].map(([key, label]) => (
          <button
            key={key}
            aria-pressed={filter === key}
            className={filter === key ? 'active' : ''}
            onClick={() => {
              setFilter(key);
              setOffset(0);
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <Notice>
        Mocked delivery is a local test result. It does not mean an external notification was sent.
      </Notice>
      <QueryState query={query} empty={!query.data?.items.length}>
        {query.data?.items.map((alert) => (
          <AlertCard key={alert.id} alert={alert} />
        ))}
      </QueryState>
      <Pagination total={query.data?.total || 0} offset={offset} onChange={setOffset} />
    </>
  );
}
