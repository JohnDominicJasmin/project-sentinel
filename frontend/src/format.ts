import type { Alarm, Severity } from './types'

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

export function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type.replaceAll('_', ' ')
}

export function percent(confidence: number | null): string {
  return confidence == null ? 'n/a' : `${Math.round(confidence * 100)}%`
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
    b.event.received_at.localeCompare(a.event.received_at)
  )
}

export function byResolvedTime(a: Alarm, b: Alarm): number {
  return (b.resolved_at ?? '').localeCompare(a.resolved_at ?? '')
}
