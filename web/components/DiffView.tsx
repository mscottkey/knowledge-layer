import { diffWords, type Part } from '@/lib/diff'

function Words({ parts }: { parts: Part[] }) {
  return (
    <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
      {parts.map((p, i) =>
        p.kind === 'same' ? (
          <span key={i}>{p.text}</span>
        ) : (
          <span
            key={i}
            className={p.kind === 'removed' ? 'rounded bg-red-100 text-red-800 line-through' : 'rounded bg-green-100 text-green-900'}
          >
            {p.text}
          </span>
        ),
      )}
    </p>
  )
}

export default function DiffView({
  before,
  after,
  beforeLabel,
  afterLabel,
}: {
  before: string
  after: string
  beforeLabel: string
  afterLabel: string
}) {
  const diff = diffWords(before, after)
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{beforeLabel}</h4>
        <Words parts={diff.before} />
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{afterLabel}</h4>
        <Words parts={diff.after} />
      </div>
    </div>
  )
}
