export type Severity = 'info' | 'warning' | 'critical'
export type Status = 'new' | 'acknowledged' | 'resolved'
export type Connection = 'connecting' | 'live' | 'reconnecting'
export type Verdict = 'likely_real' | 'probable_false_positive' | 'uncertain'
export type TriageStatus = 'pending' | 'ai' | 'rules'

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

export interface AiTriage {
  severity: Severity
  verdict: Verdict
  summary: string
  action: string
  model: string
  latency_ms: number
}

export interface Alarm {
  seq: number
  event: AlarmEvent
  status: Status
  severity: Severity
  severity_source: 'rules' | 'ai'
  reason: string
  triage_status: TriageStatus
  triage_note: string | null
  ai: AiTriage | null
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
  ai: AiStats
  camera: CameraStats | null
}

export interface CameraStats {
  status: string
  camera_id?: string
  site_id?: string
  zone?: string
  source?: string
  source_fps?: number
  target_fps?: number
  frames_read?: number
  frames_processed?: number
  frames_skipped?: number
  reconnects?: number
  inference_p50_ms?: number | null
  inference_p95_ms?: number | null
  active_tracks?: number
  events_sent?: number
  events_suppressed?: number
  events_dropped?: number
  events_received: number
  worker_restarts: number
}

export interface AiStats {
  state: 'on' | 'off' | 'paused' | 'budget_reached'
  model: string | null
  chaos: string
  pause_reason: string | null
  queue_depth: number
  calls: number
  failed_calls: number
  ai_triaged: number
  fallbacks: number
  input_tokens: number
  output_tokens: number
  spent_usd: number
  budget_usd: number
  latency_p50_ms: number | null
  latency_p95_ms: number | null
}

export type ServerMessage =
  | { type: 'snapshot'; seq: number; alarms: Alarm[] }
  | { type: 'alarm'; seq: number; alarm: Alarm }
  | { type: 'stats'; stats: FeedStats }
