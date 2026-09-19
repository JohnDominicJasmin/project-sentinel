import { useCallback, useEffect, useRef, useState } from 'react'
import type { CameraStats } from './types'

const FRAME_REFRESH_MS = 500

interface Feed {
  id: string
  name: string
  zone: string
}

export function CameraPanel({ camera }: { camera: CameraStats }) {
  const [tick, setTick] = useState(0)
  const [hasFrame, setHasFrame] = useState(false)
  const [feeds, setFeeds] = useState<Feed[]>([])
  const [switchingTo, setSwitchingTo] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), FRAME_REFRESH_MS)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    fetch('/api/camera/feeds')
      .then((res) => res.json())
      .then((data: { feeds: Feed[] }) => setFeeds(data.feeds))
      .catch(() => setFeeds([]))
  }, [])

  useEffect(() => {
    if (switchingTo && camera.feed_id === switchingTo && camera.status === 'streaming') setSwitchingTo(null)
  }, [camera.feed_id, camera.status, switchingTo])

  const switchFeed = useCallback(async (feedId: string) => {
    setError(null)
    setSwitchingTo(feedId)
    setHasFrame(false)
    try {
      const res = await fetch(`/api/camera/feeds/${encodeURIComponent(feedId)}`, { method: 'POST' })
      if (!res.ok) throw new Error(`Could not switch feed (HTTP ${res.status}).`)
    } catch (err) {
      setSwitchingTo(null)
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  const streaming = camera.status === 'streaming' && !switchingTo
  const status = switchingTo ? 'switching' : camera.status
  const frameUrl = `/api/camera/frame?t=${tick}`
  const ms = (value: number | null | undefined) => (value == null ? 'n/a' : `${Math.round(value)} ms`)
  const title = `${camera.feed_name ?? 'Camera'} (${camera.camera_id ?? 'camera'})`

  return (
    <section className="camera" aria-label="Camera feed">
      <div className="camera-feed">
        <img
          src={frameUrl}
          alt={`Live detections from ${title}`}
          onLoad={() => setHasFrame(true)}
          onError={() => setHasFrame(false)}
          style={{ visibility: hasFrame ? 'visible' : 'hidden' }}
        />
        <button type="button" className="camera-enlarge" onClick={() => dialog.current?.showModal()}>
          Enlarge
        </button>
      </div>
      <div className="camera-info">
        <div className="camera-header">
          <p className="camera-title">
            {title}{' '}
            <span className="muted">
              {camera.site_id} / {camera.zone}
            </span>
          </p>
          {feeds.length > 1 && (
            <label className="camera-select">
              <span className="muted">Feed</span>
              <select
                value={switchingTo ?? camera.feed_id ?? ''}
                disabled={switchingTo !== null}
                onChange={(e) => void switchFeed(e.target.value)}
              >
                {feeds.map((feed) => (
                  <option key={feed.id} value={feed.id}>
                    {feed.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        {error && (
          <p className="alarm-error" role="alert">
            {error}
          </p>
        )}
        <dl className="health">
          <div className="health-item">
            <dt>Status</dt>
            <dd className={streaming ? 'state state-ok' : 'state state-bad'}>{status}</dd>
          </div>
          <div className="health-item">
            <dt>Analysing</dt>
            <dd className="num">
              {camera.target_fps ?? 'n/a'} fps of {camera.source_fps ?? 'n/a'}
            </dd>
          </div>
          <div className="health-item">
            <dt>Detection p50 / p95</dt>
            <dd className="num">
              {ms(camera.inference_p50_ms)} / {ms(camera.inference_p95_ms)}
            </dd>
          </div>
          <div className="health-item">
            <dt>Objects in view</dt>
            <dd className="num">{camera.active_tracks ?? 0}</dd>
          </div>
          <div className="health-item">
            <dt>Alarms raised</dt>
            <dd className="num">{camera.events_received}</dd>
          </div>
          <div className="health-item">
            <dt>Repeats suppressed</dt>
            <dd className="num">{camera.events_suppressed ?? 0}</dd>
          </div>
        </dl>
      </div>

      <dialog
        ref={dialog}
        className="camera-dialog"
        aria-label={`${title}, enlarged`}
        onClick={(e) => e.target === dialog.current && dialog.current?.close()}
        onKeyDown={(e) => e.key === 'Escape' && dialog.current?.close()}
      >
        <div className="camera-dialog-header">
          <p className="camera-title">
            {title}{' '}
            <span className="muted">
              {camera.site_id} / {camera.zone} · {status}
            </span>
          </p>
          <button type="button" onClick={() => dialog.current?.close()} autoFocus>
            Close
          </button>
        </div>
        <img src={frameUrl} alt={`Enlarged live detections from ${title}`} />
      </dialog>
    </section>
  )
}
