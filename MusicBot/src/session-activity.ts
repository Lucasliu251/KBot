// Foreground navigation and real interaction extend the shared idle session.
// Music state polling does not call this endpoint.
let lastActivity = 0

export function startSessionActivity() {
  const activity = async () => {
    if (document.visibilityState !== 'visible' || !window.TRASHBOX_CSRF_TOKEN || Date.now() - lastActivity < 60_000) return
    lastActivity = Date.now()
    const base = String(window.APP_BASE || '').replace(/\/$/, '')
    await fetch(`${base}/api/auth/activity`, {
      method: 'POST',
      headers: { 'X-CSRF-Token': window.TRASHBOX_CSRF_TOKEN },
      credentials: 'same-origin',
    }).catch(() => {})
  }
  window.addEventListener('pointerdown', activity, { passive: true })
  window.addEventListener('keydown', activity, { passive: true })
  window.addEventListener('popstate', activity)
  window.addEventListener('music-session-ready', activity)
}
