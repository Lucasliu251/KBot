import { startSessionActivity } from './session-activity'

export type ApiResult<T> = T & { success?: boolean; error?: string; login_required?: boolean; login_url?: string; identity_required?: boolean; account_url?: string }

function basePath() {
  return String(window.APP_BASE ?? '').replace(/\/$/, '')
}

export function apiUrl(path: string) {
  const normalized = path.startsWith('/') ? path : `/${path}`
  return `${basePath()}${normalized}`
}

function loginIfRequired(response: Response, data: ApiResult<unknown>) {
  if (response.status === 401 && data.login_required) {
    const current = window.location.pathname.startsWith('/Music') ? `${window.location.pathname}${window.location.search}` : '/Music/'
    const destination = new URL(data.login_url || '/login', window.location.origin)
    destination.searchParams.set('return_to', current)
    window.location.assign(destination.href)
  }
  if (response.status === 403 && data.identity_required && data.account_url) {
    window.location.assign(`/account?return_to=${encodeURIComponent(window.location.pathname + window.location.search)}`)
  }
}

async function csrfHeaders() {
  if (!window.TRASHBOX_CSRF_TOKEN) {
    const status = await getJson<{ csrf_token?: string }>('/api/auth/kook/status')
    window.TRASHBOX_CSRF_TOKEN = status.csrf_token || ''
  }
  return { 'Content-Type': 'application/json', 'X-CSRF-Token': window.TRASHBOX_CSRF_TOKEN || '' }
}

startSessionActivity()

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<ApiResult<T>> {
  const response = await fetch(apiUrl(path), { signal })
  const data = (await response.json().catch(() => ({}))) as ApiResult<T>
  loginIfRequired(response, data)
  if (!response.ok || data.success === false) {
    throw new Error(data.error || `请求失败（HTTP ${response.status}）`)
  }
  return data
}

export async function postJson<T>(path: string, body: Record<string, unknown>): Promise<ApiResult<T>> {
  const response = await fetch(apiUrl(path), {
    method: 'POST',
    headers: await csrfHeaders(),
    body: JSON.stringify(body),
  })
  const data = (await response.json().catch(() => ({}))) as ApiResult<T>
  loginIfRequired(response, data)
  if (!response.ok) throw new Error(data.error || `请求失败（HTTP ${response.status}）`)
  if (data.success === false) throw new Error(data.error || '操作失败')
  return data
}

export async function getAdminJson<T>(path: string, token: string, signal?: AbortSignal): Promise<ApiResult<T>> {
  const response = await fetch(apiUrl(path), { signal, headers: { 'X-Music-Settings-Token': token } })
  const data = (await response.json().catch(() => ({}))) as ApiResult<T>
  loginIfRequired(response, data)
  if (!response.ok || data.success === false) {
    throw new Error(data.error || `请求失败（HTTP ${response.status}）`)
  }
  return data
}

export async function postAdminJson<T>(path: string, body: Record<string, unknown>, token: string): Promise<ApiResult<T>> {
  const response = await fetch(apiUrl(path), {
    method: 'POST',
    headers: {
      ...await csrfHeaders(),
      'X-Music-Settings-Token': token,
    },
    body: JSON.stringify(body),
  })
  const data = (await response.json().catch(() => ({}))) as ApiResult<T>
  loginIfRequired(response, data)
  if (!response.ok || data.success === false) {
    throw new Error(data.error || `请求失败（HTTP ${response.status}）`)
  }
  return data
}

export function assetUrl(filename: string) {
  const configured = window.MUSIC_CONSOLE_ASSET_BASE?.replace(/\/$/, '')
  if (configured) return `${configured}/${filename}`
  return `${import.meta.env.BASE_URL}assets/${filename}`
}
