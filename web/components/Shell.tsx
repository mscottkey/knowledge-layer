'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { getBackend } from '@/lib/backend'
import { getStoredKey, storeKey } from '@/lib/live-backend'

const tabs = [
  { href: '/queue', label: 'Review queue' },
  { href: '/agents', label: 'What agents get' },
]

export default function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const [mode, setMode] = useState<'demo' | 'live' | null>(null)

  useEffect(() => setMode(getBackend().mode), [])

  return (
    <div className="mx-auto max-w-6xl px-4 pb-16">
      <header className="flex flex-wrap items-center justify-between gap-3 py-5">
        <div className="flex items-center gap-6">
          <Link href="/queue" className="text-lg font-semibold tracking-tight text-slate-900">
            KnowledgeLayer
          </Link>
          <nav className="flex gap-1">
            {tabs.map((t) => (
              <Link
                key={t.href}
                href={t.href}
                className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium ${
                  pathname === t.href ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-200'
                }`}
              >
                {t.label}
              </Link>
            ))}
          </nav>
        </div>
        {mode === 'live' && <KeyField />}
      </header>

      {mode === 'demo' && <DemoBanner />}
      {children}
    </div>
  )
}

function DemoBanner() {
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <p>
        <strong>Demo with sample data</strong> for a fictional product. Approving, editing and rejecting follow the
        same rules as the API, but nothing here is stored on a server.
      </p>
      <button
        onClick={() => {
          getBackend().reset?.()
          window.location.reload()
        }}
        className="rounded-md border border-amber-300 bg-white px-3 py-1.5 font-medium hover:bg-amber-100"
      >
        Reset demo
      </button>
    </div>
  )
}

function KeyField() {
  const [key, setKey] = useState('')
  useEffect(() => setKey(getStoredKey()), [])
  return (
    <label className="flex items-center gap-2 text-sm text-slate-600">
      API key
      <input
        type="password"
        value={key}
        placeholder="kl_live_…"
        onChange={(e) => {
          setKey(e.target.value)
          storeKey(e.target.value)
        }}
        onBlur={() => window.location.reload()}
        className="w-56 rounded-md border border-slate-300 px-2 py-1 font-mono text-xs"
      />
    </label>
  )
}
