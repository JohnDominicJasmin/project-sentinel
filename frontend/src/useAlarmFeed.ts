import { useEffect, useState } from 'react'
import type { Alarm, Connection, FeedStats, ServerMessage } from './types'

const MAX_RESOLVED_KEPT = 500
const MAX_RETRY_MS = 5000
const FLUSH_MS = 50

export function useAlarmFeed() {
  const [alarms, setAlarms] = useState<Alarm[]>([])
  const [stats, setStats] = useState<FeedStats | null>(null)
  const [connection, setConnection] = useState<Connection>('connecting')

  useEffect(() => {
    const byId = new Map<string, Alarm>()
    let socket: WebSocket | null = null
    let lastSeq = 0
    let resyncing = false
    let flushTimer: number | undefined
    let attempt = 0
    let retryTimer: number | undefined
    let stopped = false

    const flush = () => {
      flushTimer = undefined
      pruneResolved(byId)
      setAlarms(Array.from(byId.values()))
    }

    const scheduleFlush = () => {
      if (flushTimer === undefined) flushTimer = window.setTimeout(flush, FLUSH_MS)
    }

    const handle = (msg: ServerMessage) => {
      if (msg.type === 'stats') {
        setStats(msg.stats)
        return
      }
      if (msg.type === 'snapshot') {
        byId.clear()
        for (const alarm of msg.alarms) byId.set(alarm.event.event_id, alarm)
        lastSeq = msg.seq
        resyncing = false
        scheduleFlush()
        return
      }
      if (resyncing || msg.seq <= lastSeq) return
      if (msg.seq !== lastSeq + 1) {
        resyncing = true
        socket?.close()
        return
      }
      lastSeq = msg.seq
      byId.set(msg.alarm.event.event_id, msg.alarm)
      scheduleFlush()
    }

    const connect = () => {
      const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${scheme}://${location.host}/ws`)
      socket = ws
      ws.onopen = () => {
        attempt = 0
        setConnection('live')
      }
      ws.onmessage = (e) => handle(JSON.parse(e.data) as ServerMessage)
      ws.onclose = () => {
        if (stopped || socket !== ws) return
        setConnection('reconnecting')
        attempt += 1
        retryTimer = window.setTimeout(connect, Math.min(MAX_RETRY_MS, 250 * 2 ** attempt))
      }
    }

    connect()
    return () => {
      stopped = true
      window.clearTimeout(retryTimer)
      window.clearTimeout(flushTimer)
      socket?.close()
    }
  }, [])

  return { alarms, stats, connection }
}

function pruneResolved(byId: Map<string, Alarm>) {
  const resolved = [...byId.values()].filter((a) => a.status === 'resolved')
  if (resolved.length <= MAX_RESOLVED_KEPT) return
  resolved.sort((a, b) => (a.resolved_at ?? '').localeCompare(b.resolved_at ?? ''))
  for (const alarm of resolved.slice(0, resolved.length - MAX_RESOLVED_KEPT)) {
    byId.delete(alarm.event.event_id)
  }
}
