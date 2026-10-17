import type { Metadata } from 'next'
import './globals.css'
import Shell from '@/components/Shell'

export const metadata: Metadata = {
  title: 'KnowledgeLayer',
  description: 'A reviewed knowledge base for AI support agents',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900">
        <Shell>{children}</Shell>
      </body>
    </html>
  )
}
