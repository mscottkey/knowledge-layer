import type { Backend, ContextResult, QueueItem } from './types'

export const KEY_STORAGE = 'kl-api-key'

export function getStoredKey(): string {
  try {
    return window.sessionStorage.getItem(KEY_STORAGE) ?? ''
  } catch {
    return ''
  }
}

export function storeKey(key: string) {
  try {
    window.sessionStorage.setItem(KEY_STORAGE, key)
  } catch {
    // ignore: the key just will not survive a reload
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export function createLiveBackend(baseUrl: string): Backend {
  async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
    const key = getStoredKey()
    if (!key) throw new ApiError(401, 'Enter an API key with the review scope.')
    const response = await fetch(`${baseUrl}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', 'X-API-Key': key, ...init.headers },
    })
    if (!response.ok) {
      let detail = response.statusText
      try {
        detail = (await response.json()).detail ?? detail
      } catch {
        // keep the status text
      }
      throw new ApiError(response.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
    }
    return (await response.json()) as T
  }

  const post = (path: string, body: object) => call<unknown>(path, { method: 'POST', body: JSON.stringify(body) })

  return {
    mode: 'live',
    async queue() {
      return (await call<{ items: QueueItem[] }>('/review/queue')).items
    },
    async approve(id, note) {
      await post(`/review/${id}/approve`, { note })
    },
    async reject(id, note) {
      await post(`/review/${id}/reject`, { note })
    },
    async edit(id, body, note) {
      await post(`/review/${id}/edit`, { edited_body: body, note })
    },
    async context(query) {
      const params = new URLSearchParams({ query, limit: '5' })
      return (await call<{ results: ContextResult[] }>(`/context?${params}`)).results
    },
  }
}
