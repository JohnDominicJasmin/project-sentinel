export type StatusAction = 'acknowledge' | 'resolve'

export async function changeStatus(eventId: string, action: StatusAction): Promise<void> {
  const res = await fetch(`/api/alarms/${encodeURIComponent(eventId)}/${action}`, { method: 'POST' })
  if (res.ok || res.status === 409) return
  throw new Error(res.status === 404 ? 'This alarm no longer exists.' : `Could not ${action} (HTTP ${res.status}).`)
}
