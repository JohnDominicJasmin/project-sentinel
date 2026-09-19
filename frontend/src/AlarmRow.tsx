import { useState } from 'react'
import { changeStatus, type StatusAction } from './api'
import { SEVERITY_LABEL, ago, percent, typeLabel } from './format'
import type { Alarm } from './types'

const FRESH_MS = 3000

export function AlarmRow({ alarm, now }: { alarm: Alarm; now: number }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const e = alarm.event
  const fresh = now - Date.parse(e.received_at) < FRESH_MS

  const act = async (action: StatusAction) => {
    setBusy(true)
    setError(null)
    try {
      await changeStatus(e.event_id, action)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <tr className={`row sev-${alarm.severity}${fresh ? ' fresh' : ''}`}>
      <td>
        <span className={`chip chip-${alarm.severity}`}>{SEVERITY_LABEL[alarm.severity]}</span>
      </td>
      <td>
        <div className="alarm-type">{typeLabel(e.type)}</div>
        <div className="alarm-reason">{alarm.reason}</div>
        {e.issues.length > 0 && (
          <div className="alarm-issues">Data repaired: {e.issues.join(', ')}</div>
        )}
        {error && (
          <div className="alarm-error" role="alert">
            {error}
          </div>
        )}
      </td>
      <td>
        <div>{e.site_id}</div>
        <div className="muted">{e.zone}</div>
      </td>
      <td className="col-optional">{e.source === 'camera' ? 'Camera' : 'Sensor'}</td>
      <td className="num col-optional">{percent(e.confidence)}</td>
      <td className="num" title={new Date(e.received_at).toLocaleString()}>
        {ago(e.received_at, now)}
      </td>
      <td className="actions">
        {alarm.status === 'new' && (
          <button type="button" onClick={() => act('acknowledge')} disabled={busy}>
            Acknowledge
          </button>
        )}
        {alarm.status !== 'resolved' && (
          <button type="button" onClick={() => act('resolve')} disabled={busy}>
            Resolve
          </button>
        )}
        {alarm.status === 'resolved' && alarm.resolved_at && (
          <span className="muted">Resolved {ago(alarm.resolved_at, now)}</span>
        )}
      </td>
    </tr>
  )
}
