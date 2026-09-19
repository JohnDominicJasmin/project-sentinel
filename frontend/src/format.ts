import type { Alarm, Severity, Verdict } from './types'

const TYPE_LABELS: Record<string, string> = {
  motion_detected: 'Motion',
  perimeter_breach: 'Perimeter breach',
  door_forced: 'Door forced',
  glass_break: 'Glass break',
  smoke_detected: 'Smoke detected',
  fire_alarm: 'Fire alarm',
  object_detected: 'Object detected',
  loitering: 'Loitering',
  camera_offline: 'Camera offline',
  sensor_fault: 'Sensor fault',
  panic_button: 'Panic button',
}

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: 'Critical',
  warning: 'Warning',
  info: 'Info',
}

const SEVERITY_RANK: Record<Severity, number> = { critical: 0, warning: 1, info: 2 }

export const VERDICT_LABEL: Record<Verdict, string> = {
  likely_real: 'Likely real',
  uncertain: 'Uncertain',
  probable_false_positive: 'Probable false alarm',
}

const VERDICT_RANK: Record<Verdict, number> = { likely_real: 0, uncertain: 1, probable_false_positive: 2 }

function verdictRank(alarm: Alarm): number {
  return alarm.ai ? VERDICT_RANK[alarm.ai.verdict] : 1
}

export function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type.replaceAll('_', ' ')
}

export function percent(confidence: number | null): string {
  return confidence == null ? 'n/a' : `${Math.round(confidence * 100)}%`
}

export function formatMs(ms: number | null): string {
  return ms == null ? 'n/a' : `${(ms / 1000).toFixed(1)} s`
}

export function ago(iso: string, now: number): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m ago`
}

export function byUrgency(a: Alarm, b: Alarm): number {
  return (
    SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] ||
    verdictRank(a) - verdictRank(b) ||
    b.event.received_at.localeCompare(a.event.received_at)
  )
}

export function byResolvedTime(a: Alarm, b: Alarm): number {
  return (b.resolved_at ?? '').localeCompare(a.resolved_at ?? '')
}
