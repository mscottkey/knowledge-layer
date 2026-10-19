import type { ContextResult, QueueItem } from './types'

// A fictional B2B analytics product, "Acme Cloud". Everything here is invented for the demo.
// The queue items are shaped like real review-queue responses from the API.

const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString()

export const THRESHOLD = 0.8

export const seedPublished = (): ContextResult[] => [
  {
    article_id: 'pub-export',
    title: 'Exporting reports from the Dashboard',
    body: 'Reports can be exported from the Dashboard as CSV or PDF. CSV exports are limited to 10,000 rows. For larger exports, use the Export API. PDF exports include charts and are limited to the first 50 pages.',
    confidence: 0.91,
    version: 1,
  },
  {
    article_id: 'pub-webhooks',
    title: 'Webhook delivery and retries',
    body: 'Acme Cloud signs every webhook with an HMAC header. If your endpoint does not return a 2xx response, we retry 3 times, 1 minute apart. After the third failure the event is dropped and appears in the delivery log for 7 days.',
    confidence: 0.88,
    version: 2,
  },
  {
    article_id: 'pub-sso',
    title: 'Setting up SSO with Okta',
    body: 'Create a SAML app in Okta and paste the metadata URL into Settings, Security, Single sign-on. Users are provisioned on first sign-in. Admins can still sign in with a password if SSO is misconfigured.',
    confidence: 0.93,
    version: 1,
  },
]

export const seedQueue = (): QueueItem[] => [
  {
    article_id: 'pend-export-v2',
    title: 'Exporting reports from the Dashboard',
    body: 'Reports can be exported from the Dashboard as CSV. PDF export was removed in release 4.12. CSV exports are limited to 50,000 rows. For larger exports, use the Export API.',
    version: 2,
    confidence: 0.62,
    created_at: minutesAgo(14),
    reason: 'conflict',
    replaces: {
      article_id: 'pub-export',
      title: 'Exporting reports from the Dashboard',
      body: 'Reports can be exported from the Dashboard as CSV or PDF. CSV exports are limited to 10,000 rows. For larger exports, use the Export API. PDF exports include charts and are limited to the first 50 pages.',
      version: 1,
      confidence: 0.91,
    },
    sources: [
      {
        source: 'pr',
        source_id: 'acme/web#4312',
        excerpt: 'Remove PDF export from the Dashboard. The renderer is being retired. Raise the CSV export limit from 10k to 50k rows.',
        authority: 1.0,
        ingested_at: minutesAgo(180),
      },
      {
        source: 'ticket',
        source_id: 'ZD-88213',
        excerpt: "Customer says the PDF button disappeared from their Dashboard after this week's update. They need it for a board report on Friday.",
        authority: 0.7,
        ingested_at: minutesAgo(95),
      },
      {
        source: 'slack',
        source_id: '#support-leads',
        excerpt: "I'm pretty sure PDF export still works if you open it from the report page instead of the Dashboard.",
        authority: 0.5,
        ingested_at: minutesAgo(40),
      },
    ],
  },
  {
    article_id: 'pend-webhooks-v3',
    title: 'Webhook delivery and retries',
    body: 'Acme Cloud signs every webhook with an HMAC header. If your endpoint does not return a 2xx response, we retry 5 times with exponential backoff, starting at 1 minute. After the fifth failure the event is dropped and appears in the delivery log for 7 days.',
    version: 3,
    confidence: 0.74,
    created_at: minutesAgo(52),
    reason: 'conflict',
    replaces: {
      article_id: 'pub-webhooks',
      title: 'Webhook delivery and retries',
      body: 'Acme Cloud signs every webhook with an HMAC header. If your endpoint does not return a 2xx response, we retry 3 times, 1 minute apart. After the third failure the event is dropped and appears in the delivery log for 7 days.',
      version: 2,
      confidence: 0.88,
    },
    sources: [
      {
        source: 'pr',
        source_id: 'acme/api#2290',
        excerpt: 'Webhook retries: 5 attempts with exponential backoff (1m, 2m, 4m, 8m, 16m). Delivery log retention unchanged at 7 days.',
        authority: 1.0,
        ingested_at: minutesAgo(300),
      },
      {
        source: 'call',
        source_id: 'gong/call-5521',
        excerpt: 'Customer: "We saw the same event delivered four times over about fifteen minutes." Agent confirmed retries are longer now.',
        authority: 0.6,
        ingested_at: minutesAgo(130),
      },
    ],
  },
  {
    article_id: 'pend-sso-reset',
    title: 'Resetting an SSO connection after a domain change',
    body: 'If your company changes its email domain, update the domain under Settings, Security, Single sign-on before users sign in again. Users on the old domain are locked out until the connection is reset by an admin.',
    version: 1,
    confidence: 0.55,
    created_at: minutesAgo(120),
    reason: 'low_confidence',
    replaces: null,
    sources: [
      {
        source: 'ticket',
        source_id: 'ZD-88190',
        excerpt: 'We rebranded and our emails moved to a new domain. Nobody can log in with SSO since Monday. How do we fix the connection?',
        authority: 0.7,
        ingested_at: minutesAgo(120),
      },
    ],
  },
  {
    article_id: 'pend-rate-limits',
    title: 'Rate limits for the Export API',
    body: 'The Export API allows 60 requests per minute per workspace. Requests over the limit return 429 with a Retry-After header.',
    version: 1,
    confidence: 0.41,
    created_at: minutesAgo(200),
    reason: 'low_confidence',
    replaces: null,
    sources: [
      {
        source: 'slack',
        source_id: '#eng-support',
        excerpt: "I think it's 60 a minute but don't quote me, check with platform.",
        authority: 0.5,
        ingested_at: minutesAgo(200),
      },
    ],
  },
]

export const SUGGESTED_QUERIES = [
  'Can I export a PDF from the Dashboard?',
  'How many times are webhooks retried?',
  'How do I fix SSO after we changed our email domain?',
  'What is the Export API rate limit?',
]
