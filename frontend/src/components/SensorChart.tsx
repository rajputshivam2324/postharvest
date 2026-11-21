import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { AssessmentOut, ObservationOut, ReadingOut } from '../api/types';
import { Empty } from './ui';

const colors = ['#28644c', '#b85432', '#416c9d', '#876195', '#7e7518'];
export default function SensorChart({
  readings,
  observations,
  assessments,
  metric,
}: {
  readings: ReadingOut[];
  observations: ObservationOut[];
  assessments: AssessmentOut[];
  metric: 'temperature_c' | 'humidity_pct' | 'gas_adc';
}) {
  if (!readings.length)
    return (
      <Empty title="No readings in this range">
        Choose another time range or check the device.
      </Empty>
    );
  const devices = [...new Set(readings.map((reading) => reading.device_id))];
  const points = new Map<number, Record<string, number>>();
  for (const reading of readings) {
    const time = Date.parse(reading.source_timestamp);
    const point = points.get(time) || { time };
    point[reading.device_id] = reading[metric];
    points.set(time, point);
  }
  const data = [...points.values()].sort((a, b) => a.time - b.time);
  const min = data[0].time;
  const max = data[data.length - 1].time;
  const unit = metric === 'temperature_c' ? '°C' : metric === 'humidity_pct' ? '% RH' : 'ADC';
  const events = [
    ...observations.map((o) => ({
      id: o.id,
      time: Date.parse(o.observed_at),
      label: 'Observation',
      color: '#876195',
    })),
    ...assessments.map((a) => ({
      id: a.id,
      time: Date.parse(a.created_at),
      label: 'Assessment',
      color: '#b85432',
    })),
  ].filter((e) => e.time >= min && e.time <= max);
  return (
    <>
      <div
        className="chart"
        role="img"
        aria-label={`${metric.replaceAll('_', ' ')} history. Values and timestamps are available in the reading table below.`}
      >
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={data} margin={{ top: 20, right: 24, left: 0, bottom: 8 }}>
            <CartesianGrid vertical={false} stroke="#e1e6dd" />
            <XAxis
              dataKey="time"
              type="number"
              scale="time"
              domain={min === max ? [min - 60000, max + 60000] : [min, max]}
              tickFormatter={(value) =>
                new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
              }
              minTickGap={45}
              tick={{ fill: '#596458', fontSize: 12 }}
            />
            <YAxis
              unit={` ${unit}`}
              width={70}
              domain={['auto', 'auto']}
              tick={{ fill: '#596458', fontSize: 12 }}
            />
            <Tooltip
              labelFormatter={(value) => new Date(Number(value)).toLocaleString()}
              formatter={(value, name) => [`${Number(value).toFixed(1)} ${unit}`, String(name)]}
            />
            <Legend />
            {devices.map((id, i) => (
              <Line
                key={id}
                dataKey={id}
                name={`Device ${id.slice(0, 8)}`}
                type="linear"
                stroke={colors[i % colors.length]}
                strokeDasharray={i > 0 ? `${i + 2} 3` : undefined}
                strokeWidth={2}
                dot={data.length === 1}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
            {events.slice(0, 20).map((e) => (
              <ReferenceLine
                key={e.id}
                x={e.time}
                stroke={e.color}
                strokeDasharray="3 3"
                label={{ value: e.label, position: 'insideTopRight', fill: e.color, fontSize: 10 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="panel-footnote">
        Chart covers this reading page only. Dashed markers show observations and assessments within
        its time span (up to 20). Device series are separate. Gas values are raw ADC counts,
        uncalibrated.
      </p>
    </>
  );
}
