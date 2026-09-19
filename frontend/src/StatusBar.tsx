import type { ReactNode } from 'react'
import { formatMs } from './format'
import type { AiStats, Connection, FeedStats } from './types'

interface Props {
  connection: Connection
  stats: FeedStats | null
}

export function StatusBar({ connection, stats }: Props) {
  const live = connection === 'live'
  const known = live && stats !== null
  const feedUp = known && stats.stream_connected

  return (
    <header className="topbar">
      <div className="brand">
        Sentinel <span className="muted">operator console</span>
      </div>
      <dl className="health">
        <Indicator
          label="Console"
          value={live ? 'Live' : connection === 'reconnecting' ? 'Reconnecting' : 'Connecting'}
          ok={live}
        />
        <Indicator label="Event feed" value={!known ? 'Unknown' : feedUp ? 'Up' : 'Down, retrying'} ok={feedUp} />
        {known && <AiIndicator ai={stats.ai} />}
        <Count label="Received" value={stats?.received} />
        <Count label="Repaired" value={stats?.repaired} />
        <Count label="Rejected" value={stats?.rejected} />
        <Count label="Duplicates" value={stats?.duplicates} />
        {known && stats.ai.state !== 'off' && (
          <>
            <Item label="AI latency p50 / p95">
              {formatMs(stats.ai.latency_p50_ms)} / {formatMs(stats.ai.latency_p95_ms)}
            </Item>
            <Item label="AI spend">
              ${stats.ai.spent_usd.toFixed(4)} of ${stats.ai.budget_usd.toFixed(2)}
            </Item>
          </>
        )}
      </dl>
    </header>
  )
}

function AiIndicator({ ai }: { ai: AiStats }) {
  const text = {
    on: ai.model ?? 'On',
    off: 'Off, rules only',
    paused: ai.pause_reason ?? 'Paused',
    budget_reached: 'Budget reached, rules only',
  }[ai.state]
  const chaos = ai.chaos !== 'off' ? ` (chaos: ${ai.chaos})` : ''
  return <Indicator label="AI triage" value={text + chaos} ok={ai.state === 'on'} neutral={ai.state === 'off'} />
}

function Indicator({ label, value, ok, neutral = false }: { label: string; value: string; ok: boolean; neutral?: boolean }) {
  const tone = neutral ? 'state state-neutral' : ok ? 'state state-ok' : 'state state-bad'
  return (
    <div className="health-item">
      <dt>{label}</dt>
      <dd className={tone}>{value}</dd>
    </div>
  )
}

function Count({ label, value }: { label: string; value: number | undefined }) {
  return <Item label={label}>{value == null ? 'n/a' : value.toLocaleString()}</Item>
}

function Item({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="health-item">
      <dt>{label}</dt>
      <dd className="num">{children}</dd>
    </div>
  )
}
