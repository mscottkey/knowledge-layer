import { seedPublished, seedQueue } from './demo-data'
import type { Backend, ContextResult, QueueItem } from './types'

// Runs the review lifecycle in the browser on sample data, with the same rules as the API:
// a replacement stays pending until approved, the old version retires only when the new one is
// published, an edit publishes as a new version, and rejected articles go back to draft.

interface State {
  published: ContextResult[]
  queue: QueueItem[]
  seq: number
}

const KEY = 'kl-demo-state-v1'

function fresh(): State {
  return { published: seedPublished(), queue: seedQueue(), seq: 0 }
}

function load(): State {
  try {
    const raw = typeof window !== 'undefined' ? window.sessionStorage.getItem(KEY) : null
    if (raw) return JSON.parse(raw) as State
  } catch {
    // fall through to a fresh state
  }
  return fresh()
}

function save(state: State) {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(state))
  } catch {
    // private windows can refuse storage; the demo still works for this page view
  }
}

const STOP = new Set('the and for can how what are you your with from that this does not our was when why who has have its into about'.split(' '))
const tokens = (text: string) => new Set((text.toLowerCase().match(/[a-z0-9]{3,}/g) ?? []).filter((w) => !STOP.has(w)))

// Stand-in for the vector search: rank published articles by how many query words they share.
function rank(query: string, articles: ContextResult[]): ContextResult[] {
  const q = tokens(query)
  return articles
    .map((a) => {
      const words = tokens(`${a.title} ${a.body}`)
      let hits = 0
      q.forEach((w) => words.has(w) && hits++)
      return { a, hits }
    })
    .filter((r) => r.hits > 0)
    .sort((x, y) => y.hits - x.hits)
    .map((r) => r.a)
}

export function createDemoBackend(): Backend {
  let state = load()
  const commit = () => save(state)

  const take = (id: string) => {
    const item = state.queue.find((i) => i.article_id === id)
    if (!item) throw new Error('That article is no longer waiting for review.')
    return item
  }

  // `pendingId` is the queue entry being decided; `publishedId` is the id the published version gets.
  const publish = (item: QueueItem, pendingId: string, publishedId: string, body: string, version: number) => {
    const retired = item.replaces?.article_id
    state.published = state.published.filter((a) => a.article_id !== retired)
    state.published.push({
      article_id: publishedId,
      title: item.title,
      body,
      confidence: item.confidence,
      version,
    })
    state.queue = state.queue.filter((i) => i.article_id !== pendingId)
  }

  return {
    mode: 'demo',
    async queue() {
      return [...state.queue].sort((a, b) => a.created_at.localeCompare(b.created_at))
    },
    async approve(id) {
      const item = take(id)
      publish(item, item.article_id, item.article_id, item.body, item.version)
      commit()
    },
    async reject(id) {
      const item = take(id)
      state.queue = state.queue.filter((i) => i.article_id !== item.article_id)
      commit()
    },
    async edit(id, body) {
      const item = take(id)
      state.seq += 1
      publish(item, item.article_id, `${id}-edit-${state.seq}`, body, item.version + 1)
      commit()
    },
    async context(query) {
      return rank(query, state.published).slice(0, 5)
    },
    reset() {
      state = fresh()
      commit()
    },
  }
}
