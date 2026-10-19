'use client'

import { useState } from 'react'
import { getBackend } from '@/lib/backend'
import { SUGGESTED_QUERIES } from '@/lib/demo-data'
import type { ContextResult } from '@/lib/types'
import Confidence from './Confidence'

export default function AgentView() {
  const backend = getBackend()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<ContextResult[] | null>(null)
  const [asked, setAsked] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function ask(q: string) {
    if (!q.trim()) return
    setQuery(q)
    setAsked(q)
    try {
      setResults(await backend.context(q))
      setError(null)
    } catch (e) {
      setResults(null)
      setError(e instanceof Error ? e.message : 'The request failed.')
    }
  }

  return (
    <div className="max-w-3xl">
      <h1 className="text-xl font-semibold text-slate-900">What agents get</h1>
      <p className="mt-1 mb-5 text-sm text-slate-600">
        This is what a support agent receives when it asks for context. Only published articles come back. Anything
        waiting in the review queue stays out. Ask a question, then approve something in the queue and ask again.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          ask(query)
        }}
        className="flex gap-2"
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask the knowledge base a question"
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
        <button className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white">Ask</button>
      </form>

      {backend.mode === 'demo' && (
        <div className="mt-3 flex flex-wrap gap-2">
          {SUGGESTED_QUERIES.map((q) => (
            <button key={q} onClick={() => ask(q)} className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-700 hover:bg-slate-100">
              {q}
            </button>
          ))}
        </div>
      )}

      {error && <p className="mt-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</p>}

      {results && (
        <div className="mt-6">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            {results.length} published article{results.length === 1 ? '' : 's'} for “{asked}”
          </h2>
          {results.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
              Nothing published answers this yet. The agent gets no context and should hand off to a person.
            </p>
          ) : (
            <ul className="space-y-3">
              {results.map((r) => (
                <li key={r.article_id} className="rounded-lg border border-slate-200 bg-white p-4">
                  <div className="mb-1 flex items-center justify-between gap-3">
                    <h3 className="text-sm font-semibold text-slate-900">{r.title}</h3>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-slate-500">v{r.version}</span>
                      <Confidence value={r.confidence} />
                    </div>
                  </div>
                  <p className="text-sm leading-relaxed text-slate-700">{r.body}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
