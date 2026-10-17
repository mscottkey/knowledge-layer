'use client'

import { useCallback, useEffect, useState } from 'react'
import { getBackend } from '@/lib/backend'
import type { Decision, QueueItem } from '@/lib/types'
import Confidence from './Confidence'
import DiffView from './DiffView'

const SOURCE_LABEL: Record<string, string> = {
  pr: 'Pull request',
  ticket: 'Ticket',
  slack: 'Slack',
  call: 'Call',
  doc: 'Doc',
}

function ago(iso: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000))
  if (minutes < 60) return `${minutes}m ago`
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)}h ago`
  return `${Math.round(minutes / 60 / 24)}d ago`
}

export default function ReviewConsole() {
  const backend = getBackend()
  const [items, setItems] = useState<QueueItem[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [decisions, setDecisions] = useState<Decision[]>([])

  const refresh = useCallback(async () => {
    try {
      const next = await backend.queue()
      setItems(next)
      setError(null)
      setSelected((current) => (next.some((i) => i.article_id === current) ? current : next[0]?.article_id ?? null))
    } catch (e) {
      setItems([])
      setError(e instanceof Error ? e.message : 'Could not load the queue.')
    }
  }, [backend])

  useEffect(() => {
    refresh()
  }, [refresh])

  const item = items?.find((i) => i.article_id === selected) ?? null

  async function decide(action: Decision['action'], run: () => Promise<void>, detail: string) {
    if (!item) return
    try {
      await run()
      setDecisions((d) => [
        { id: `${Date.now()}`, action, title: item.title, detail, at: new Date().toISOString() },
        ...d,
      ])
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work.')
    }
  }

  if (items === null) return <p className="text-sm text-slate-500">Loading…</p>

  return (
    <div>
      {error && <p className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</p>}

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <aside>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Waiting for review ({items.length})
          </h2>
          {items.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
              Nothing waiting. Everything that reached the queue has a decision.
            </p>
          ) : (
            <ul className="space-y-2">
              {items.map((i) => (
                <li key={i.article_id}>
                  <button
                    onClick={() => setSelected(i.article_id)}
                    className={`w-full rounded-lg border p-3 text-left ${
                      i.article_id === selected ? 'border-slate-900 bg-white shadow-sm' : 'border-slate-200 bg-white hover:border-slate-400'
                    }`}
                  >
                    <div className="mb-1 flex items-center justify-between">
                      <ReasonBadge reason={i.reason} />
                      <span className="text-xs text-slate-500">{ago(i.created_at)}</span>
                    </div>
                    <p className="text-sm font-medium text-slate-900">{i.title}</p>
                    <div className="mt-2">
                      <Confidence value={i.confidence} />
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {decisions.length > 0 && (
            <div className="mt-8">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Your decisions</h2>
              <ul className="space-y-2 text-sm">
                {decisions.map((d) => (
                  <li key={d.id} className="rounded-md bg-slate-100 px-3 py-2">
                    <span className="font-medium capitalize">{d.action}</span>{' '}
                    <span className="text-slate-700">{d.title}</span>
                    <p className="text-xs text-slate-500">{d.detail}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>

        <section>
          {item ? (
            <Detail
              key={item.article_id}
              item={item}
              onApprove={(note) =>
                decide('approved', () => backend.approve(item.article_id, note), item.replaces ? `Published v${item.version}; v${item.replaces.version} retired` : `Published v${item.version}`)
              }
              onReject={(note) => decide('rejected', () => backend.reject(item.article_id, note), 'Sent back to draft; agents never saw it')}
              onEdit={(body, note) =>
                decide('edited', () => backend.edit(item.article_id, body, note), `Published your text as v${item.version + 1}`)
              }
            />
          ) : (
            <div className="rounded-lg border border-dashed border-slate-300 p-12 text-center text-sm text-slate-500">
              Select an article to review.
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function ReasonBadge({ reason }: { reason: QueueItem['reason'] }) {
  return reason === 'conflict' ? (
    <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">Changes a live article</span>
  ) : (
    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">Low confidence</span>
  )
}

function Detail({
  item,
  onApprove,
  onReject,
  onEdit,
}: {
  item: QueueItem
  onApprove: (note?: string) => void
  onReject: (note?: string) => void
  onEdit: (body: string, note?: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(item.body)
  const [note, setNote] = useState('')
  const changed = draft.trim() !== item.body.trim() && draft.trim().length > 0

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-1 flex items-center gap-3">
          <ReasonBadge reason={item.reason} />
          <Confidence value={item.confidence} />
        </div>
        <h2 className="text-xl font-semibold text-slate-900">{item.title}</h2>
        <p className="mt-1 text-sm text-slate-600">
          {item.reason === 'conflict'
            ? `Proposed version ${item.version} would replace the live version ${item.replaces?.version}. Agents keep getting the live one until you approve.`
            : 'New article. It scored below the auto-publish threshold, so agents cannot retrieve it until you approve.'}
        </p>
      </div>

      {item.replaces ? (
        <DiffView
          before={item.replaces.body}
          after={editing ? draft : item.body}
          beforeLabel={`Live now · v${item.replaces.version} · ${Math.round(item.replaces.confidence * 100)}%`}
          afterLabel={`${editing ? 'Your edit' : 'Proposed'} · v${editing ? item.version + 1 : item.version}`}
        />
      ) : (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Proposed · v{item.version}</h4>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">{editing ? draft : item.body}</p>
        </div>
      )}

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Built from {item.sources.length} signal{item.sources.length === 1 ? '' : 's'}
        </h3>
        <ul className="space-y-2">
          {item.sources.map((s) => (
            <li key={`${s.source_id}-${s.ingested_at}`} className="rounded-lg border border-slate-200 bg-white p-3">
              <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span className="rounded bg-slate-100 px-1.5 py-0.5 font-medium text-slate-700">{SOURCE_LABEL[s.source] ?? s.source}</span>
                <span className="font-mono">{s.source_id}</span>
                <span title="How much this source type is trusted">authority {s.authority.toFixed(1)}</span>
                <span>{ago(s.ingested_at)}</span>
              </div>
              <p className="text-sm text-slate-800">“{s.excerpt}”</p>
            </li>
          ))}
        </ul>
      </div>

      {editing && (
        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Edit the article</label>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={6}
            className="w-full rounded-lg border border-slate-300 p-3 text-sm leading-relaxed"
          />
        </div>
      )}

      <div>
        <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Note (optional, goes in the audit log)</label>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          placeholder="Why you made this call"
        />
      </div>

      <div className="flex flex-wrap gap-2">
        {editing ? (
          <>
            <button
              disabled={!changed}
              onClick={() => onEdit(draft.trim(), note || undefined)}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
            >
              Publish my edit
            </button>
            <button onClick={() => { setEditing(false); setDraft(item.body) }} className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-100">
              Cancel edit
            </button>
          </>
        ) : (
          <>
            <button onClick={() => onApprove(note || undefined)} className="rounded-md bg-green-700 px-4 py-2 text-sm font-medium text-white hover:bg-green-800">
              Approve and publish
            </button>
            <button onClick={() => setEditing(true)} className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-100">
              Edit first
            </button>
            <button onClick={() => onReject(note || undefined)} className="rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50">
              Reject
            </button>
          </>
        )}
      </div>
    </div>
  )
}
