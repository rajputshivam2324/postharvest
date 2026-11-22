import { lazy, Suspense, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Plus } from 'lucide-react';
import { useAuth } from '../auth';
import { useList, useResource, useWrite } from '../api/hooks';
import { type Page, params } from '../api/client';
import type {
  AssessmentOut,
  BatchOut,
  DecisionOut,
  DeviceOut,
  ObservationOut,
  ReadingOut,
} from '../api/types';
import {
  Badge,
  date,
  Empty,
  human,
  Modal,
  Notice,
  PageHeader,
  Pagination,
  QueryState,
  Refresh,
  Source,
} from '../components/ui';
import { localNow, ResourceForm, type Field } from '../components/ResourceForm';
import { AssignDeviceModal, PairDeviceModal } from '../components/DeviceSetup';
const SensorChart = lazy(() => import('../components/SensorChart'));

const observationFields: Field[] = [
  {
    name: 'observation_type',
    label: 'Observation type',
    required: true,
    options: ['routine', 'start_condition', 'final_outcome', 'correction'].map((value) => ({
      value,
      label: human(value),
    })),
  },
  {
    name: 'observed_at',
    label: 'Observed at (your local time)',
    type: 'datetime-local',
    required: true,
  },
  { name: 'condition', label: 'Visual condition', required: true, maxLength: 500 },
  { name: 'firmness', label: 'Firmness', maxLength: 100 },
  {
    name: 'visible_mould',
    label: 'Visible mould',
    options: [
      { value: 'true', label: 'Observed' },
      { value: 'false', label: 'Not observed' },
    ],
  },
  { name: 'weight_kg', label: 'Weight (kg)', type: 'number', min: 0, step: 'any' },
  { name: 'photo_reference', label: 'Photo reference (no file upload)', maxLength: 500 },
  { name: 'corrects_id', label: 'Corrected observation ID (corrections only)', maxLength: 36 },
  { name: 'notes', label: 'Notes', type: 'textarea', maxLength: 2000 },
];

function ObservationForm({ id, close }: { id: string; close: () => void }) {
  return (
    <Modal title="Record an observation" close={close}>
      <p className="muted">
        Observations are append-only. Use a correction with the original ID to correct an earlier
        record.
      </p>
      <ResourceForm
        path={`/batches/${id}/observations`}
        fields={observationFields.map((f) =>
          f.name === 'observed_at' ? { ...f, value: localNow() } : f,
        )}
        transform={(values) => {
          if ((values.observation_type === 'correction') !== !!values.corrects_id)
            throw new Error(
              'Corrections require an original observation ID; other observation types cannot include one.',
            );
          return {
            ...values,
            ...(values.visible_mould !== undefined
              ? { visible_mould: values.visible_mould === 'true' }
              : {}),
          };
        }}
        onSuccess={close}
        submit="Record observation"
      />
    </Modal>
  );
}

function Assessment({ assessment }: { assessment: AssessmentOut }) {
  const ai = assessment.ai_status === 'ok' ? assessment.ai_explanation : null;
  return (
    <div className="assessment-content">
      <div className="assessment-summary">
        <Badge status={assessment.status} />
        <span>Deterministic score: {assessment.score?.toFixed(1) ?? 'Insufficient evidence'}</span>
        <span>{date(assessment.created_at)}</span>
      </div>
      <h3>What the evidence indicates</h3>
      <p>{assessment.explanation}</p>
      <h3>Suggested next step</h3>
      <p>{assessment.recommendation}</p>
      <Notice>
        {assessment.uncertainty} Human review is required for consequential handling decisions.
      </Notice>
      {assessment.quality_flags.length > 0 && (
        <div className="quality-flags">
          <h3>Data quality</h3>
          {assessment.quality_flags.map((flag) => (
            <span className="source simulated" key={flag}>
              {human(flag)}
            </span>
          ))}
        </div>
      )}
      <div className="ai-explanation">
        <h3>
          AI explanation <span className="source">{human(assessment.ai_status)}</span>
        </h3>
        <p className="muted">
          Job: {human(assessment.ai_job_status)} · {assessment.model || 'No model used'}
        </p>
        {ai ? (
          <>
            <p>{String(ai.risk_interpretation || '')}</p>
            <p>{String(ai.suggested_next_step || '')}</p>
            <p className="muted">{String(ai.uncertainty || '')}</p>
          </>
        ) : (
          <p>
            The deterministic assessment remains available when AI is disabled, pending, or fails
            validation.
          </p>
        )}
      </div>
      <details>
        <summary>Evidence & reproducibility</summary>
        <dl className="metadata">
          <div>
            <dt>Rules</dt>
            <dd>{assessment.rules_version}</dd>
          </div>
          <div>
            <dt>Workflow / prompt</dt>
            <dd>
              {assessment.workflow_version} / {assessment.prompt_version}
            </dd>
          </div>
          <div>
            <dt>Candidate indicator</dt>
            <dd>{human(assessment.candidate_status)}</dd>
          </div>
          <div>
            <dt>Retrieved IDs</dt>
            <dd>{assessment.retrieved_evidence_ids.join(', ') || 'None'}</dd>
          </div>
          <div>
            <dt>Cited IDs</dt>
            <dd>{assessment.cited_evidence_ids.join(', ') || 'None'}</dd>
          </div>
        </dl>
        <pre>
          {JSON.stringify(
            {
              input_references: assessment.input_references,
              features: assessment.features,
              policy_snapshot: assessment.policy_snapshot,
            },
            null,
            2,
          )}
        </pre>
      </details>
    </div>
  );
}

export function BatchDetail() {
  const { id = '' } = useParams();
  const { user } = useAuth();
  const canWrite = user?.role !== 'vendor';
  const [tab, setTab] = useState('readings');
  const [modal, setModal] = useState('');
  const [offset, setOffset] = useState(0);
  const [observationOffset, setObservationOffset] = useState(0);
  const [assessmentOffset, setAssessmentOffset] = useState(0);
  const [decisionOffset, setDecisionOffset] = useState(0);
  const [time, setTime] = useState(() => {
    const start = new Date(Date.now() - 24 * 3600000);
    return {
      start: new Date(start.getTime() - start.getTimezoneOffset() * 60000)
        .toISOString()
        .slice(0, 16),
      end: localNow(),
    };
  });
  const [range, setRange] = useState({
    start: new Date(Date.now() - 24 * 3600000).toISOString(),
    end: new Date().toISOString(),
  });
  const [rangeError, setRangeError] = useState('');
  const [metric, setMetric] = useState<'temperature_c' | 'humidity_pct' | 'gas_adc'>(
    'temperature_c',
  );
  const batch = useResource<BatchOut>(`/batches/${id}`);
  // Live view: follow the newest readings. The API lists oldest first, so a one-row probe
  // gives the total and the real query then asks for the last page. A fixed window (the old
  // behaviour) would hide every reading that arrives after the page was opened.
  const [live, setLive] = useState(true);
  const liveProbe = useList<ReadingOut>(`/batches/${id}/readings`, 0, {}, 1, live);
  const liveTotal = liveProbe.data?.total ?? 0;
  const liveReadings = useList<ReadingOut>(
    `/batches/${id}/readings`,
    Math.max(0, liveTotal - 200),
    {},
    200,
    live && liveProbe.isSuccess,
  );
  const rangeReadings = useList<ReadingOut>(`/batches/${id}/readings`, offset, range, 200, !live);
  const readings = live ? liveReadings : rangeReadings;
  const readingsQuery = live && liveProbe.isError ? liveProbe : readings;
  const observations = useList<ObservationOut>(`/batches/${id}/observations`, observationOffset);
  const assessments = useList<AssessmentOut>(`/batches/${id}/assessments`, assessmentOffset);
  const decisions = useList<DecisionOut>(`/batches/${id}/decisions`, decisionOffset);
  const [deviceModal, setDeviceModal] = useState<'' | 'assign' | 'pair'>('');
  const devices = useResource<Page<DeviceOut>>(`/devices${params({ batch_id: id, limit: 200 })}`);
  const assess = useWrite(`/batches/${id}/assessments`);
  const archive = useWrite(`/batches/${id}/archive`);
  const newest = useResource<Page<AssessmentOut>>(`/batches/${id}/assessments?limit=1`);
  function applyRange() {
    const start = new Date(time.start),
      end = new Date(time.end);
    if (
      !time.start ||
      !time.end ||
      !Number.isFinite(+start) ||
      !Number.isFinite(+end) ||
      start > end
    ) {
      setRangeError('Choose valid start and end times, with start before end.');
      return;
    }
    setRangeError('');
    setRange({ start: start.toISOString(), end: end.toISOString() });
    setOffset(0);
    setLive(false);
  }
  return (
    <>
      <Link className="text-link back-link" to="/app/batches">
        <ArrowLeft size={16} />
        All batches
      </Link>
      <QueryState query={batch}>
        {batch.data && (
          <>
            <PageHeader
              title={batch.data.identifier}
              description={`${batch.data.commodity} · ${batch.data.quantity} ${batch.data.unit} · ${batch.data.storage_location}${batch.data.archived ? ' · Archived' : ''}`}
              action={
                <>
                  <Refresh
                    refresh={() => {
                      void batch.refetch();
                      void readings.refetch();
                      void observations.refetch();
                      void assessments.refetch();
                      void newest.refetch();
                      void devices.refetch();
                      void decisions.refetch();
                    }}
                    fetching={batch.isFetching || readings.isFetching}
                  />
                  {canWrite && !batch.data.archived && (
                    <button
                      className="button primary"
                      onClick={() => assess.mutate(undefined)}
                      disabled={assess.isPending}
                    >
                      {assess.isPending ? 'Assessing…' : 'Run assessment'}
                    </button>
                  )}
                </>
              }
            />
            <div className="batch-status">
              <Badge status={batch.data.status} />
              <span className="muted">Registered {date(batch.data.created_at)}</span>
              <span className="muted">Batch ID: {batch.data.id}</span>
            </div>
            {batch.data.notes && <p>{batch.data.notes}</p>}
            {assess.error && <Notice danger>{assess.error.message}</Notice>}
            {assess.isSuccess && (
              <Notice>
                Assessment recorded. Open the Assessment tab to review its evidence and AI job
                status.
              </Notice>
            )}
            <QueryState query={devices}>
              <div className="device-chips">
                {devices.data?.items.map((d) => (
                  <span key={d.id}>
                    {d.identifier} <strong>{human(d.connection_status)}</strong>{' '}
                    <Source simulated={d.simulated} />
                  </span>
                ))}
                {!devices.data?.items.length && (
                  <Notice>No device is assigned to this batch.</Notice>
                )}
              </div>
              {canWrite && !batch.data.archived && (
                <div className="actions">
                  <button className="button secondary" onClick={() => setDeviceModal('assign')}>
                    Add a free device
                  </button>
                  <button className="button secondary" onClick={() => setDeviceModal('pair')}>
                    Pair a new ESP32
                  </button>
                </div>
              )}
              {deviceModal === 'assign' && (
                <AssignDeviceModal batch={batch.data} close={() => setDeviceModal('')} />
              )}
              {deviceModal === 'pair' && (
                <PairDeviceModal batchId={batch.data.id} close={() => setDeviceModal('')} />
              )}
            </QueryState>
            <div className="tabs" role="group" aria-label="Batch views">
              {[
                ['readings', 'Sensor history'],
                ['assessment', 'Assessment'],
                ['observations', 'Observations'],
                ['decisions', 'Decisions & metadata'],
              ].map(([key, label]) => (
                <button
                  key={key}
                  aria-pressed={tab === key}
                  className={tab === key ? 'active' : ''}
                  onClick={() => setTab(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            {tab === 'readings' && (
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Sensor history</h2>
                    <p>
                      Warm-up samples remain visible and are excluded by the backend risk engine.
                    </p>
                  </div>
                  <label>
                    Measurement
                    <select
                      value={metric}
                      onChange={(e) => setMetric(e.target.value as typeof metric)}
                    >
                      <option value="temperature_c">Temperature (°C)</option>
                      <option value="humidity_pct">Humidity (% RH)</option>
                      <option value="gas_adc">Gas response (raw ADC)</option>
                    </select>
                  </label>
                </div>
                <div className="filters time-filters">
                  <label>
                    Start (local time)
                    <input
                      type="datetime-local"
                      value={time.start}
                      onChange={(e) => setTime({ ...time, start: e.target.value })}
                    />
                  </label>
                  <label>
                    End (local time)
                    <input
                      type="datetime-local"
                      value={time.end}
                      onChange={(e) => setTime({ ...time, end: e.target.value })}
                    />
                  </label>
                  <button className="button secondary" onClick={applyRange}>
                    Apply range
                  </button>
                  {!live && (
                    <button className="button secondary" onClick={() => setLive(true)}>
                      Show latest
                    </button>
                  )}
                </div>
                <p className="muted">
                  {live
                    ? `Showing the latest ${Math.min(liveTotal, 200)} of ${liveTotal} readings. Updates every minute.`
                    : 'Showing the chosen time range. Choose "Show latest" to follow new readings.'}
                </p>
                {rangeError && <Notice danger>{rangeError}</Notice>}
                <QueryState query={readingsQuery}>
                  <Suspense fallback={<div className="loading">Loading chart…</div>}>
                    <SensorChart
                      readings={readings.data?.items || []}
                      observations={observations.data?.items || []}
                      assessments={assessments.data?.items || []}
                      metric={metric}
                    />
                  </Suspense>
                  {(observations.isError || assessments.isError) && (
                    <Notice danger>
                      Some timeline markers could not be loaded. Sensor values remain available.
                    </Notice>
                  )}
                  <details>
                    <summary>Reading values & timestamps</summary>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Source / ingestion time</th>
                            <th>Device</th>
                            <th>°C</th>
                            <th>% RH</th>
                            <th>ADC / voltage</th>
                            <th>Data source</th>
                          </tr>
                        </thead>
                        <tbody>
                          {readings.data?.items.map((r) => (
                            <tr key={r.id}>
                              <td>
                                {date(r.source_timestamp)}
                                <small>Ingested {date(r.ingested_at)}</small>
                              </td>
                              <td>{r.device_id.slice(0, 8)}</td>
                              <td>{r.temperature_c.toFixed(1)}</td>
                              <td>{r.humidity_pct.toFixed(1)}</td>
                              <td>
                                {r.gas_adc} / {r.gas_voltage_v.toFixed(2)} V
                              </td>
                              <td>
                                <Source simulated={r.simulated} />
                                {r.warming_up && <small>Warming up</small>}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                </QueryState>
                {!live && (
                  <Pagination
                    limit={200}
                    total={readings.data?.total || 0}
                    offset={offset}
                    onChange={setOffset}
                  />
                )}
              </section>
            )}
            {tab === 'assessment' && (
              <>
                <section className="panel">
                  <div className="panel-heading">
                    <h2>Latest assessment</h2>
                  </div>
                  <QueryState query={newest}>
                    {newest.data?.items[0] ? (
                      <Assessment assessment={newest.data.items[0]} />
                    ) : (
                      <Empty title="No assessment yet">
                        {canWrite
                          ? 'Run an assessment to calculate risk from available evidence.'
                          : 'An operator can request an assessment.'}
                      </Empty>
                    )}
                  </QueryState>
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <h2>Assessment history</h2>
                  </div>
                  <QueryState query={assessments} empty={!assessments.data?.items.length}>
                    {assessments.data?.items.map((a) => (
                      <details className="history-detail" key={a.id}>
                        <summary>
                          {date(a.created_at)} · {human(a.status)} ·{' '}
                          {a.score?.toFixed(1) ?? 'No score'}
                        </summary>
                        <Assessment assessment={a} />
                      </details>
                    ))}
                  </QueryState>
                  <Pagination
                    total={assessments.data?.total || 0}
                    offset={assessmentOffset}
                    onChange={setAssessmentOffset}
                  />
                </section>
              </>
            )}
            {tab === 'observations' && (
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Observation log</h2>
                    <p>
                      Human observations, retained as evidence. Historical records cannot be edited.
                    </p>
                  </div>
                  {canWrite && (
                    <button className="button primary" onClick={() => setModal('observation')}>
                      <Plus size={16} />
                      Record observation
                    </button>
                  )}
                </div>
                <QueryState query={observations} empty={!observations.data?.items.length}>
                  {observations.data?.items.map((o) => (
                    <article className="observation" key={o.id}>
                      <div>
                        <span className="source">{human(o.observation_type)}</span>
                        <span className="muted">{date(o.observed_at)}</span>
                      </div>
                      <h3>{o.condition}</h3>
                      <p>{o.notes}</p>
                      <p className="muted">
                        Firmness: {o.firmness || 'Not recorded'} · Visible mould:{' '}
                        {o.visible_mould === null
                          ? 'Not recorded'
                          : o.visible_mould
                            ? 'Observed'
                            : 'Not observed'}{' '}
                        · Weight: {o.weight_kg === null ? 'Not recorded' : `${o.weight_kg} kg`}
                      </p>
                      {o.photo_reference && <p>Photo reference: {o.photo_reference}</p>}
                      <small>
                        ID: {o.id} · Observer: {o.observer_id}
                        {o.corrects_id && ` · Corrects: ${o.corrects_id}`}
                      </small>
                    </article>
                  ))}
                </QueryState>
                <Pagination
                  total={observations.data?.total || 0}
                  offset={observationOffset}
                  onChange={setObservationOffset}
                />
              </section>
            )}
            {tab === 'decisions' && (
              <>
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Decision history</h2>
                      <p>
                        Annotations, inspections and priority overrides, with a recorded rationale.
                      </p>
                    </div>
                    {canWrite && (
                      <button className="button primary" onClick={() => setModal('decision')}>
                        Record decision
                      </button>
                    )}
                  </div>
                  <QueryState query={decisions} empty={!decisions.data?.items.length}>
                    {decisions.data?.items.map((d) => (
                      <article className="observation" key={d.id}>
                        <span className="source">{human(d.decision_type)}</span>
                        <h3>{d.rationale}</h3>
                        <p className="muted">
                          {date(d.created_at)} · Actor {d.actor_id} · Policy {d.policy_version}
                        </p>
                        {d.decision_type === 'priority_override' && (
                          <p>
                            Requested rank: {String(d.input_references.override_rank ?? 'Cleared')}
                          </p>
                        )}
                      </article>
                    ))}
                  </QueryState>
                  <Pagination
                    total={decisions.data?.total || 0}
                    offset={decisionOffset}
                    onChange={setDecisionOffset}
                  />
                </section>
                <section className="panel metadata-panel">
                  <h2>Batch metadata</h2>
                  <pre>{JSON.stringify(batch.data.attributes, null, 2)}</pre>
                  {canWrite && (
                    <div className="actions">
                      <button className="button secondary" onClick={() => setModal('edit')}>
                        Edit batch
                      </button>
                      {!batch.data.archived && (
                        <button className="button secondary" onClick={() => setModal('archive')}>
                          Archive batch
                        </button>
                      )}
                    </div>
                  )}
                </section>
              </>
            )}
            {modal === 'observation' && <ObservationForm id={id} close={() => setModal('')} />}
            {modal === 'decision' && (
              <Modal title="Record a decision" close={() => setModal('')}>
                <ResourceForm
                  path={`/batches/${id}/decisions`}
                  fields={[
                    {
                      name: 'decision_type',
                      label: 'Type',
                      required: true,
                      options: ['inspection', 'annotation', 'priority_override'].map((value) => ({
                        value,
                        label: human(value),
                      })),
                    },
                    {
                      name: 'rationale',
                      label: 'Rationale',
                      type: 'textarea',
                      required: true,
                      maxLength: 4000,
                    },
                    {
                      name: 'override_rank',
                      label: 'Requested priority rank',
                      type: 'number',
                      min: 1,
                      max: 100000,
                      hint: 'For priority overrides only. Leave blank to clear an override.',
                    },
                  ]}
                  onSuccess={() => setModal('')}
                  submit="Record decision"
                />
              </Modal>
            )}
            {modal === 'edit' && (
              <Modal title="Edit batch" close={() => setModal('')}>
                <ResourceForm
                  path={`/batches/${id}`}
                  method="PATCH"
                  fields={[
                    {
                      name: 'quantity',
                      label: 'Quantity',
                      type: 'number',
                      min: 0.001,
                      step: 'any',
                      required: true,
                      value: batch.data.quantity,
                    },
                    {
                      name: 'unit',
                      label: 'Unit',
                      required: true,
                      value: batch.data.unit,
                      maxLength: 20,
                    },
                    {
                      name: 'storage_location',
                      label: 'Storage location',
                      required: true,
                      value: batch.data.storage_location,
                      maxLength: 200,
                    },
                    {
                      name: 'notes',
                      label: 'Notes',
                      type: 'textarea',
                      value: batch.data.notes || '',
                      maxLength: 2000,
                    },
                  ]}
                  transform={(v) => ({ ...v, notes: v.notes || null })}
                  onSuccess={() => setModal('')}
                />
              </Modal>
            )}
            {modal === 'archive' && (
              <Modal title="Archive this batch?" close={() => setModal('')}>
                <p>
                  It will leave active monitoring. Existing readings, observations and assessments
                  are retained.
                </p>
                {archive.error && <Notice danger>{archive.error.message}</Notice>}
                <button
                  className="button primary"
                  disabled={archive.isPending}
                  onClick={() => archive.mutate(undefined, { onSuccess: () => setModal('') })}
                >
                  Archive batch
                </button>
              </Modal>
            )}
          </>
        )}
      </QueryState>
    </>
  );
}
