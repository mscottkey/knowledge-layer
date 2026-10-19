// Shapes match the FastAPI responses in api/routers/review.py and api/routers/serve.py.

export type Reason = 'conflict' | 'low_confidence'

export interface SourceSignal {
  source: string
  source_id: string
  excerpt: string
  authority: number
  ingested_at: string
}

export interface ReplacedArticle {
  article_id: string
  title: string
  body: string
  version: number
  confidence: number
}

export interface QueueItem {
  article_id: string
  title: string
  body: string
  version: number
  confidence: number
  created_at: string
  reason: Reason
  replaces: ReplacedArticle | null
  sources: SourceSignal[]
}

export interface ContextResult {
  article_id: string
  title: string
  body: string
  confidence: number
  version: number
}

export interface Decision {
  id: string
  action: 'approved' | 'rejected' | 'edited'
  title: string
  detail: string
  at: string
}

export interface Backend {
  mode: 'demo' | 'live'
  queue(): Promise<QueueItem[]>
  approve(id: string, note?: string): Promise<void>
  reject(id: string, note?: string): Promise<void>
  edit(id: string, body: string, note?: string): Promise<void>
  context(query: string): Promise<ContextResult[]>
  reset?(): void
}
