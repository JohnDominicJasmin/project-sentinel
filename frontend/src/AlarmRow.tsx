import { useState } from 'react'
import { changeStatus, type StatusAction } from './api'
import { SEVERITY_LABEL, VERDICT_LABEL, ago, alarmTitle, isIncident, percent, typeLabel } from './format'
import type { Alarm } from './types'

const FRESH_MS = 3000

export function AlarmRow({ alarm, now }: { alarm: Alarm; now: number }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const e = alarm.event
  const ai = alarm.ai
  const fresh = now - Date.parse(e.received_at) < FRESH_MS
  const incident = isIncident(alarm)

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
    <tr className={`row sev-${alarm.severity}${fresh ? ' fresh' : ''}${incident ? ' incident' : ''}`}>
      <td>
        <span className={`chip chip-${alarm.severity}`}>{SEVERITY_LABEL[alarm.severity]}</span>
      </td>
      <td className="alarm-cell">
        {e.snapshot_url && (
          <a className="snapshot" href={e.snapshot_url} target="_blank" rel="noreferrer">
            <img src={e.snapshot_url} alt={`Camera snapshot for ${typeLabel(e.type)}`} loading="lazy" />
          </a>
        )}
        <div className="alarm-type">
          {alarmTitle(alarm)}
          {ai && <span className={`verdict verdict-${ai.verdict}`}>{VERDICT_LABEL[ai.verdict]}</span>}
        </div>
        {ai ? (
          <>
            <div>{ai.summary}</div>
            <div className="alarm-action">Action: {ai.action}</div>
          </>
        ) : (
          <div className="alarm-reason">{alarm.reason}</div>
        )}
        {incident && <IncidentDetail alarm={alarm} />}
        {alarm.incident_id && !incident && <div className="triage-note">Part of an escalated incident</div>}
        <TriageNote alarm={alarm} />
        {e.issues.length > 0 && <div className="alarm-issues">Data repaired: {e.issues.join(', ')}</div>}
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
      <td className="col-optional">{SOURCE_LABEL[e.source]}</td>
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

const SOURCE_LABEL = { camera: 'Camera', sensor: 'Sensor', system: 'Correlation' }

function IncidentDetail({ alarm }: { alarm: Alarm }) {
  const meta = alarm.event.metadata
  const types = (meta.alarm_types as string[] | undefined) ?? []
  const zones = (meta.zones as string[] | undefined) ?? []
  return (
    <div className="incident-detail">
      {String(meta.count ?? '')} linked alarms: {types.join(', ')}. Zones: {zones.join(', ')}. Acknowledging or resolving the
      incident applies to all of them.
    </div>
  )
}

function TriageNote({ alarm }: { alarm: Alarm }) {
  if (alarm.triage_status === 'pending') {
    return <div className="triage-note">AI triage pending</div>
  }
  if (alarm.triage_note) {
    return <div className="triage-note">{alarm.triage_note}</div>
  }
  return null
}
