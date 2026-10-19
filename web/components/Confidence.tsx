import { THRESHOLD } from '@/lib/demo-data'

export default function Confidence({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  return (
    <div className="flex items-center gap-2" title={`Auto-publishes at ${THRESHOLD * 100}% and above`}>
      <div className="relative h-1.5 w-20 rounded-full bg-slate-200">
        <div className={`h-full rounded-full ${value >= THRESHOLD ? 'bg-green-500' : 'bg-amber-500'}`} style={{ width: `${pct}%` }} />
        <div className="absolute -top-0.5 h-2.5 w-px bg-slate-500" style={{ left: `${THRESHOLD * 100}%` }} />
      </div>
      <span className="text-xs tabular-nums text-slate-600">{pct}%</span>
    </div>
  )
}
