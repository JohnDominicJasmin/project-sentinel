import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Alarm } from './types'

const MIN_GAP_BETWEEN_TONES_MS = 2000
const DEFAULT_TITLE = 'Sentinel operator console'

export function useCriticalAlerts(alarms: Alarm[]) {
  const critical = useMemo(
    () => alarms.filter((a) => a.status === 'new' && a.severity === 'critical'),
    [alarms],
  )
  const [soundOn, setSoundOn] = useState(false)
  const audio = useRef<AudioContext | null>(null)
  const known = useRef<Set<string> | null>(null)
  const lastTone = useRef(0)

  useEffect(() => {
    document.title = critical.length ? `(${critical.length}) CRITICAL · Sentinel` : DEFAULT_TITLE
  }, [critical.length])

  useEffect(() => {
    const ids = new Set(critical.map((a) => a.event.event_id))
    if (known.current === null) {
      if (alarms.length) known.current = ids
      return
    }
    const arrived = [...ids].some((id) => !known.current!.has(id))
    for (const id of ids) known.current.add(id)
    if (!arrived || !soundOn || !audio.current) return
    const now = Date.now()
    if (now - lastTone.current < MIN_GAP_BETWEEN_TONES_MS) return
    lastTone.current = now
    playTone(audio.current)
  }, [critical, alarms.length, soundOn])

  const toggleSound = useCallback(() => {
    if (!audio.current) audio.current = new AudioContext()
    void audio.current.resume()
    setSoundOn((on) => {
      if (!on && audio.current) playTone(audio.current)
      return !on
    })
  }, [])

  return { critical, soundOn, toggleSound }
}

function playTone(ctx: AudioContext) {
  const start = ctx.currentTime
  ;[880, 660].forEach((frequency, i) => {
    const at = start + i * 0.18
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.frequency.value = frequency
    gain.gain.setValueAtTime(0.0001, at)
    gain.gain.exponentialRampToValueAtTime(0.25, at + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.16)
    osc.connect(gain).connect(ctx.destination)
    osc.start(at)
    osc.stop(at + 0.17)
  })
}
