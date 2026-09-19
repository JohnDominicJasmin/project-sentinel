export type Severity = 'info' | 'warning' | 'critical'
export type Status = 'new' | 'acknowledged' | 'resolved'
export type Connection = 'connecting' | 'live' | 'reconnecting'

export interface AlarmEvent {
  event_id: string
  site_id: string
  zone: string
  type: string
  source: 'camera' | 'sensor'
  confidence: number | null
  timestamp: string
  snapshot_url: string | null
  metadata: Record<string, unknown>
  received_at: string
  issues: string[]
}

export interface Alarm {
  seq: number
  event: AlarmEvent
  status: Status
  severity: Severity
  severity_source: 'rules' | 'ai'
  reason: string
  updated_at: string
  acknowledged_at: string | null
  resolved_at: string | null
}

export interface FeedStats {
  stream_connected: boolean
  stream_retries: number
  received: number
  accepted: number
  repaired: number
  rejected: number
  duplicates: number
  stored: number
  dashboards: number
  resyncs: number
}

export type ServerMessage =
  | { type: 'snapshot'; seq: number; alarms: Alarm[] }
  | { type: 'alarm'; seq: number; alarm: Alarm }
  | { type: 'stats'; stats: FeedStats }
