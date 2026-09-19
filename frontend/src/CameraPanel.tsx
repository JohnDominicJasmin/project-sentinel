import { useEffect, useState } from 'react'
import type { CameraStats } from './types'

const FRAME_REFRESH_MS = 500

export function CameraPanel({ camera }: { camera: CameraStats }) {
  const [tick, setTick] = useState(0)
  const [hasFrame, setHasFrame] = useState(false)

  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), FRAME_REFRESH_MS)
    return () => window.clearInterval(id)
  }, [])

  const streaming = camera.status === 'streaming'
  const ms = (value: number | null | undefined) => (value == null ? 'n/a' : `${Math.round(value)} ms`)

  return (
    <section className="camera" aria-label="Camera feed">
      <div className="camera-feed">
        <img
          src={`/api/camera/frame?t=${tick}`}
          alt={`Live detections from ${camera.camera_id ?? 'camera'}`}
          onLoad={() => setHasFrame(true)}
          onError={() => setHasFrame(false)}
          style={{ visibility: hasFrame ? 'visible' : 'hidden' }}
        />
      </div>
      <div>
        <p className="camera-title">
          {camera.camera_id ?? 'Camera'}{' '}
          <span className="muted">
            {camera.site_id} / {camera.zone} · {camera.source}
          </span>
        </p>
        <dl className="health">
          <div className="health-item">
            <dt>Status</dt>
            <dd className={streaming ? 'state state-ok' : 'state state-bad'}>{camera.status}</dd>
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
    </section>
  )
}
