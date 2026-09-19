import { ago, isIncident } from './format'
import type { Alarm } from './types'

interface Props {
  critical: Alarm[]
  now: number
  soundOn: boolean
  onToggleSound: () => void
  onShow: () => void
}

export function CriticalBanner({ critical, now, soundOn, onToggleSound, onShow }: Props) {
  const incidents = critical.filter(isIncident).length
  const oldest = critical.reduce<string | null>(
    (min, a) => (min === null || a.event.received_at < min ? a.event.received_at : min),
    null,
  )

  return (
    <div className={critical.length ? 'banner banner-active' : 'banner'}>
      <div className="banner-text">
        {critical.length ? (
          <>
            <strong aria-live="assertive">
              {critical.length} critical alarm{critical.length === 1 ? '' : 's'} need action
            </strong>
            {incidents > 0 && (
              <span>
                {incidents} escalated incident{incidents === 1 ? '' : 's'}
              </span>
            )}
            {oldest && <span>oldest {ago(oldest, now)}</span>}
          </>
        ) : (
          <span aria-live="polite">No critical alarms waiting.</span>
        )}
      </div>
      <div className="banner-actions">
        <button type="button" onClick={onToggleSound} aria-pressed={soundOn}>
          {soundOn ? 'Sound on' : 'Enable sound'}
        </button>
        {critical.length > 0 && (
          <button type="button" onClick={onShow}>
            Show
          </button>
        )}
      </div>
    </div>
  )
}
