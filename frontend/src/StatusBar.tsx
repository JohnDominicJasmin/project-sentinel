import type { Connection, FeedStats } from './types'

interface Props {
  connection: Connection
  stats: FeedStats | null
}

export function StatusBar({ connection, stats }: Props) {
  const live = connection === 'live'
  const feedKnown = live && stats !== null
  const feedUp = feedKnown && stats.stream_connected

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
        <Indicator
          label="Event feed"
          value={!feedKnown ? 'Unknown' : feedUp ? 'Up' : 'Down, retrying'}
          ok={feedUp}
        />
        <Count label="Received" value={stats?.received} />
        <Count label="Repaired" value={stats?.repaired} />
        <Count label="Rejected" value={stats?.rejected} />
        <Count label="Duplicates" value={stats?.duplicates} />
      </dl>
    </header>
  )
}

function Indicator({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <div className="health-item">
      <dt>{label}</dt>
      <dd className={ok ? 'state state-ok' : 'state state-bad'}>{value}</dd>
    </div>
  )
}

function Count({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="health-item">
      <dt>{label}</dt>
      <dd className="num">{value == null ? 'n/a' : value.toLocaleString()}</dd>
    </div>
  )
}
