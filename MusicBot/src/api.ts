export type ApiResult<T> = T & { success?: boolean; error?: string }

function basePath() {
  return String(window.APP_BASE ?? '').replace(/\/$/, '')
}

export function apiUrl(path: string) {
  const normalized = path.startsWith('/') ? path : `/${path}`
  return `${basePath()}${normalized}`
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<ApiResult<T>> {
  const response = await fetch(apiUrl(path), { signal })
  const data = (await response.json().catch(() => ({}))) as ApiResult<T>
  if (!response.ok || data.success === false) {
    throw new Error(data.error || `请求失败（HTTP ${response.status}）`)
  }
  return data
}

export async function postJson<T>(path: string, body: Record<string, unknown>): Promise<ApiResult<T>> {
  const response = await fetch(apiUrl(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = (await response.json().catch(() => ({}))) as ApiResult<T>
  if (!response.ok) throw new Error(data.error || `请求失败（HTTP ${response.status}）`)
  if (data.success === false) throw new Error(data.error || '操作失败')
  return data
}

export async function postAdminJson<T>(path: string, body: Record<string, unknown>, token: string): Promise<ApiResult<T>> {
  const response = await fetch(apiUrl(path), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Music-Settings-Token': token,
    },
    body: JSON.stringify(body),
  })
  const data = (await response.json().catch(() => ({}))) as ApiResult<T>
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
