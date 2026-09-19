import { useEffect, useMemo, useState } from 'react'
import { AlarmRow } from './AlarmRow'
import { StatusBar } from './StatusBar'
import { byResolvedTime, byUrgency } from './format'
import type { Alarm, Connection, FeedStats, Status } from './types'
import { useAlarmFeed } from './useAlarmFeed'

const ROW_LIMIT = 200

const TABS: { status: Status; label: string }[] = [
  { status: 'new', label: 'Needs action' },
  { status: 'acknowledged', label: 'In progress' },
  { status: 'resolved', label: 'Resolved' },
]

export default function App() {
  const { alarms, stats, connection } = useAlarmFeed()
  const [tab, setTab] = useState<Status>('new')
  const now = useNow(1000)
  const groups = useMemo(() => groupByStatus(alarms), [alarms])
  const rows = groups[tab]
  const openCritical = groups.new.filter((a) => a.severity === 'critical').length

  return (
    <div className="app">
      <StatusBar connection={connection} stats={stats} />
      <main>
        <div className="tabs" role="tablist" aria-label="Alarm queues">
          {TABS.map(({ status, label }) => (
            <button
              key={status}
              type="button"
              role="tab"
              aria-selected={tab === status}
              className={tab === status ? 'tab tab-active' : 'tab'}
              onClick={() => setTab(status)}
            >
              {label} <span className="num">{groups[status].length.toLocaleString()}</span>
              {status === 'new' && openCritical > 0 && (
                <span className="chip chip-critical">{openCritical} critical</span>
              )}
            </button>
          ))}
        </div>

        {rows.length === 0 ? (
          <EmptyState tab={tab} connection={connection} stats={stats} />
        ) : (
          <div className="table-wrap" role="tabpanel">
            <table className="alarms">
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Alarm</th>
                  <th>Site / zone</th>
                  <th className="col-optional">Source</th>
                  <th className="num col-optional">Confidence</th>
                  <th className="num">Received</th>
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, ROW_LIMIT).map((alarm) => (
                  <AlarmRow key={alarm.event.event_id} alarm={alarm} now={now} />
                ))}
              </tbody>
            </table>
            {rows.length > ROW_LIMIT && (
              <p className="table-note">
                Showing the top {ROW_LIMIT} of {rows.length.toLocaleString()}, most urgent first.
              </p>
            )}
          </div>
        )}
      </main>
    </div>
  )
}

function groupByStatus(alarms: Alarm[]): Record<Status, Alarm[]> {
  const groups: Record<Status, Alarm[]> = { new: [], acknowledged: [], resolved: [] }
  for (const alarm of alarms) groups[alarm.status].push(alarm)
  groups.new.sort(byUrgency)
  groups.acknowledged.sort(byUrgency)
  groups.resolved.sort(byResolvedTime)
  return groups
}

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])
  return now
}

function EmptyState({ tab, connection, stats }: { tab: Status; connection: Connection; stats: FeedStats | null }) {
  let title = 'Nothing needs action.'
  let detail = 'New alarms appear here the moment they arrive.'

  if (connection !== 'live') {
    title = 'Connecting to the backend.'
    detail = 'The console reconnects on its own. Check that the backend is running on port 8000.'
  } else if (tab === 'new' && stats && !stats.stream_connected) {
    detail = 'The event feed is down, so new alarms cannot arrive. The backend is retrying on its own.'
  } else if (tab === 'acknowledged') {
    title = 'Nothing in progress.'
    detail = 'Acknowledged alarms wait here until they are resolved.'
  } else if (tab === 'resolved') {
    title = 'No resolved alarms yet.'
    detail = 'Resolved alarms are kept here for reference.'
  }

  return (
    <div className="empty" role="status">
      <p className="empty-title">{title}</p>
      <p className="muted">{detail}</p>
    </div>
  )
}
