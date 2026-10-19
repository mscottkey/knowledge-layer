'use client'

import { createDemoBackend } from './demo-backend'
import { createLiveBackend } from './live-backend'
import type { Backend } from './types'

// With NEXT_PUBLIC_API_URL set, the console talks to a real KnowledgeLayer API. Without it, it
// runs on the sample data in the browser, which is what the public demo does.
let backend: Backend | null = null

export function getBackend(): Backend {
  if (!backend) {
    const url = process.env.NEXT_PUBLIC_API_URL
    backend = url ? createLiveBackend(url) : createDemoBackend()
  }
  return backend
}
